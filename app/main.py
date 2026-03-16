from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import router
from app.logging import configure_logging


configure_logging()
app = FastAPI(title="home-utility-api")
app.include_router(router)
