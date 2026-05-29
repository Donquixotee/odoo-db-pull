from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.core.config import DEFAULT_PG_USER
from app.core.templates import templates
from app.core.tool_registry import TOOLS

from .schemas import CronRequest, PostgresConnection, PostgresTarget
from .service import OdooCronDebuggerService, list_docker_containers

router = APIRouter()


def _template_context() -> dict:
    return {
        "tools": TOOLS,
        "active_tool": "odoo_cron_debugger",
        "default_pg_user": DEFAULT_PG_USER,
    }


@router.get("/tools/odoo-cron-debugger", response_class=HTMLResponse)
async def odoo_cron_debugger(request: Request):
    return templates.TemplateResponse(
        request,
        "odoo_cron_debugger/index.html",
        _template_context(),
    )


@router.get("/api/odoo-cron-debugger/docker-containers")
async def docker_containers():
    try:
        return list_docker_containers()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/api/odoo-cron-debugger/databases")
async def databases(req: PostgresConnection):
    try:
        service = OdooCronDebuggerService(req)
        return service.list_databases()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/odoo-cron-debugger/stuck-crons")
async def stuck_crons(req: PostgresTarget):
    try:
        service = OdooCronDebuggerService(req)
        return service.get_stuck_crons()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/odoo-cron-debugger/active-sessions")
async def active_sessions(req: PostgresTarget):
    try:
        service = OdooCronDebuggerService(req)
        return service.get_all_active_sessions()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/odoo-cron-debugger/recent-crons")
async def recent_crons(req: PostgresTarget):
    try:
        service = OdooCronDebuggerService(req)
        return service.get_recent_crons()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/odoo-cron-debugger/kill-backend")
async def kill_backend(req: CronRequest):
    """Kill a backend by PID."""
    if req.pid is None:
        raise HTTPException(status_code=400, detail="PID is required")

    try:
        service = OdooCronDebuggerService(req)
        return service.kill_backend(req.pid)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/odoo-cron-debugger/tools")
async def tools():
    return [asdict(tool) for tool in TOOLS]
