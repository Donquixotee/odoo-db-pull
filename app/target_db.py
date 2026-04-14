import io
import os
import subprocess
import tarfile
from abc import ABC, abstractmethod
from typing import Optional

def _docker_client():
    import docker
    return docker.from_env()

class TargetDb(ABC):
    @abstractmethod
    def exists(self, dbname: str) -> bool:
        pass

    @abstractmethod
    def rename(self, old_name: str, new_name: str) -> None:
        pass

    @abstractmethod
    def create(self, dbname: str) -> None:
        pass

    @abstractmethod
    def drop(self, dbname: str) -> None:
        pass

    @abstractmethod
    def restore(self, dbname: str, dump_path: str) -> None:
        pass


class LocalDbTarget(TargetDb):
    """Handles local PostgreSQL operations (native or local docker)."""
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
        env = {"PGPASSWORD": self._pg_password} if self._pg_password else None
        result = self._container().exec_run(cmd, demux=True, environment=env)
        exit_code = result.exit_code
        stdout = (result.output[0] or b"").decode()
        stderr = (result.output[1] or b"").decode()
        if exit_code != 0:
            raise RuntimeError(stderr.strip() or stdout.strip())
        return stdout.strip()

    def _run(self, cmd: list[str]) -> subprocess.CompletedProcess:
        env = None
        if self._pg_password:
            env = {**os.environ, "PGPASSWORD": self._pg_password}
        return subprocess.run(cmd, capture_output=True, text=True, env=env)

    @property
    def _native_conn_args(self) -> list[str]:
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
            if result.returncode >= 2:
                raise RuntimeError(result.stderr.strip())


class RemoteDbTarget(TargetDb):
    """Handles PostgreSQL operations on a remote server over SSH."""
    def __init__(
        self,
        ssh,  # ssh_utils.SshClient
        pg_user: str = "postgres",
        docker_container: Optional[str] = None,
    ):
        self._ssh = ssh
        self._pg_user = pg_user
        self._container_name = docker_container

    def _escape(self, s: str) -> str:
        # dumb bash escape for command arguments
        return "'" + s.replace("'", "'\\''") + "'"

    def _psql(self, sql: str, dbname: str = "postgres") -> str:
        if self._container_name:
            # Note: assuming no password needed for docker exec as postgres user inside the correct container
            cmd = f'docker exec {self._container_name} psql -U {self._pg_user} -d {dbname} -t -A -c {self._escape(sql)}'
        else:
            # Note: assuming trust or .pgpass is configured on the remote
            cmd = f'psql -U {self._pg_user} -d {dbname} -t -A -c {self._escape(sql)}'
        
        stdout, _ = self._ssh.exec(cmd)
        return stdout.strip()

    def exists(self, dbname: str) -> bool:
        out = self._psql(f"SELECT 1 FROM pg_database WHERE datname = '{dbname}';")
        return out == "1"

    def rename(self, old_name: str, new_name: str) -> None:
        self._psql(f'ALTER DATABASE "{old_name}" RENAME TO "{new_name}";')

    def create(self, dbname: str) -> None:
        if self._container_name:
            self._ssh.exec(f'docker exec {self._container_name} createdb -U {self._pg_user} {dbname}')
        else:
            self._ssh.exec(f'createdb -U {self._pg_user} {dbname}')

    def drop(self, dbname: str) -> None:
        if self._container_name:
            self._ssh.exec(f'docker exec {self._container_name} dropdb -U {self._pg_user} --if-exists {dbname}')
        else:
            self._ssh.exec(f'dropdb -U {self._pg_user} --if-exists {dbname}')

    def restore(self, db_name: str, dump_path: str) -> None:
        """
        dump_path is a path on the remote host filesystem.
        """
        if self._container_name:
            # 1. Copy dump from host to container
            container_dump = f"/tmp/{os.path.basename(dump_path)}"
            self._ssh.exec(f'docker cp {dump_path} {self._container_name}:{container_dump}')

            # 2. Restore using the file inside the container
            # We use --no-owner and -j 4 for speed. 
            # Note: pg_restore warnings (exit 1) are treated as success.
            cmd = f'docker exec {self._container_name} pg_restore -U {self._pg_user} -d {db_name} --no-owner -j 4 {container_dump}'
            try:
                self._ssh.exec(cmd)
            except RuntimeError as e:
                if "exit 1" in str(e):
                    pass
                else:
                    raise e
            finally:
                # 3. Cleanup
                self._ssh.exec(f'docker exec {self._container_name} rm {container_dump}')
        else:
            # Native restoration on the remote host
            cmd = f'pg_restore -U {self._pg_user} -d {db_name} --no-owner -j 4 {dump_path}'
            try:
                self._ssh.exec(cmd)
            except RuntimeError as e:
                if "exit 1" in str(e):
                    pass
                else:
                    raise e

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
