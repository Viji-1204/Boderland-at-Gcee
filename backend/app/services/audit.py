"""The two logs from spec section 23, plus the real-time hints that go with them.

* ``log_game``  -> game_events   (what the system decided during normal play)
* ``log_admin`` -> admin_actions (what a human overrode, and why)
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.timeutil import iso, utcnow
from app.database import queue_publish
from app.models import Admin, AdminAction, GameEvent
from app.services.websocket_service import coord_channel, event_channel, team_channel


def log_game(db: Session, event_id: str, team_id: str | None, kind: str, message: str) -> None:
    entry = GameEvent(event_id=event_id, team_id=team_id, kind=kind, message=message, created_at=utcnow())
    db.add(entry)
    queue_publish(
        db,
        coord_channel(event_id),
        {"type": "log", "log": "game", "kind": kind, "message": message, "team_id": team_id, "at": iso(entry.created_at)},
    )


def log_admin(
    db: Session,
    admin: Admin,
    event_id: str | None,
    action: str,
    notes: str | None = None,
    team_id: str | None = None,
) -> None:
    entry = AdminAction(
        event_id=event_id,
        admin_id=admin.id,
        admin_username=admin.username,
        team_id=team_id,
        action=action,
        notes=notes,
        created_at=utcnow(),
    )
    db.add(entry)
    if event_id:
        queue_publish(
            db,
            coord_channel(event_id),
            {
                "type": "log",
                "log": "admin",
                "kind": action,
                "message": f"{admin.username}: {action}" + (f" - {notes}" if notes else ""),
                "team_id": team_id,
                "at": iso(entry.created_at),
            },
        )


def notify_team(db: Session, team_id: str, message: dict) -> None:
    queue_publish(db, team_channel(team_id), message)


def notify_event(db: Session, event_id: str, message: dict) -> None:
    queue_publish(db, event_channel(event_id), message)


def notify_dashboard(db: Session, event_id: str) -> None:
    queue_publish(db, coord_channel(event_id), {"type": "dashboard"})


def team_changed(db: Session, event_id: str, team_id: str, leaderboard: bool = False) -> None:
    """Common hint bundle after any change to a team's state."""
    notify_team(db, team_id, {"type": "state"})
    notify_dashboard(db, event_id)
    if leaderboard:
        notify_event(db, event_id, {"type": "leaderboard"})
