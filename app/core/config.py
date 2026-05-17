import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_LOCAL_FILESTORE = os.getenv(
    "LOCAL_FILESTORE_PATH",
    str(Path.home() / ".local" / "share" / "Odoo" / "filestore"),
)
DEFAULT_PG_USER = os.getenv("PGUSER") or os.getenv("USER") or "postgres"
