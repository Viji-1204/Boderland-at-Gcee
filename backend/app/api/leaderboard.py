import logging
import time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_team, load_event
from app.core.exceptions import ConflictError
from app.database import get_db
from app.models import EventStatus, Team
from app.services import results_service, state_service

router = APIRouter(tags=["public"])
logger = logging.getLogger("round2")


@router.get("/health")
def health():
    """Is it up? For people (open it in a browser) and Docker's healthcheck.
    Also proves the database answers, not just the web server."""
    from app import database  # looked up per call: tests swap the engine

    try:
        with database.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any failure means "not healthy"
        logger.exception("Health check: the database is not answering")
        return JSONResponse({"status": "error", "database": "unreachable"}, status_code=503)
    return {"status": "ok", "database": database.engine.dialect.name}


@router.get("/time")
def server_time():
    """Clock sync for countdowns (Round 1's api.js syncServerTime uses this)."""
    return {"server_time_ms": int(time.time() * 1000)}


@router.get("/leaderboard")
def leaderboard(team: Team = Depends(get_current_team), db: Session = Depends(get_db)):
    """Checkpoint progress only - no fouls, positions, routes or powers (spec section 17)."""
    event = load_event(db, team.event_id)
    return state_service.leaderboard(db, event, viewer_team_id=team.id)


@router.get("/results/public")
def public_results(team: Team = Depends(get_current_team), db: Session = Depends(get_db)):
    """Rank, team name and time only - never fouls (spec section 21)."""
    event = load_event(db, team.event_id)
    if event.status != EventStatus.ENDED:
        raise ConflictError("Results are published when the game ends.")
    return {"event_name": event.name, "rows": results_service.public_results(db, event)}
