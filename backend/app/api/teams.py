"""Team profile and the full state resync (spec section 28: GET /me/state)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_team, load_event
from app.core.timeutil import utcnow
from app.database import get_db
from app.models import Team
from app.services import power_service, state_service

router = APIRouter(tags=["team"])


@router.get("/teams/me")
def me(team: Team = Depends(get_current_team)):
    return {
        "team_id": team.id,
        "team_code": team.team_code,
        "team_name": team.team_name,
        "leader_name": team.leader_name,
        "event_id": team.event_id,
    }


@router.get("/me/state")
def my_state(team: Team = Depends(get_current_team), db: Session = Depends(get_db)):
    """Everything this team may see. Clients call it on load and after every
    WebSocket (re)connect, and never trust cached UI over it."""
    event = load_event(db, team.event_id)
    power_service.expire_due_attacks(db, event, utcnow())
    db.refresh(team)
    db.refresh(event)
    return state_service.team_state(db, event, team, utcnow())
