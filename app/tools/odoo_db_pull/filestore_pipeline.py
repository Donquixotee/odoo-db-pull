import asyncio
import os
import shutil
import subprocess
import tarfile
import tempfile
from typing import AsyncGenerator, Optional

from .ssh_utils import SshClient


class FilestorePipeline:
    """
    Fetches the filestore tar from the SOURCE server and deploys it
    to the TARGET — which is the same destination chosen for the DB pull.

    Target modes (mirror the DB pull targetMode):
      - "local"        : deploy to a local filesystem path or local Docker container
      - "same_server"  : deploy on the source server itself (SSH already available)
      - "remote"       : deploy on a different remote server via target_ssh
    """

    def __init__(
        self,
        source_ssh: SshClient,                  # always needed — tar lives here
        target_ssh: Optional[SshClient] = None,  # only for "remote" mode
    ):
        self._source_ssh = source_ssh
        self._target_ssh = target_ssh

    def _event(self, message: str, status: str = "info") -> str:
        return f"data: {status}|{message}\n\n"

    async def run(
        self,
        tar_remote_path: str,   # path on the SOURCE server
        db_name: str,
        target_mode: str,       # "local" | "same_server" | "remote"
        # ── local mode ──────────────────────────────────────────────────────────
        target_local_path: Optional[str] = None,         # filesystem path
        target_docker_container: Optional[str] = None,  # docker container name
        target_docker_internal_path: str = "/var/lib/odoo/filestore",
        # ── same_server / remote mode ────────────────────────────────────────────
        target_server_path: Optional[str] = None,       # base filestore dir on server
        target_sudo_password: Optional[str] = None,     # sudo on target server
        odoo_user: str = "odoo",
    ) -> AsyncGenerator[str, None]:

        # ── Step 1: Connect to source and validate remote file ──────────────────
        yield self._event("Connecting to source server…")
        try:
            await asyncio.to_thread(self._source_ssh.connect)
        except Exception as e:
            yield self._event(f"Source SSH connection failed: {e}", "error")
            return

        try:
            yield self._event(f"Checking file on source: {tar_remote_path}…")
            try:
                size_bytes = await asyncio.to_thread(
                    self._source_ssh.file_size, tar_remote_path
                )
                size_mb = round(size_bytes / 1024 / 1024, 1)
                yield self._event(f"Found: {tar_remote_path} ({size_mb} MB)")
            except Exception as e:
                yield self._event(
                    f"File not found on source server: {tar_remote_path} → {e}", "error"
                )
                return

            # ── Dispatch to the appropriate deployment strategy ────────────────
            if target_mode == "same_server":
                # Most efficient: do everything over SSH on the source server,
                # no local download needed.
                async for msg in self._deploy_same_server(
                    tar_remote_path, db_name,
                    target_server_path, target_sudo_password, odoo_user
                ):
                    yield msg

            elif target_mode == "local":
                # Download to local temp, then deploy locally
                async for msg in self._deploy_local(
                    tar_remote_path, db_name,
                    target_local_path, target_docker_container,
                    target_docker_internal_path
                ):
                    yield msg

            elif target_mode == "remote":
                # Download to local temp, then push to remote target
                async for msg in self._deploy_remote(
                    tar_remote_path, db_name,
                    target_server_path, target_sudo_password, odoo_user
                ):
                    yield msg

            else:
                yield self._event(f"Unknown target_mode: {target_mode}", "error")
                return

            yield self._event("✓ Filestore deployed successfully!", "success")

        finally:
            try:
                await asyncio.to_thread(self._source_ssh.disconnect)
            except Exception:
                pass

    # ── same_server: extract + sudo mv entirely on the source server ───────────

    async def _deploy_same_server(
        self,
        tar_remote_path: str,
        db_name: str,
        target_server_path: Optional[str],
        sudo_password: Optional[str],
        odoo_user: str,
    ) -> AsyncGenerator[str, None]:
        """
        Everything happens on the source server via SSH:
          1. tar xzf → /tmp/odoo_fs_XXXX/
          2. sudo mv  → target_server_path/db_name
          3. sudo chown odoo:odoo
        No local download needed.
        """
        if not target_server_path:
            yield self._event(
                "No target server path specified (e.g. /var/lib/odoo/filestore).", "error"
            )
            return

        yield self._event("Deploying directly on source server (same_server mode)…")
        try:
            for msg in await asyncio.to_thread(
                lambda: list(
                    self._source_ssh.extract_and_place(
                        tar_remote_path,
                        target_server_path,
                        db_name=db_name,
                        sudo_password=sudo_password,
                        odoo_user=odoo_user,
                    )
                )
            ):
                yield self._event(f"  {msg}")
        except Exception as e:
            yield self._event(f"same_server deploy failed: {e}", "error")

    # ── local: download then local copy / docker cp ────────────────────────────

    async def _deploy_local(
        self,
        tar_remote_path: str,
        db_name: str,
        target_local_path: Optional[str],
        target_docker_container: Optional[str],
        target_docker_internal_path: str,
    ) -> AsyncGenerator[str, None]:
        """Download the tar via SFTP then deploy locally (path or docker)."""
        tmp_dir = tempfile.mkdtemp(prefix="odoo_filestore_")
        local_tar = os.path.join(tmp_dir, os.path.basename(tar_remote_path))

        try:
            yield self._event("Downloading filestore tar from source server…")
            try:
                await asyncio.to_thread(self._source_ssh.download, tar_remote_path, local_tar)
            except Exception as e:
                yield self._event(f"Download failed: {e}", "error")
                return

            yield self._event("Validating archive…")
            if not tarfile.is_tarfile(local_tar):
                yield self._event("Downloaded file is not a valid tar archive.", "error")
                return

            # Extract to local sub-dir
            extract_dir = os.path.join(tmp_dir, "extracted")
            os.makedirs(extract_dir, exist_ok=True)
            yield self._event("Extracting archive…")
            try:
                await asyncio.to_thread(self._extract_tar, local_tar, extract_dir)
            except Exception as e:
                yield self._event(f"Extraction failed: {e}", "error")
                return

            # Determine src_dir
            entries = os.listdir(extract_dir)
            if not entries:
                yield self._event("Tar archive is empty.", "error")
                return
            if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
                src_dir = os.path.join(extract_dir, entries[0])
            else:
                src_dir = extract_dir

            yield self._event(f"Extraction done. Deploying as '{db_name}'…")

            if target_docker_container:
                async for msg in self._copy_to_docker(
                    src_dir, db_name,
                    target_docker_container, target_docker_internal_path
                ):
                    yield msg
            elif target_local_path:
                async for msg in self._copy_to_local_path(src_dir, db_name, target_local_path):
                    yield msg
            else:
                yield self._event(
                    "No local target specified (need path or docker container).", "error"
                )

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── remote: download locally then push to remote target server ────────────

    async def _deploy_remote(
        self,
        tar_remote_path: str,
        db_name: str,
        target_server_path: Optional[str],
        sudo_password: Optional[str],
        odoo_user: str,
    ) -> AsyncGenerator[str, None]:
        """Download tar from source, upload to remote target, extract + sudo mv."""
        if not target_server_path:
            yield self._event("No target remote path specified.", "error")
            return
        if not self._target_ssh:
            yield self._event("No SSH client configured for remote target.", "error")
            return

        tmp_dir = tempfile.mkdtemp(prefix="odoo_filestore_")
        local_tar = os.path.join(tmp_dir, os.path.basename(tar_remote_path))

        try:
            yield self._event("Downloading filestore tar from source server…")
            try:
                await asyncio.to_thread(self._source_ssh.download, tar_remote_path, local_tar)
            except Exception as e:
                yield self._event(f"Download from source failed: {e}", "error")
                return

            yield self._event("Connecting to target server…")
            try:
                await asyncio.to_thread(self._target_ssh.connect)
            except Exception as e:
                yield self._event(f"Target SSH connection failed: {e}", "error")
                return

            try:
                for msg in await asyncio.to_thread(
                    lambda: list(
                        self._target_ssh.upload_tar_and_extract(
                            local_tar,
                            target_server_path,
                            db_name=db_name,
                            sudo_password=sudo_password,
                            odoo_user=odoo_user,
                        )
                    )
                ):
                    yield self._event(f"  {msg}")
            finally:
                await asyncio.to_thread(self._target_ssh.disconnect)

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── local helpers ──────────────────────────────────────────────────────────

    def _extract_tar(self, tar_path: str, dest_dir: str) -> None:
        with tarfile.open(tar_path, "r:*") as tar:
            tar.extractall(dest_dir)

    async def _copy_to_local_path(
        self, src_dir: str, db_name: str, target_local_path: str
    ) -> AsyncGenerator[str, None]:
        dest = os.path.join(target_local_path, db_name)
        yield self._event(f"Copying to local path: {dest}…")
        try:
            def _copy():
                if os.path.exists(dest):
                    shutil.rmtree(dest)
                shutil.copytree(src_dir, dest)
            await asyncio.to_thread(_copy)
            yield self._event(f"✓ Files copied to {dest}")
        except Exception as e:
            yield self._event(f"Local copy failed: {e}", "error")

    async def _copy_to_docker(
        self,
        src_dir: str,
        db_name: str,
        container: str,
        internal_path: str,
    ) -> AsyncGenerator[str, None]:
        dest_in_container = f"{internal_path}/{db_name}"
        yield self._event(f"Deploying to Docker '{container}' → {dest_in_container}…")
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["docker", "exec", container, "rm", "-rf", dest_in_container],
                capture_output=True,
            )
            await asyncio.to_thread(
                subprocess.run,
                ["docker", "exec", container, "mkdir", "-p", internal_path],
                capture_output=True,
            )
            named_src = os.path.join(os.path.dirname(src_dir), db_name)
            if src_dir != named_src:
                os.rename(src_dir, named_src)
                src_dir = named_src
            result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "cp", src_dir, f"{container}:{internal_path}"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                yield self._event(f"docker cp failed: {result.stderr.strip()}", "error")
                return
            yield self._event(f"✓ Copied to container {container}:{dest_in_container}")
        except Exception as e:
            yield self._event(f"Docker deployment failed: {e}", "error")
