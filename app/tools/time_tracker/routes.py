from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse

from app.core.templates import templates
from app.core.tool_registry import TOOLS

from .schemas import TimeEntryCreate, TimeEntryUpdate, TimeTrackerSettingsUpdate
from .storage import (
    add_entry,
    delete_entry,
    list_entries,
    summarize,
    update_entry,
    update_settings,
)

router = APIRouter()


def _template_context() -> dict:
    return {
        "tools": TOOLS,
        "active_tool": "time_tracker",
        "default_hourly_rate": 7.5,
        "default_eur_to_dzd_rate": 250,
    }


@router.get("/tools/time-tracker", response_class=HTMLResponse)
async def time_tracker(request: Request):
    return templates.TemplateResponse(
        request,
        "time_tracker/index.html",
        _template_context(),
    )


@router.get("/api/time-tracker")
async def time_tracker_data():
    data = list_entries()
    return {
        **data,
        "summary": summarize(data["entries"], float(data.get("eur_to_dzd_rate") or 0)),
        "tools": [asdict(tool) for tool in TOOLS],
    }


@router.patch("/api/time-tracker/settings")
async def patch_settings(req: TimeTrackerSettingsUpdate):
    return update_settings(jsonable_encoder(req))


@router.post("/api/time-tracker/entries")
async def create_entry(req: TimeEntryCreate):
    entry = add_entry(jsonable_encoder(req))
    return entry


@router.patch("/api/time-tracker/entries/{entry_id}")
async def patch_entry(entry_id: str, req: TimeEntryUpdate):
    entry = update_entry(entry_id, jsonable_encoder(req, exclude_unset=True))
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


@router.delete("/api/time-tracker/entries/{entry_id}")
async def remove_entry(entry_id: str):
    if not delete_entry(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"ok": True}
