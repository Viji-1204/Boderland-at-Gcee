from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_team, load_event
from app.core.timeutil import utcnow
from app.database import get_db
from app.models import Team
from app.services import power_service, scan_service

router = APIRouter(tags=["team"])


@router.get("/radar")
def radar(
    lat: float | None = Query(default=None, ge=-90, le=90),
    lng: float | None = Query(default=None, ge=-180, le=180),
    accuracy: float | None = Query(default=None, ge=0, le=100000),
    team: Team = Depends(get_current_team),
    db: Session = Depends(get_db),
):
    """Distance and bearing to the current target only (spec section 13)."""
    event = load_event(db, team.event_id)
    power_service.expire_due_attacks(db, event, utcnow())
    db.refresh(team)
    return scan_service.radar(db, event, team, utcnow(), lat, lng, accuracy)
