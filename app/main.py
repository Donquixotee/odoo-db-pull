from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import BASE_DIR
from app.tools.odoo_db_pull import router as odoo_db_pull_router


app = FastAPI(title="Personal Admin Tools")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(odoo_db_pull_router)
