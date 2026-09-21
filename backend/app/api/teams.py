"""Team profile and the full state resync (spec section 28: GET /me/state)."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_team, load_event, run_team_action
from app.core.timeutil import utcnow
from app.database import get_db
from app.models import Team
from app.schemas.schemas import PhotoHintIn
from app.services import hint_service, power_service, state_service

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


@router.post("/me/photo-hint")
def photo_hint(payload: PhotoHintIn, team: Team = Depends(get_current_team), db: Session = Depends(get_db)):
    """Standing at the checkpoint but can't find the QR: reveal its photo
    (limited per team, never on the last few checkpoints)."""
    return run_team_action(
        db, team, payload.idempotency_key, "photo_hint",
        lambda event, now: hint_service.request(db, event, team, payload.lat, payload.lng, payload.accuracy, now),
    )


@router.get("/me/photo-hint/image")
def photo_hint_image(thumb: bool = False, team: Team = Depends(get_current_team), db: Session = Depends(get_db)):
    """The revealed photo of the current target only."""
    db.refresh(team)
    body, kind = hint_service.image(db, team, thumb)
    return Response(content=body, media_type=kind, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
