import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import BASE_DIR

DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "snippet_vault.json"

_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "notes": []}


def _read_unlocked() -> dict[str, Any]:
    if not DATA_FILE.exists():
        return _empty_store()
    with DATA_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if "notes" not in data or not isinstance(data["notes"], list):
        data["notes"] = []
    return data


def _write_unlocked(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = DATA_FILE.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, DATA_FILE)


def list_notes() -> dict[str, Any]:
    with _LOCK:
        data = _read_unlocked()
    data["notes"] = sorted(
        data["notes"],
        key=lambda note: (note.get("updated_at", ""), note.get("created_at", "")),
        reverse=True,
    )
    return data


def add_note(payload: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        data = _read_unlocked()
        now = _now_iso()
        note = {
            "id": uuid.uuid4().hex,
            "created_at": now,
            "updated_at": now,
            **payload,
            "tags": _clean_tags(payload.get("tags", [])),
        }
        data["notes"].append(note)
        _write_unlocked(data)
        return note


def update_note(note_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    with _LOCK:
        data = _read_unlocked()
        for note in data["notes"]:
            if note.get("id") == note_id:
                for key, value in payload.items():
                    if value is not None:
                        note[key] = _clean_tags(value) if key == "tags" else value
                note["updated_at"] = _now_iso()
                _write_unlocked(data)
                return note
    return None


def delete_note(note_id: str) -> bool:
    with _LOCK:
        data = _read_unlocked()
        before = len(data["notes"])
        data["notes"] = [note for note in data["notes"] if note.get("id") != note_id]
        if len(data["notes"]) == before:
            return False
        _write_unlocked(data)
        return True


def _clean_tags(tags: list[str]) -> list[str]:
    cleaned = []
    seen = set()
    for tag in tags:
        value = str(tag).strip().lower()
        if value and value not in seen:
            cleaned.append(value)
            seen.add(value)
    return cleaned
