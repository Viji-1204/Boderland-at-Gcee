"""Background loop: turns expired attack windows into freezes.

State is in the database, not in memory, so a restart loses nothing: an
attack that expired while the server was down is resolved on the next tick
(spec section 18, restart-safe timers).
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.core.timeutil import utcnow
from app.database import SessionLocal
from app.models import Event, EventStatus
from app.services import power_service

logger = logging.getLogger("round2.sweeper")


def sweep_once() -> int:
    with SessionLocal() as db:
        total = 0
        for event in db.scalars(select(Event).where(Event.status == EventStatus.LIVE)).all():
            total += power_service.expire_due_attacks(db, event, utcnow())
        db.commit()
        return total


async def sweeper_loop(stop: asyncio.Event, interval: float = 1.0) -> None:
    while not stop.is_set():
        try:
            await run_in_threadpool(sweep_once)
        except Exception:  # noqa: BLE001 - keep sweeping whatever happens
            logger.exception("Sweeper tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
