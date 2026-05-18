import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import BASE_DIR

DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "postgres_maintenance.json"

_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "history": []}


def _read_unlocked() -> dict[str, Any]:
    if not DATA_FILE.exists():
        return _empty_store()
    with DATA_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if "history" not in data or not isinstance(data["history"], list):
        data["history"] = []
    return data


def _write_unlocked(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = DATA_FILE.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, DATA_FILE)


def list_history(limit: int = 30) -> list[dict[str, Any]]:
    with _LOCK:
        data = _read_unlocked()
    history = sorted(data["history"], key=lambda item: item.get("created_at", ""), reverse=True)
    return history[:limit]


def add_history(payload: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        data = _read_unlocked()
        item = {
            "id": uuid.uuid4().hex,
            "created_at": _now_iso(),
            **payload,
        }
        data["history"].append(item)
        _write_unlocked(data)
        return item
