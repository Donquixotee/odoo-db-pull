import io
import os
import subprocess
import tarfile
from typing import Optional


def _docker_client():
    import docker
    return docker.from_env()


class LocalDb:
    """
    Handles local PostgreSQL operations.

    Two modes:
    - Native (docker_container=None): connects to the host PostgreSQL via TCP
      (localhost by default).  Because the app runs as root inside Docker,
      unix-socket peer auth won't work — TCP + password/trust is required.
    - Docker (docker_container=<name>): routes all commands through the Docker
      SDK (docker exec), copying dump files in via put_archive.
    """

    def __init__(
        self,
        pg_user: Optional[str] = None,
        pg_password: Optional[str] = None,
        pg_host: str = "localhost",
        pg_port: Optional[int] = None,
        docker_container: Optional[str] = None,
    ):
        self._pg_user = pg_user or os.getenv("PGUSER") or os.getenv("USER") or "postgres"
        self._pg_password = pg_password
        self._pg_host = pg_host
        self._pg_port = pg_port
        self._container_name = docker_container

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _container(self):
        return _docker_client().containers.get(self._container_name)

    def _docker_exec(self, cmd: list[str]) -> str:
        """Run a command inside the postgres container via Docker SDK."""
        env = {"PGPASSWORD": self._pg_password} if self._pg_password else None
        result = self._container().exec_run(cmd, demux=True, environment=env)
        exit_code = result.exit_code
        stdout = (result.output[0] or b"").decode()
        stderr = (result.output[1] or b"").decode()
        if exit_code != 0:
            raise RuntimeError(stderr.strip() or stdout.strip())
        return stdout.strip()

    def _run(self, cmd: list[str]) -> subprocess.CompletedProcess:
        """Run a command locally via subprocess."""
        env = None
        if self._pg_password:
            env = {**os.environ, "PGPASSWORD": self._pg_password}
        return subprocess.run(cmd, capture_output=True, text=True, env=env)

    @property
    def _native_conn_args(self) -> list[str]:
        """Return [-h host, -p port] for native mode, [] for docker mode."""
        if self._container_name:
            return []
        args = []
        if self._pg_host:
            args.extend(["-h", self._pg_host])
        if self._pg_port:
            args.extend(["-p", str(self._pg_port)])
        return args

    def _psql(self, sql: str, dbname: str = "postgres") -> str:
        cmd = ["psql", "-U", self._pg_user, *self._native_conn_args,
               "-d", dbname, "-t", "-A", "-c", sql]
        if self._container_name:
            return self._docker_exec(cmd)
        result = self._run(cmd)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        return result.stdout.strip()

    # ── Public API ────────────────────────────────────────────────────────────

    def exists(self, dbname: str) -> bool:
        out = self._psql(f"SELECT 1 FROM pg_database WHERE datname = '{dbname}';")
        return out.strip() == "1"

    def rename(self, old_name: str, new_name: str) -> None:
        self._psql(f'ALTER DATABASE "{old_name}" RENAME TO "{new_name}";')

    def create(self, dbname: str) -> None:
        cmd = ["createdb", "-U", self._pg_user, *self._native_conn_args, dbname]
        if self._container_name:
            self._docker_exec(cmd)
        else:
            result = self._run(cmd)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip())

    def drop(self, dbname: str) -> None:
        cmd = ["dropdb", "-U", self._pg_user, *self._native_conn_args, "--if-exists", dbname]
        if self._container_name:
            self._docker_exec(cmd)
        else:
            result = self._run(cmd)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip())

    def restore(self, dbname: str, dump_path: str) -> None:
        if self._container_name:
            # Stream the dump file into the container as a tar archive
            container_dump = f"/tmp/{os.path.basename(dump_path)}"
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tar:
                tar.add(dump_path, arcname=os.path.basename(dump_path))
            buf.seek(0)
            self._container().put_archive("/tmp", buf)

            cmd = ["pg_restore", "-U", self._pg_user, "-d", dbname,
                   "--no-owner", "-j", "4", container_dump]
            result = self._container().exec_run(cmd, demux=True)
            stderr = (result.output[1] or b"").decode()
            if result.exit_code >= 2:
                raise RuntimeError(stderr.strip())
        else:
            result = self._run(
                ["pg_restore", "-U", self._pg_user, *self._native_conn_args,
                 "-d", dbname, "--no-owner", "-j", "4", dump_path]
            )
            # pg_restore exits 1 on warnings — only fail on exit 2+
            if result.returncode >= 2:
                raise RuntimeError(result.stderr.strip())

    def list_databases(self) -> list[str]:
        out = self._psql(
            "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname;"
        )
        return [line for line in out.splitlines() if line]


def list_local_docker_pg_containers() -> list[dict]:
    """
    Return local Docker containers that look like postgres instances.
    Uses the Docker Python SDK — no CLI binary required.
    """
    client = _docker_client()
    containers = []
    for c in client.containers.list():
        name = c.name
        image = c.image.tags[0] if c.image.tags else c.image.short_id
        status = c.status
        if (
            "postgres" in image.lower()
            or "postgres" in name.lower()
            or name.endswith("_db")
            or name.endswith("-db")
        ):
            containers.append({"name": name, "image": image, "status": status})
    return containers
