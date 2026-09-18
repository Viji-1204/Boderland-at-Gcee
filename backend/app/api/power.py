from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_team, load_event, load_team, run_team_action
from app.database import get_db
from app.models import Team, TeamStatus
from app.schemas.schemas import AttackIn, DefendIn, HelpIn, PurchaseIn
from app.services import power_service

router = APIRouter(prefix="/powers", tags=["team"])


@router.get("/targets")
def targets(team: Team = Depends(get_current_team), db: Session = Depends(get_db)):
    """Opponents for the attack picker. Only names are shown, never anyone's
    freeze or power state: the server rejects an invalid target with a clear
    message instead."""
    rows = db.scalars(
        select(Team)
        .where(Team.event_id == team.event_id, Team.id != team.id, Team.status != TeamStatus.DISQUALIFIED)
        .order_by(Team.team_name)
    )
    return [{"id": t.id, "team_name": t.team_name, "finished": t.status == TeamStatus.COMPLETED} for t in rows]


@router.post("/purchase")
def purchase(payload: PurchaseIn, team: Team = Depends(get_current_team), db: Session = Depends(get_db)):
    return run_team_action(
        db, team, payload.idempotency_key, "purchase",
        lambda event, now: power_service.purchase(db, event, team, payload.kind, payload.quantity),
    )


@router.post("/attack")
def attack(payload: AttackIn, team: Team = Depends(get_current_team), db: Session = Depends(get_db)):
    event = load_event(db, team.event_id)
    target = load_team(db, event, payload.target_team_id)

    def act(event, now):
        db.refresh(target)
        return power_service.attack(db, event, team, target, now)

    return run_team_action(db, team, payload.idempotency_key, "attack", act, extra_lock_ids=(target.id,))


@router.post("/defend")
def defend(payload: DefendIn, team: Team = Depends(get_current_team), db: Session = Depends(get_db)):
    """Answer an incoming attack: use a Defence, or accept the freeze."""
    return run_team_action(
        db, team, payload.idempotency_key, "defend",
        lambda event, now: power_service.respond(db, event, team, payload.usage_id, payload.use_defence, now),
    )


@router.post("/help")
def help_request(payload: HelpIn, team: Team = Depends(get_current_team), db: Session = Depends(get_db)):
    return run_team_action(
        db, team, payload.idempotency_key, "help",
        lambda event, now: power_service.request_help(db, event, team, payload.message, now),
    )
