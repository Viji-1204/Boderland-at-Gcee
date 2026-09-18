"""Coordinator API: events, lifecycle, live monitoring and overrides (spec section 22)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, load_event, load_team, require_super
from app.core.exceptions import ConflictError, NotFoundError
from app.core.locks import team_locks
from app.core.timeutil import iso, utcnow
from app.database import get_db
from app.models import (
    Admin,
    AdminAction,
    Event,
    EventStatus,
    GameEvent,
    Location,
    Team,
)
from app.schemas.schemas import EventCreateIn, EventUpdateIn, FoulIn, FreezeIn, ReasonIn, RestartIn
from app.services import admin_service, event_service, export_service, power_service, results_service, state_service
from app.services.event_settings import event_settings

router = APIRouter(prefix="/admin", tags=["admin"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def event_summary(db: Session, event: Event) -> dict:
    team_count = db.scalar(select(func.count(Team.id)).where(Team.event_id == event.id)) or 0
    loc_total = db.scalar(select(func.count(Location.id)).where(Location.event_id == event.id)) or 0
    loc_selected = db.scalar(
        select(func.count(Location.id)).where(Location.event_id == event.id, Location.is_selected.is_(True))
    ) or 0
    return {
        "id": event.id,
        "name": event.name,
        "status": event.status,
        "settings": event_settings(event),
        "final_location_name": event.final_location_name,
        "final_latitude": event.final_latitude,
        "final_longitude": event.final_longitude,
        "created_at": iso(event.created_at),
        "config_locked_at": iso(event.config_locked_at),
        "started_at": iso(event.started_at),
        "paused_at": iso(event.paused_at),
        "ended_at": iso(event.ended_at),
        "counts": {"teams": team_count, "locations": loc_total, "selected_locations": loc_selected},
    }


# ---------------------------------------------------------------------------
# Events & lifecycle
# ---------------------------------------------------------------------------


@router.get("/events")
def list_events(_admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    events = db.scalars(select(Event).order_by(Event.created_at.desc()))
    return [event_summary(db, e) for e in events]


@router.post("/events", status_code=status.HTTP_201_CREATED)
def create_event(payload: EventCreateIn, admin: Admin = Depends(require_super), db: Session = Depends(get_db)):
    clone = load_event(db, payload.clone_from_event_id) if payload.clone_from_event_id else None
    event = event_service.create_event(db, admin, payload.name, clone)
    db.commit()
    return event_summary(db, event)


@router.get("/events/{event_id}")
def get_event(event_id: str, _admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    return {**event_summary(db, event), "readiness": event_service.readiness(db, event)}


@router.patch("/events/{event_id}")
def update_event(event_id: str, payload: EventUpdateIn, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    event_service.update_event(db, event, admin, payload.model_dump(exclude_unset=True))
    db.commit()
    return {**event_summary(db, event), "readiness": event_service.readiness(db, event)}


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(event_id: str, _admin: Admin = Depends(require_super), db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    if event.status not in (EventStatus.DRAFT, EventStatus.ENDED):
        raise ConflictError("Only DRAFT or ENDED events can be deleted.")
    db.delete(event)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/events/{event_id}/readiness")
def readiness(event_id: str, _admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    return event_service.readiness(db, load_event(db, event_id))


def _transition(db: Session, event_id: str, admin: Admin, fn: Callable) -> dict:
    event = load_event(db, event_id)
    fn(db, event, admin)
    db.commit()
    return event_summary(db, event)


@router.post("/events/{event_id}/lock")
def lock(event_id: str, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    """DRAFT -> CONFIGURED: validates everything and freezes the setup."""
    return _transition(db, event_id, admin, event_service.lock)


@router.post("/events/{event_id}/unlock")
def unlock(event_id: str, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _transition(db, event_id, admin, event_service.unlock)


@router.post("/events/{event_id}/start")
def start(event_id: str, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _transition(db, event_id, admin, event_service.start)


@router.post("/events/{event_id}/pause")
def pause(event_id: str, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _transition(db, event_id, admin, event_service.pause)


@router.post("/events/{event_id}/resume")
def resume(event_id: str, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _transition(db, event_id, admin, event_service.resume)


@router.post("/events/{event_id}/end")
def end(event_id: str, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _transition(db, event_id, admin, event_service.end)


@router.post("/events/{event_id}/restart")
def restart(event_id: str, payload: RestartIn | None = None, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    """LIVE / PAUSED / ENDED -> CONFIGURED: discard the run, keep the setup."""
    refund = bool(payload and payload.refund_powers)
    return _transition(db, event_id, admin, lambda d, e, a: event_service.restart(d, e, a, refund))


# ---------------------------------------------------------------------------
# Live monitoring
# ---------------------------------------------------------------------------


@router.get("/events/{event_id}/dashboard")
def dashboard(event_id: str, _admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    power_service.expire_due_attacks(db, event, utcnow())
    return {"event": event_summary(db, event), **state_service.dashboard(db, event, utcnow())}


@router.get("/events/{event_id}/leaderboard")
def leaderboard(event_id: str, _admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    """What teams see on their public board."""
    return state_service.leaderboard(db, load_event(db, event_id))


# ---------------------------------------------------------------------------
# Team overrides (all logged to admin_actions)
# ---------------------------------------------------------------------------


def _team_action(db: Session, event_id: str, team_id: str, fn: Callable[[Event, Team], None]) -> dict:
    event = load_event(db, event_id)
    team = load_team(db, event, team_id)
    with team_locks(team.id):
        db.refresh(team, with_for_update=True)
        fn(event, team)
        db.commit()
    return {"ok": True, "team_id": team.id, "status": team.status, "foul_count": team.foul_count, "frozen_until": iso(team.frozen_until)}


@router.post("/events/{event_id}/teams/{team_id}/foul")
def foul(event_id: str, team_id: str, payload: FoulIn, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    def act(event, team):
        if payload.action == "add":
            admin_service.add_foul(db, event, team, admin, payload.reason, utcnow())
        else:
            admin_service.remove_foul(db, event, team, admin, payload.reason)

    return _team_action(db, event_id, team_id, act)


@router.post("/events/{event_id}/teams/{team_id}/freeze")
def freeze(event_id: str, team_id: str, payload: FreezeIn, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _team_action(db, event_id, team_id, lambda e, t: admin_service.freeze_team(db, e, t, admin, payload.duration_s, utcnow()))


@router.post("/events/{event_id}/teams/{team_id}/unfreeze")
def unfreeze(event_id: str, team_id: str, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _team_action(db, event_id, team_id, lambda e, t: admin_service.unfreeze_team(db, e, t, admin, utcnow()))


@router.post("/events/{event_id}/teams/{team_id}/unlock-puzzle")
def unlock_puzzle(event_id: str, team_id: str, payload: ReasonIn, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _team_action(db, event_id, team_id, lambda e, t: admin_service.unlock_puzzle(db, e, t, admin, payload.reason))


@router.post("/events/{event_id}/teams/{team_id}/verify-joker")
def verify_joker(event_id: str, team_id: str, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _team_action(db, event_id, team_id, lambda e, t: admin_service.verify_joker(db, e, t, admin, utcnow()))


@router.post("/events/{event_id}/teams/{team_id}/disqualify")
def disqualify(event_id: str, team_id: str, payload: ReasonIn, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _team_action(db, event_id, team_id, lambda e, t: admin_service.disqualify(db, e, t, admin, payload.reason))


@router.post("/events/{event_id}/teams/{team_id}/reinstate")
def reinstate(event_id: str, team_id: str, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _team_action(db, event_id, team_id, lambda e, t: admin_service.reinstate(db, e, t, admin))


# ---------------------------------------------------------------------------
# Logs (spec section 23 - two separate trails)
# ---------------------------------------------------------------------------


@router.get("/events/{event_id}/logs")
def logs(
    event_id: str,
    log: Literal["game", "admin"] = "game",
    limit: int = Query(default=300, ge=1, le=2000),
    _admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    event = load_event(db, event_id)
    names = dict(db.execute(select(Team.id, Team.team_name).where(Team.event_id == event.id)).all())
    if log == "game":
        rows = db.scalars(select(GameEvent).where(GameEvent.event_id == event.id).order_by(GameEvent.created_at.desc()).limit(limit))
        return [
            {"at": iso(r.created_at), "kind": r.kind, "team_name": names.get(r.team_id), "message": r.message}
            for r in rows
        ]
    rows = db.scalars(select(AdminAction).where(AdminAction.event_id == event.id).order_by(AdminAction.created_at.desc()).limit(limit))
    return [
        {"at": iso(r.created_at), "kind": r.action, "admin": r.admin_username, "team_name": names.get(r.team_id), "message": r.notes}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Results (spec section 21)
# ---------------------------------------------------------------------------


@router.get("/events/{event_id}/results")
def results(event_id: str, _admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    return {
        "event_status": event.status,
        "coordinator": results_service.coordinator_results(db, event),
        "public": results_service.public_results(db, event),
    }


@router.get("/events/{event_id}/results/export")
def results_export(event_id: str, _admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    content = export_service.build_results_workbook(
        event_name=event.name,
        rows=results_service.coordinator_results(db, event),
        generated_at=datetime.now(timezone.utc),
    )
    filename = f"round2-results-{utcnow().strftime('%Y%m%d-%H%M')}.xlsx"
    return Response(
        content=content,
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Access-Control-Expose-Headers": "Content-Disposition"},
    )
