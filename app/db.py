from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)


def get_db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    alembic_ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini_path))
    alembic_cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    has_existing_app_tables = bool({"billing_records", "fetch_logs"} & existing_tables)
    has_alembic_version = "alembic_version" in existing_tables

    if has_existing_app_tables and not has_alembic_version:
        command.stamp(alembic_cfg, "head")

    command.upgrade(alembic_cfg, "head")
