import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import BASE_DIR

DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "time_tracker.json"

_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_store() -> dict[str, Any]:
    return {
        "version": 1,
        "currency": "EUR",
        "secondary_currency": "DZD",
        "default_hourly_rate": 7.5,
        "eur_to_dzd_rate": 250,
        "entries": [],
    }


def _read_unlocked() -> dict[str, Any]:
    if not DATA_FILE.exists():
        return _empty_store()
    with DATA_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if "entries" not in data or not isinstance(data["entries"], list):
        data["entries"] = []
    defaults = _empty_store()
    for key, value in defaults.items():
        data.setdefault(key, value)
    return data


def _write_unlocked(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = DATA_FILE.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, DATA_FILE)


def list_entries() -> dict[str, Any]:
    with _LOCK:
        data = _read_unlocked()
    data["entries"] = sorted(
        data["entries"],
        key=lambda entry: (entry.get("work_date", ""), entry.get("created_at", "")),
        reverse=True,
    )
    return data


def add_entry(payload: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        data = _read_unlocked()
        entry = {
            "id": uuid.uuid4().hex,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            **payload,
        }
        data["entries"].append(entry)
        _write_unlocked(data)
        return entry


def update_entry(entry_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    with _LOCK:
        data = _read_unlocked()
        for entry in data["entries"]:
            if entry.get("id") == entry_id:
                for key, value in payload.items():
                    if value is not None:
                        entry[key] = value
                entry["updated_at"] = _now_iso()
                _write_unlocked(data)
                return entry
    return None


def delete_entry(entry_id: str) -> bool:
    with _LOCK:
        data = _read_unlocked()
        before = len(data["entries"])
        data["entries"] = [entry for entry in data["entries"] if entry.get("id") != entry_id]
        if len(data["entries"]) == before:
            return False
        _write_unlocked(data)
        return True


def update_settings(payload: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        data = _read_unlocked()
        data["eur_to_dzd_rate"] = float(payload["eur_to_dzd_rate"])
        _write_unlocked(data)
        return {
            "currency": data["currency"],
            "secondary_currency": data["secondary_currency"],
            "default_hourly_rate": data["default_hourly_rate"],
            "eur_to_dzd_rate": data["eur_to_dzd_rate"],
        }


def summarize(entries: list[dict[str, Any]], eur_to_dzd_rate: float = 0) -> dict[str, Any]:
    total_hours = sum(float(entry.get("hours") or 0) for entry in entries)
    total_amount = sum(
        float(entry.get("hours") or 0) * float(entry.get("hourly_rate") or 0)
        for entry in entries
    )
    unpaid_amount = sum(
        float(entry.get("hours") or 0) * float(entry.get("hourly_rate") or 0)
        for entry in entries
        if not entry.get("paid")
    )
    return {
        "total_hours": round(total_hours, 2),
        "total_amount": round(total_amount, 2),
        "unpaid_amount": round(unpaid_amount, 2),
        "total_amount_dzd": round(total_amount * eur_to_dzd_rate, 2),
        "unpaid_amount_dzd": round(unpaid_amount * eur_to_dzd_rate, 2),
        "entry_count": len(entries),
    }
