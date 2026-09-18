"""Apply Alembic migrations programmatically (used at startup and by app.seed)."""
from __future__ import annotations

import logging

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.config import BACKEND_DIR
from app.database import engine

logger = logging.getLogger("round2.migrate")


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def run_migrations() -> None:
    cfg = alembic_config()
    tables = set(inspect(engine).get_table_names())
    if tables and "alembic_version" not in tables and "events" in tables:
        # A database created by create_all() (e.g. an early dev copy): record
        # it as current instead of trying to create tables that exist.
        logger.warning("Database has tables but no migration history - stamping it at head.")
        command.stamp(cfg, "head")
        return
    command.upgrade(cfg, "head")
