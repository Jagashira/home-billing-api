from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import router
from app.api.timetree_routes import router as timetree_router
from app.logging import configure_logging


configure_logging()
app = FastAPI(title="home-utility-api")
app.include_router(router)
app.include_router(timetree_router)
