from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.core.config import DEFAULT_PG_USER
from app.core.templates import templates
from app.core.tool_registry import TOOLS

from .schemas import MaintenanceRequest, PostgresTarget
from .service import PostgresMaintenanceService, list_docker_containers
from .storage import add_history, list_history

router = APIRouter()


def _template_context() -> dict:
    return {
        "tools": TOOLS,
        "active_tool": "postgres_maintenance",
        "default_pg_user": DEFAULT_PG_USER,
    }


@router.get("/tools/postgres-maintenance", response_class=HTMLResponse)
async def postgres_maintenance(request: Request):
    return templates.TemplateResponse(
        request,
        "postgres_maintenance/index.html",
        _template_context(),
    )


@router.get("/api/postgres-maintenance/history")
async def history():
    return list_history()


@router.get("/api/postgres-maintenance/docker-containers")
async def docker_containers():
    try:
        return list_docker_containers()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/api/postgres-maintenance/databases")
async def databases(req: PostgresTarget):
    try:
        return PostgresMaintenanceService(req).list_databases()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/postgres-maintenance/run")
async def run(req: MaintenanceRequest):
    service = PostgresMaintenanceService(req)
    results = []
    errors = []
    for database in req.databases:
        try:
            result = service.run_operation(database, req.operation)
            history_item = add_history({
                "mode": req.mode,
                "docker_container": req.docker_container,
                "pg_host": req.pg_host if req.mode == "native" else None,
                "pg_port": req.pg_port if req.mode == "native" else None,
                "pg_user": req.pg_user,
                "database": database,
                "operation": req.operation,
                "status": "success",
                "stdout": result["stdout"],
                "stderr": result["stderr"],
                "size_before_bytes": result["size_before_bytes"],
                "size_before_pretty": result["size_before_pretty"],
                "size_after_bytes": result["size_after_bytes"],
                "size_after_pretty": result["size_after_pretty"],
                "size_delta_bytes": result["size_delta_bytes"],
            })
            results.append({"database": database, "status": "success", **result, "history_id": history_item["id"]})
        except Exception as e:
            message = str(e)
            add_history({
                "mode": req.mode,
                "docker_container": req.docker_container,
                "pg_host": req.pg_host if req.mode == "native" else None,
                "pg_port": req.pg_port if req.mode == "native" else None,
                "pg_user": req.pg_user,
                "database": database,
                "operation": req.operation,
                "status": "error",
                "stdout": "",
                "stderr": message,
            })
            errors.append({"database": database, "error": message})

    if errors and not results:
        raise HTTPException(status_code=400, detail=errors[0]["error"])
    return {"results": results, "errors": errors}


@router.get("/api/postgres-maintenance/tools")
async def tools():
    return [asdict(tool) for tool in TOOLS]
