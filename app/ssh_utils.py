import os
import shlex
from typing import Optional, Generator
import paramiko
from .ssh_config import SshHostEntry


def _shell_quote(s: str) -> str:
    """Safely shell-quote a string to prevent injection."""
    return shlex.quote(s)


class SshClient:
    """Handles all SSH transport: exec, SFTP download/upload."""

    def __init__(self, entry: SshHostEntry, password: Optional[str] = None):
        self._entry = entry
        self._password = password
        self._client: Optional[paramiko.SSHClient] = None

    def connect(self) -> None:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: dict = dict(
            hostname=self._entry.hostname,
            port=self._entry.port,
            username=self._entry.user,
            timeout=15,
        )

        if self._entry.identity_file and os.path.exists(self._entry.identity_file):
            connect_kwargs["key_filename"] = self._entry.identity_file

        if self._password:
            connect_kwargs["password"] = self._password

        client.connect(**connect_kwargs)
        self._client = client

    def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def exec(self, command: str) -> tuple[str, str]:
        """Run command, return (stdout, stderr). Raises on non-zero exit."""
        if not self._client:
            raise RuntimeError("Not connected")
        _, stdout, stderr = self._client.exec_command(command)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        if exit_code != 0:
            raise RuntimeError(f"Command failed (exit {exit_code}): {err.strip() or command}")
        return out, err

    def exec_sudo(
        self, command: str, sudo_password: Optional[str] = None
    ) -> tuple[str, str]:
        """
        Run a command with sudo, piping the password via stdin.
        Falls back to exec() (no sudo) if sudo_password is not provided.
        """
        if not sudo_password:
            return self.exec(command)
        sudo_cmd = f"echo {_shell_quote(sudo_password)} | sudo -S -p '' {command}"
        return self.exec(sudo_cmd)

    def download(self, remote_path: str, local_path: str) -> None:
        """Download a file via SFTP."""
        if not self._client:
            raise RuntimeError("Not connected")
        sftp = self._client.open_sftp()
        try:
            sftp.get(remote_path, local_path)
        finally:
            sftp.close()

    def file_size(self, remote_path: str) -> int:
        """Return size in bytes of a remote file via SFTP stat. Raises if not found."""
        if not self._client:
            raise RuntimeError("Not connected")
        sftp = self._client.open_sftp()
        try:
            attr = sftp.stat(remote_path)
            return attr.st_size or 0
        finally:
            sftp.close()

    def upload(self, local_path: str, remote_path: str) -> None:
        """Upload a file via SFTP."""
        if not self._client:
            raise RuntimeError("Not connected")
        sftp = self._client.open_sftp()
        try:
            sftp.put(local_path, remote_path)
        finally:
            sftp.close()

    def file_size(self, remote_path: str) -> int:
        """Return file size in bytes for a remote path."""
        if not self._client:
            raise RuntimeError("Not connected")
        sftp = self._client.open_sftp()
        try:
            return sftp.stat(remote_path).st_size or 0
        finally:
            sftp.close()

    def upload_tar_and_extract(
        self,
        local_tar_path: str,
        remote_dest_dir: str,
        db_name: str = "",
        sudo_password: Optional[str] = None,
        odoo_user: str = "odoo",
    ) -> Generator[str, None, None]:
        """
        Upload a local .tar.gz via SFTP, extract to a tmp dir on the remote,
        then sudo-move + sudo-chown it to the final destination.

        Strategy:
          1. Upload tar to /tmp/<name>.tar.gz
          2. Extract to /tmp/<tmp_dir>/ (no sudo needed, /tmp is world-writable)
          3. sudo mv /tmp/<tmp_dir>/<db_name>  →  <remote_dest_dir>/<db_name>
          4. sudo chown -R odoo:odoo <remote_dest_dir>/<db_name>
          5. Cleanup /tmp artefacts

        Yields progress strings.
        """
        if not self._client:
            raise RuntimeError("Not connected")

        import uuid
        tar_name = os.path.basename(local_tar_path)
        remote_tar = f"/tmp/{tar_name}"
        tmp_extract = f"/tmp/odoo_fs_{uuid.uuid4().hex[:8]}"

        # ── 1. Upload ──────────────────────────────────────────────────────────
        yield f"Uploading {tar_name} to remote…"
        sftp = self._client.open_sftp()
        try:
            sftp.put(local_tar_path, remote_tar)
        finally:
            sftp.close()
        yield "Upload complete."

        try:
            # ── 2. Extract to writable tmp dir ─────────────────────────────────
            yield f"Extracting to temp dir {tmp_extract}…"
            self.exec(f"mkdir -p {tmp_extract}")
            self.exec(f"tar xzf {remote_tar} -C {tmp_extract}")
            yield "Extraction complete."

            # Determine what got extracted (should be a single dir = db_name)
            out, _ = self.exec(f"ls {tmp_extract}")
            entries = [e.strip() for e in out.strip().splitlines() if e.strip()]
            if not entries:
                raise RuntimeError("Tar archive extracted empty.")
            # Use the extracted folder name if db_name not specified
            extracted_folder = entries[0]
            src_path = f"{tmp_extract}/{extracted_folder}"
            dest_folder = db_name or extracted_folder
            final_dest = f"{remote_dest_dir}/{dest_folder}"

            # ── 3. Sudo: ensure dest dir, remove old, mv new ───────────────────
            yield f"Moving to final destination: {final_dest}…"
            self.exec_sudo(f"mkdir -p {remote_dest_dir}", sudo_password)

            # Remove old filestore folder if it exists
            try:
                self.exec_sudo(f"rm -rf {final_dest}", sudo_password)
            except Exception:
                pass

            self.exec_sudo(f"mv {src_path} {final_dest}", sudo_password)
            yield "Files moved to destination."

            # ── 4. Fix ownership ───────────────────────────────────────────────
            yield f"Setting ownership to {odoo_user}:{odoo_user}…"
            try:
                self.exec_sudo(
                    f"chown -R {odoo_user}:{odoo_user} {final_dest}", sudo_password
                )
                yield "Ownership set."
            except Exception as e:
                yield f"Warning: chown failed ({e}) — continuing"

        finally:
            # ── 5. Cleanup remote temp artefacts ───────────────────────────────
            for path in [remote_tar, tmp_extract]:
                try:
                    self.exec(f"rm -rf {path}")
                except Exception:
                    pass
            yield "Remote temp files cleaned up."

    def extract_and_place(
        self,
        remote_tar_path: str,
        remote_dest_dir: str,
        db_name: str = "",
        sudo_password: Optional[str] = None,
        odoo_user: str = "odoo",
    ) -> Generator[str, None, None]:
        """
        Extract a tar that already exists on this server into a tmp dir,
        then sudo mv + chown it to the final destination.
        Used for same_server mode — no local download required.

        Steps:
          1. Extract remote_tar_path → /tmp/odoo_fs_XXXX/
          2. sudo mv extracted_folder → remote_dest_dir/db_name
          3. sudo chown -R odoo_user
          4. Cleanup /tmp
        """
        import uuid
        if not self._client:
            raise RuntimeError("Not connected")

        tmp_extract = f"/tmp/odoo_fs_{uuid.uuid4().hex[:8]}"

        yield f"Extracting {remote_tar_path} to temp dir…"
        self.exec(f"mkdir -p {tmp_extract}")
        self.exec(f"tar xzf {remote_tar_path} -C {tmp_extract}")
        yield "Extraction complete."

        # Discover extracted folder name
        out, _ = self.exec(f"ls {tmp_extract}")
        entries = [e.strip() for e in out.strip().splitlines() if e.strip()]
        if not entries:
            raise RuntimeError("Tar archive extracted empty.")

        extracted_folder = entries[0]
        src_path = f"{tmp_extract}/{extracted_folder}"
        dest_folder = db_name or extracted_folder
        final_dest = f"{remote_dest_dir}/{dest_folder}"

        yield f"Placing at {final_dest}…"
        self.exec_sudo(f"mkdir -p {remote_dest_dir}", sudo_password)
        try:
            self.exec_sudo(f"rm -rf {final_dest}", sudo_password)
        except Exception:
            pass
        self.exec_sudo(f"mv {src_path} {final_dest}", sudo_password)
        yield "Files placed."

        yield f"Setting ownership → {odoo_user}:{odoo_user}…"
        try:
            self.exec_sudo(f"chown -R {odoo_user}:{odoo_user} {final_dest}", sudo_password)
            yield "Ownership set."
        except Exception as e:
            yield f"Warning: chown failed ({e})"

        # Cleanup
        try:
            self.exec(f"rm -rf {tmp_extract}")
        except Exception:
            pass
        yield "Temp dir cleaned up."

    def list_docker_containers(self) -> list[dict]:
        """Return list of running Docker containers with name and image."""
        out, _ = self.exec('docker ps --format "{{.Names}}|{{.Image}}|{{.Status}}"')
        containers = []
        for line in out.strip().splitlines():
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 2:
                containers.append({"name": parts[0], "image": parts[1], "status": parts[2] if len(parts) > 2 else ""})
        return containers

    def list_databases(self, db_container: str, db_user: str = "odoo") -> list[str]:
        """List postgres databases inside a Docker container."""
        out, _ = self.exec(
            f'docker exec {db_container} psql -U {db_user} -d postgres -t -A -c '
            f'"SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname;"'
        )
        return [line.strip() for line in out.strip().splitlines() if line.strip()]

    def detect_odoo_pairs(self) -> list[dict]:
        """Detect (odoo_container, db_container, filestore_path) pairs."""
        containers = self.list_docker_containers()
        names = {c["name"] for c in containers}
        pairs = []
        for c in containers:
            name = c["name"]
            db_candidate = next(
                (n for n in [f"{name}_db", f"{name}-db"] if n in names), None
            )
            if db_candidate is None:
                continue
            try:
                out, _ = self.exec(
                    f"docker inspect {name} --format "
                    f"'{{{{range .Mounts}}}}{{{{.Source}}}}|{{{{.Destination}}}}\\n{{{{end}}}}'"
                )
                filestore_path = None
                for line in out.strip().splitlines():
                    if "|/var/lib/odoo" in line:
                        source = line.split("|")[0]
                        filestore_path = os.path.join(source, "filestore")
                        break
            except Exception:
                filestore_path = None

            pairs.append({
                "odoo": name,
                "db": db_candidate,
                "filestore": filestore_path,
            })
        return pairs