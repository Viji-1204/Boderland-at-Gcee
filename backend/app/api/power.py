from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_team, load_event, load_team, run_team_action
from app.database import get_db
from app.models import PowerUsage, Team, TeamStatus
from app.schemas.schemas import ActionIn, AttackIn, DefendIn, PurchaseIn
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
        return power_service.attack(db, event, team, target, payload.kind, now)

    return run_team_action(db, team, payload.idempotency_key, "attack", act, extra_lock_ids=(target.id,))


@router.post("/defend")
def defend(payload: DefendIn, team: Team = Depends(get_current_team), db: Session = Depends(get_db)):
    """Answer an incoming attack: Shield it, Reflect it, or accept it (defence = null)."""
    attacker_id = None
    if payload.defence == "REFLECT":  # the bounce changes the attacker too, so lock them as well
        usage = db.get(PowerUsage, payload.usage_id)
        attacker_id = usage.team_id if usage is not None and usage.target_team_id == team.id else None
    return run_team_action(
        db, team, payload.idempotency_key, "defend",
        lambda event, now: power_service.respond(db, event, team, payload.usage_id, payload.defence, now),
        extra_lock_ids=(attacker_id,) if attacker_id else (),
    )


@router.post("/guide")
def guide(payload: ActionIn, team: Team = Depends(get_current_team), db: Session = Depends(get_db)):
    """Reveal the current target on the radar (name, exact distance, Google Maps route) for a while."""
    return run_team_action(
        db, team, payload.idempotency_key, "guide",
        lambda event, now: power_service.guide(db, event, team, now),
    )


@router.post("/ward")
def ward(payload: ActionIn, team: Team = Depends(get_current_team), db: Session = Depends(get_db)):
    """Raise a Ward: every attack is blocked automatically while it lasts."""
    return run_team_action(
        db, team, payload.idempotency_key, "ward",
        lambda event, now: power_service.ward(db, event, team, now),
    )
