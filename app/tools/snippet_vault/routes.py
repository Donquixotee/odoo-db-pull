from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse

from app.core.templates import templates
from app.core.tool_registry import TOOLS

from .schemas import SnippetCreate, SnippetUpdate
from .storage import add_note, delete_note, list_notes, update_note

router = APIRouter()


def _template_context() -> dict:
    return {
        "tools": TOOLS,
        "active_tool": "snippet_vault",
    }


@router.get("/tools/snippet-vault", response_class=HTMLResponse)
async def snippet_vault(request: Request):
    return templates.TemplateResponse(
        request,
        "snippet_vault/index.html",
        _template_context(),
    )


@router.get("/api/snippet-vault")
async def snippet_vault_data():
    data = list_notes()
    return {
        **data,
        "tools": [asdict(tool) for tool in TOOLS],
    }


@router.post("/api/snippet-vault/notes")
async def create_note(req: SnippetCreate):
    return add_note(jsonable_encoder(req))


@router.patch("/api/snippet-vault/notes/{note_id}")
async def patch_note(note_id: str, req: SnippetUpdate):
    note = update_note(note_id, jsonable_encoder(req, exclude_unset=True))
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.delete("/api/snippet-vault/notes/{note_id}")
async def remove_note(note_id: str):
    if not delete_note(note_id):
        raise HTTPException(status_code=404, detail="Note not found")
    return {"ok": True}
