from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from app.core.config import DEFAULT_LOCAL_FILESTORE, DEFAULT_PG_USER
from app.core.templates import templates
from app.core.tool_registry import TOOLS

from .filestore_pipeline import FilestorePipeline
from .pipeline import PullPipeline
from .schemas import (
    ConnectRequest,
    DiscoverRequest,
    FilestoreDeployRequest,
    ListDbsRequest,
    PullRequest,
)
from .ssh_config import SshHostEntry, get_host_entry, load_ssh_hosts
from .ssh_utils import SshClient
from .target_db import LocalDbTarget, RemoteDbTarget, list_local_docker_pg_containers

router = APIRouter()


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


def _template_context(request: Request) -> dict:
    return {
        "local_filestore_base": DEFAULT_LOCAL_FILESTORE,
        "default_pg_user": DEFAULT_PG_USER,
        "tools": TOOLS,
        "active_tool": "odoo_db_pull",
    }


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", _template_context(request))


@router.get("/tools/odoo-db-pull", response_class=HTMLResponse)
async def odoo_db_pull(request: Request):
    return templates.TemplateResponse(request, "index.html", _template_context(request))


@router.get("/api/tools")
async def tools():
    return [asdict(tool) for tool in TOOLS]


@router.get("/api/ssh-hosts")
async def ssh_hosts():
    return [
        {"alias": h.alias, "hostname": h.hostname, "user": h.user}
        for h in load_ssh_hosts()
    ]


@router.get("/api/local-docker-containers")
async def local_docker_containers():
    try:
        return list_local_docker_pg_containers()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/api/local-dbs")
async def local_dbs(container: Optional[str] = None):
    try:
        return LocalDbTarget(docker_container=container or None).list_databases()
    except Exception:
        return []  # non-critical: used only for rename suggestions in UI


@router.post("/api/discover")
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


@router.post("/api/list-dbs")
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


@router.post("/api/pull")
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


@router.post("/api/filestore/deploy")
async def filestore_deploy(req: FilestoreDeployRequest):
    """
    Deploy filestore — mirrors the DB pull target mode.
    Source SSH = the DB pull source. Target = same as DB pull target.
    """
    async def event_stream():
        try:
            source_ssh = _build_ssh_client(ConnectRequest(
                alias=req.source_alias,
                host=req.source_host,
                user=req.source_user,
                port=req.source_port,
                password=req.source_password,
            ))

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
                target_local_path=req.target_local_path,
                target_docker_container=req.target_docker_container,
                target_docker_internal_path=req.target_docker_internal_path,
                target_server_path=req.target_server_path,
                target_sudo_password=req.target_sudo_password,
                odoo_user=req.odoo_user,
            ):
                yield event
        except Exception as e:
            yield f"data: error|Unexpected filestore error: {e}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
