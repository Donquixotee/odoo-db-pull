import csv
import os
import re
import subprocess
from io import StringIO
from typing import Optional

from app.tools.odoo_db_pull.target_db import list_local_docker_pg_containers

from .schemas import MaintenanceOperation, PostgresTarget

_DB_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def list_docker_containers() -> list[dict]:
    return list_local_docker_pg_containers()


class PostgresMaintenanceService:
    def __init__(self, target: PostgresTarget):
        self.target = target

    def list_databases(self) -> list[dict]:
        sql = (
            "SELECT datname, pg_database_size(datname), "
            "pg_size_pretty(pg_database_size(datname)) "
            "FROM pg_database WHERE datistemplate = false ORDER BY pg_database_size(datname) DESC;"
        )
        rows = self._psql_csv(sql, "postgres")
        return [
            {
                "name": row[0],
                "size_bytes": int(row[1] or 0),
                "size_pretty": row[2],
            }
            for row in rows
        ]

    def database_size(self, database: str) -> dict:
        self._validate_db_name(database)
        sql = f"SELECT pg_database_size('{database}'), pg_size_pretty(pg_database_size('{database}'));"
        rows = self._psql_csv(sql, "postgres")
        if not rows:
            return {"size_bytes": 0, "size_pretty": "0 bytes"}
        return {
            "size_bytes": int(rows[0][0] or 0),
            "size_pretty": rows[0][1],
        }

    def run_operation(self, database: str, operation: MaintenanceOperation) -> dict:
        self._validate_db_name(database)
        size_before = self.database_size(database)
        if operation == "vacuum":
            cmd = self._maintenance_cmd("vacuumdb", database)
        elif operation == "vacuum_analyze":
            cmd = self._maintenance_cmd("vacuumdb", database, extra=["--analyze"])
        elif operation == "reindex":
            cmd = self._maintenance_cmd("reindexdb", database)
        else:
            raise ValueError("Unsupported operation")

        result = self._run(cmd)
        size_after = self.database_size(database)
        return {
            "returncode": result["returncode"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "size_before_bytes": size_before["size_bytes"],
            "size_before_pretty": size_before["size_pretty"],
            "size_after_bytes": size_after["size_bytes"],
            "size_after_pretty": size_after["size_pretty"],
            "size_delta_bytes": size_after["size_bytes"] - size_before["size_bytes"],
        }

    def _psql_csv(self, sql: str, database: str) -> list[list[str]]:
        cmd = ["psql", "-U", self.target.pg_user]
        if self.target.mode == "native":
            cmd.extend(self._native_conn_args())
        cmd.extend(["-d", database, "-A", "-F", ",", "-t", "-c", sql])
        output = self._run(cmd)["stdout"]
        return [row for row in csv.reader(StringIO(output)) if row]

    def _maintenance_cmd(
        self, executable: str, database: str, extra: Optional[list[str]] = None
    ) -> list[str]:
        cmd = [executable, "-U", self.target.pg_user]
        if self.target.mode == "native":
            cmd.extend(self._native_conn_args())
        cmd.extend(extra or [])
        cmd.append(database)
        return cmd

    def _native_conn_args(self) -> list[str]:
        return ["-h", self.target.pg_host, "-p", str(self.target.pg_port)]

    def _run(self, cmd: list[str]) -> dict:
        env = os.environ.copy()
        if self.target.pg_password:
            env["PGPASSWORD"] = self.target.pg_password

        if self.target.mode == "docker":
            if not self.target.docker_container:
                raise ValueError("Docker container is required")
            result = self._docker_exec(cmd, env)
        else:
            completed = subprocess.run(cmd, capture_output=True, text=True, env=env)
            result = {
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }

        if result["returncode"] != 0:
            raise RuntimeError(result["stderr"].strip() or result["stdout"].strip() or "Command failed")
        return result

    def _docker_exec(self, cmd: list[str], env: dict[str, str]) -> dict:
        import docker

        client = docker.from_env()
        container = client.containers.get(self.target.docker_container)
        docker_env = {}
        if "PGPASSWORD" in env:
            docker_env["PGPASSWORD"] = env["PGPASSWORD"]
        result = container.exec_run(cmd, demux=True, environment=docker_env)
        stdout = (result.output[0] or b"").decode(errors="replace")
        stderr = (result.output[1] or b"").decode(errors="replace")
        return {
            "returncode": result.exit_code,
            "stdout": stdout,
            "stderr": stderr,
        }

    def _validate_db_name(self, database: str) -> None:
        if not _DB_NAME_RE.match(database):
            raise ValueError("Database name contains unsupported characters")
