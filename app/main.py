from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import BASE_DIR
from app.tools.odoo_db_pull import router as odoo_db_pull_router
from app.tools.postgres_maintenance import router as postgres_maintenance_router
from app.tools.snippet_vault import router as snippet_vault_router
from app.tools.time_tracker import router as time_tracker_router


app = FastAPI(title="Personal Admin Tools")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(odoo_db_pull_router)
app.include_router(time_tracker_router)
app.include_router(snippet_vault_router)
app.include_router(postgres_maintenance_router)
