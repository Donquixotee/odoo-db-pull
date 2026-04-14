import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .target_db import TargetDb, LocalDbTarget, RemoteDbTarget, list_local_docker_pg_containers
from .pipeline import PullPipeline
from .filestore_pipeline import FilestorePipeline
from .ssh_config import SshHostEntry, get_host_entry, load_ssh_hosts
from .ssh_utils import SshClient

BASE_DIR = Path(__file__).parent

app = FastAPI(title="Odoo DB Pull")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

DEFAULT_LOCAL_FILESTORE = os.getenv(
    "LOCAL_FILESTORE_PATH",
    str(Path.home() / ".local" / "share" / "Odoo" / "filestore"),
)
DEFAULT_PG_USER = os.getenv("PGUSER") or os.getenv("USER") or "postgres"


# ── Models ────────────────────────────────────────────────────────────────────

class ConnectRequest(BaseModel):
    alias: Optional[str] = None
    host: Optional[str] = None
    user: Optional[str] = None
    port: int = 22
    password: Optional[str] = None


class DiscoverRequest(ConnectRequest):
    pass


class ListDbsRequest(ConnectRequest):
    db_container: str
    remote_db_user: str = "odoo"


class PullRequest(ConnectRequest):
    db_container: str
    source_db: str
    target_db_name: str

    # "local", "same_server", "remote"
    target_mode: str = "local"

    rename_existing_to: Optional[str] = None

    target_pg_container: Optional[str] = None
    target_pg_user: Optional[str] = None
    target_pg_password: Optional[str] = None
    target_pg_host: str = "localhost"
    target_pg_port: int = 5432

    remote_db_user: str = "odoo"

    # For remote-to-remote (where target_mode == 'remote')
    target_ssh_alias: Optional[str] = None
    target_ssh_host: Optional[str] = None
    target_ssh_user: Optional[str] = None
    target_ssh_port: int = 22
    target_ssh_password: Optional[str] = None


class FilestoreDeployRequest(BaseModel):
    """
    Deploy filestore — mirrors the DB pull target mode.

    Source server credentials are the SAME as the DB pull (form.alias/host/user/password).
    Target credentials are derived from the chosen target_mode:
      - 'local'       : deploy to local path or local docker container
      - 'same_server' : deploy on the source server itself (same SSH creds)
      - 'remote'      : deploy on the separate target server (target_ssh_* creds)

    The user runs on source server:
        tar czf /tmp/mydb_filestore.tar.gz -C /var/lib/odoo/filestore mydb
    """
    # ── Source SSH (same as DB pull — where the tar lives) ────────────────
    source_alias: Optional[str] = None
    source_host: Optional[str] = None
    source_user: Optional[str] = None
    source_port: int = 22
    source_password: Optional[str] = None

    # Path on the SOURCE server where the tar.gz was created
    tar_remote_path: str

    # Folder name inside the filestore (= target DB name)
    db_name: str

    # ── Target mode: mirrors DB pull ───────────────────────────────────
    # 'local' | 'same_server' | 'remote'
    target_mode: str = "local"

    # ── local mode ───────────────────────────────────────────────────
    target_local_path: Optional[str] = None         # local filesystem path
    target_docker_container: Optional[str] = None   # local docker container
    target_docker_internal_path: str = "/var/lib/odoo/filestore"

    # ── same_server & remote mode ────────────────────────────────────
    # Base filestore directory on the server (e.g. /var/lib/odoo/filestore)
    target_server_path: Optional[str] = None
    # Sudo password on the target server (needed to write to /var/lib/odoo/)
    target_sudo_password: Optional[str] = None
    # Odoo system user for chown
    odoo_user: str = "odoo"

    # ── remote mode only: target server SSH ───────────────────────────
    # (same fields as the DB pull form’s target_ssh_*)
    target_ssh_alias: Optional[str] = None
    target_ssh_host: Optional[str] = None
    target_ssh_user: Optional[str] = None
    target_ssh_port: int = 22
    target_ssh_password: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_ssh_client(req: ConnectRequest) -> SshClient:
    if req.alias:
        entry = get_host_entry(req.alias)
        if not entry:
            raise ValueError(f"SSH alias '{req.alias}' not found in ~/.ssh/config")
    else:
        entry = SshHostEntry(
            alias=req.host or "",
            hostname=req.host or "",
            user=req.user or "root",
            port=req.port,
        )
    return SshClient(entry, password=req.password)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "local_filestore_base": DEFAULT_LOCAL_FILESTORE,
        "default_pg_user": DEFAULT_PG_USER,
    })


