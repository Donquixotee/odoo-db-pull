import csv
import os
import re
import subprocess
from io import StringIO
from typing import cast

from app.tools.odoo_db_pull.target_db import list_local_docker_pg_containers

from .schemas import PostgresConnection, PostgresTarget

_DB_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def list_docker_containers() -> list[dict]:
    return list_local_docker_pg_containers()


class OdooCronDebuggerService:
    def __init__(self, target: PostgresConnection):
        self.target = target

    def list_databases(self) -> list[dict]:
        sql = (
            "SELECT datname, pg_database_size(datname), "
            "pg_size_pretty(pg_database_size(datname)) "
            "FROM pg_database WHERE datistemplate = false ORDER BY datname;"
        )
        rows = self._psql_query(sql, [], "postgres")
        return [
            {
                "name": row[0],
                "size_bytes": int(row[1] or 0),
                "size_pretty": row[2],
            }
            for row in rows
        ]

    def get_stuck_crons(self) -> list[dict]:
        """Get idle-in-transaction sessions with cron queries."""
        target = self._database_target()
        sql = """
        SELECT
            pid,
            COALESCE(application_name, ''),
            EXTRACT(EPOCH FROM (now() - xact_start))::INTEGER as tx_duration_sec,
            EXTRACT(EPOCH FROM (now() - query_start))::INTEGER as query_duration_sec,
            state,
            COALESCE(SUBSTRING(query, 1, 240), '') as query_preview
        FROM pg_stat_activity
        WHERE datname = %s
            AND state = 'idle in transaction'
            AND query ILIKE '%WITH last_cron_progress%'
        ORDER BY xact_start ASC;
        """
        rows = self._psql_query(sql, [target.database], target.database)
        return [
            {
                "pid": int(row[0]),
                "application_name": row[1],
                "tx_duration_sec": int(row[2] or 0),
                "query_duration_sec": int(row[3] or 0),
                "state": row[4],
                "query_preview": row[5],
            }
            for row in rows
        ]

    def get_all_active_sessions(self) -> list[dict]:
        """Get all active sessions for the database."""
        target = self._database_target()
        sql = """
        SELECT
            pid,
            COALESCE(application_name, ''),
            EXTRACT(EPOCH FROM (now() - xact_start))::INTEGER as tx_duration_sec,
            EXTRACT(EPOCH FROM (now() - query_start))::INTEGER as query_duration_sec,
            state,
            COALESCE(SUBSTRING(query, 1, 240), '') as query_preview
        FROM pg_stat_activity
        WHERE datname = %s
        ORDER BY xact_start ASC;
        """
        rows = self._psql_query(sql, [target.database], target.database)
        return [
            {
                "pid": int(row[0]),
                "application_name": row[1],
                "tx_duration_sec": int(row[2] or 0),
                "query_duration_sec": int(row[3] or 0),
                "state": row[4],
                "query_preview": row[5],
            }
            for row in rows
        ]

    def get_recent_crons(self, limit: int = 20) -> list[dict]:
        """Get recent Odoo crons (requires shell access or API connection)."""
        target = self._database_target()
        cron_columns = self._table_columns("ir_cron", target.database)

        if "cron_name" in cron_columns and "ir_actions_server_id" in cron_columns:
            sql = """
            SELECT
                c.id,
                COALESCE(c.cron_name, a.name->>'en_US', a.name::text, '') as name,
                COALESCE(a.model_id::text, '') as model_id,
                COALESCE(c.lastcall::text, 'never') as lastcall,
                COALESCE(c.nextcall::text, '') as nextcall,
                c.active,
                COALESCE(SUBSTRING(a.code, 1, 180), '') as code_preview
            FROM ir_cron c
            LEFT JOIN ir_act_server a ON a.id = c.ir_actions_server_id
            ORDER BY c.lastcall DESC NULLS LAST
            LIMIT %s;
            """
        else:
            sql = """
            SELECT
                id,
                COALESCE(name::text, '') as name,
                COALESCE(model_id::text, '') as model_id,
                COALESCE(lastcall::text, 'never') as lastcall,
                COALESCE(nextcall::text, '') as nextcall,
                active,
                COALESCE(SUBSTRING(code, 1, 180), '') as code_preview
            FROM ir_cron
            ORDER BY lastcall DESC NULLS LAST
            LIMIT %s;
            """

        rows = self._psql_query(sql, [limit], target.database)
        return [
            {
                "id": int(row[0]),
                "name": row[1],
                "model_id": row[2],
                "lastcall": row[3],
                "nextcall": row[4],
                "active": row[5] == 't' or row[5] is True,
                "code_preview": row[6],
            }
            for row in rows
        ]

    def _table_columns(self, table_name: str, database: str) -> set[str]:
        rows = self._psql_query(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = %s;
            """,
            [table_name],
            database,
        )
        return {row[0] for row in rows}

    def kill_backend(self, pid: int) -> dict:
        """Kill a PostgreSQL backend by PID."""
        target = self._database_target()
        if pid <= 0:
            raise ValueError("PID must be positive")
        result = self._psql_query("SELECT pg_terminate_backend(%s);", [pid], target.database)
        if result and result[0] and result[0][0] in {"t", "true", "True"}:
            return {"success": True, "message": f"Backend {pid} terminated"}
        return {"success": False, "message": f"Failed to terminate backend {pid}"}

    def _psql_query(self, sql: str, params: list, database: str) -> list[list[str]]:
        """Execute psql query and return CSV results."""
        self._validate_db_name(database)
        cmd = ["psql", "-U", self.target.pg_user]
        if self.target.mode == "native":
            cmd.extend(["-h", self.target.pg_host, "-p", str(self.target.pg_port)])
        cmd.extend(["-d", database, "--csv", "-t", "-c"])

        formatted_sql = sql
        for param in params:
            formatted_sql = formatted_sql.replace("%s", self._sql_literal(param), 1)

        cmd.append(formatted_sql)

        output = self._run(cmd)["stdout"]
        return [row for row in csv.reader(StringIO(output)) if row]

    def _run(self, cmd: list[str]) -> dict:
        """Run shell command with postgres password support."""
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
            raise RuntimeError(
                result["stderr"].strip() or result["stdout"].strip() or "Command failed"
            )
        return result

    def _docker_exec(self, cmd: list[str], env: dict[str, str]) -> dict:
        """Execute command inside Docker container."""
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

    def _database_target(self) -> PostgresTarget:
        database = getattr(self.target, "database", "")
        if not database:
            raise ValueError("Database is required")
        self._validate_db_name(database)
        return cast(PostgresTarget, self.target)

    def _validate_db_name(self, database: str) -> None:
        if not _DB_NAME_RE.match(database):
            raise ValueError("Database name contains unsupported characters")

    def _sql_literal(self, value) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if value is None:
            return "NULL"
        return "'" + str(value).replace("'", "''") + "'"