@app.get("/api/ssh-hosts")
async def ssh_hosts():
    return [
        {"alias": h.alias, "hostname": h.hostname, "user": h.user}
        for h in load_ssh_hosts()
    ]


@app.get("/api/local-docker-containers")
async def local_docker_containers():
    try:
        return list_local_docker_pg_containers()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/local-dbs")
async def local_dbs(container: Optional[str] = None):
    try:
        return LocalDbTarget(docker_container=container or None).list_databases()
    except Exception:
        return []  # non-critical: used only for rename suggestions in UI


@app.post("/api/discover")
async def discover(req: DiscoverRequest):
    try:
        ssh = _build_ssh_client(req)
        ssh.connect()
        try:
            return ssh.detect_odoo_pairs()
        finally:
            ssh.disconnect()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/list-dbs")
async def list_dbs(req: ListDbsRequest):
    try:
        ssh = _build_ssh_client(req)
        ssh.connect()
        try:
            return ssh.list_databases(req.db_container, db_user=req.remote_db_user)
        finally:
            ssh.disconnect()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/pull")
async def pull(req: PullRequest):
    async def event_stream():
        try:
            source_ssh = _build_ssh_client(req)

            if req.target_mode == "local":
                db_target = LocalDbTarget(
                    pg_user=req.target_pg_user or DEFAULT_PG_USER,
                    pg_password=req.target_pg_password,
                    pg_host=req.target_pg_host,
                    pg_port=req.target_pg_port,
                    docker_container=req.target_pg_container,
                )
                target_ssh = None
            elif req.target_mode == "same_server":
                db_target = RemoteDbTarget(
                    ssh=source_ssh,
                    pg_user=req.target_pg_user or DEFAULT_PG_USER,
                    docker_container=req.target_pg_container,
                )
                target_ssh = source_ssh
            elif req.target_mode == "remote":
                target_req = ConnectRequest(
                    alias=req.target_ssh_alias,
                    host=req.target_ssh_host,
                    user=req.target_ssh_user,
                    port=req.target_ssh_port,
                    password=req.target_ssh_password,
                )
                target_ssh = _build_ssh_client(target_req)
                db_target = RemoteDbTarget(
                    ssh=target_ssh,
                    pg_user=req.target_pg_user or DEFAULT_PG_USER,
                    docker_container=req.target_pg_container,
                )
            else:
                raise ValueError("Invalid target mode")

            pipeline = PullPipeline(source_ssh, db_target, target_ssh)
            async for event in pipeline.run(
                db_container=req.db_container,
                source_db=req.source_db,
                target_mode=req.target_mode,
                target_db_name=req.target_db_name,
                rename_existing_to=req.rename_existing_to,
                db_user=req.remote_db_user,
            ):
                yield event
        except Exception as e:
            yield f"data: error|Unexpected error: {e}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/filestore/deploy")
async def filestore_deploy(req: FilestoreDeployRequest):
    """
    Deploy filestore — mirrors the DB pull target mode.
    Source SSH = the DB pull source. Target = same as DB pull target.
    """
    async def event_stream():
        try:
            # ── Source SSH ─────────────────────────────────────────────────
            source_ssh = _build_ssh_client(ConnectRequest(
                alias=req.source_alias,
                host=req.source_host,
                user=req.source_user,
                port=req.source_port,
                password=req.source_password,
            ))

            # ── Target SSH (only for 'remote' mode) ─────────────────────────
            target_ssh = None
            if req.target_mode == "remote":
                target_ssh = _build_ssh_client(ConnectRequest(
                    alias=req.target_ssh_alias,
                    host=req.target_ssh_host,
                    user=req.target_ssh_user,
                    port=req.target_ssh_port,
                    password=req.target_ssh_password,
                ))

            pipeline = FilestorePipeline(source_ssh=source_ssh, target_ssh=target_ssh)
            async for event in pipeline.run(
                tar_remote_path=req.tar_remote_path,
                db_name=req.db_name,
                target_mode=req.target_mode,
                # local
                target_local_path=req.target_local_path,
                target_docker_container=req.target_docker_container,
                target_docker_internal_path=req.target_docker_internal_path,
                # same_server / remote
                target_server_path=req.target_server_path,
                target_sudo_password=req.target_sudo_password,
                odoo_user=req.odoo_user,
            ):
                yield event
        except Exception as e:
            yield f"data: error|Unexpected filestore error: {e}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")