"""Coordinator overrides (spec section 22). Every one is written to
admin_actions with who did it and why, separate from automatic game events."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ConflictError
from app.core.timeutil import iso
from app.models import Admin, Event, EventStatus, Foul, Team, TeamStatus
from app.services import audit
from app.services.scan_service import is_frozen, team_route


def game_now(event: Event, now: datetime) -> datetime:
    """The game clock stops during a pause: anything stamped then counts as
    happening at the moment the pause began (resume shifts running clocks)."""
    if event.status == EventStatus.PAUSED and event.paused_at is not None:
        return event.paused_at
    return now


def add_foul(db: Session, event: Event, team: Team, admin: Admin, reason: str, now: datetime) -> None:
    reason = (reason or "").strip() or "Coordinator penalty"
    team.foul_count += 1
    db.add(Foul(event_id=event.id, team_id=team.id, reason=reason, source="ADMIN", created_at=now))
    audit.log_admin(db, admin, event.id, "FOUL_ADDED", reason, team.id)
    audit.team_changed(db, event.id, team.id)


def remove_foul(db: Session, event: Event, team: Team, admin: Admin, reason: str) -> None:
    latest = db.scalar(
        select(Foul)
        .where(Foul.team_id == team.id, Foul.voided.is_(False))
        .order_by(Foul.created_at.desc())
        .limit(1)
    )
    if latest is None or team.foul_count <= 0:
        raise ConflictError(f"{team.team_name} has no fouls to remove.")
    latest.voided = True  # kept for the record, just no longer counted
    team.foul_count -= 1
    audit.log_admin(db, admin, event.id, "FOUL_REMOVED", (reason or "").strip() or f"Voided: {latest.reason}", team.id)
    audit.team_changed(db, event.id, team.id)


def freeze_team(db: Session, event: Event, team: Team, admin: Admin, seconds: int, now: datetime) -> None:
    if team.status not in TeamStatus.PLAYING:
        raise ConflictError(f"{team.team_name} isn't in play.")
    if not 10 <= seconds <= 3600:
        raise AppError("Freeze between 10 and 3600 seconds.")
    # While paused, count from the pause so resume's time shift leaves exactly `seconds`.
    team.frozen_until = game_now(event, now) + timedelta(seconds=seconds)
    audit.log_admin(db, admin, event.id, "TEAM_FROZEN", f"{seconds}s", team.id)
    audit.notify_team(db, team.id, {"type": "frozen", "frozen_until": iso(team.frozen_until), "reason": "coordinator"})
    audit.team_changed(db, event.id, team.id)


def unfreeze_team(db: Session, event: Event, team: Team, admin: Admin, now: datetime) -> None:
    if not is_frozen(team, now):
        raise ConflictError(f"{team.team_name} isn't frozen.")
    team.frozen_until = None
    audit.log_admin(db, admin, event.id, "TEAM_UNFROZEN", None, team.id)
    audit.notify_team(db, team.id, {"type": "unfrozen"})
    audit.team_changed(db, event.id, team.id)


def unlock_puzzle(db: Session, event: Event, team: Team, admin: Admin, reason: str) -> None:
    """Skip a puzzle a team is genuinely stuck on (a broken prop, a typo in
    the question...). Logged, so it can be weighed in disputes."""
    if team.status != TeamStatus.PUZZLE_LOCKED:
        raise ConflictError(f"{team.team_name} isn't waiting on a puzzle.")
    total = len(team_route(team))
    team.status = TeamStatus.FINAL if team.progress >= total else TeamStatus.ACTIVE
    audit.log_admin(db, admin, event.id, "PUZZLE_UNLOCKED", (reason or "").strip() or None, team.id)
    audit.notify_team(db, team.id, {"type": "toast", "message": "A coordinator unlocked your puzzle - radar is on."})
    audit.team_changed(db, event.id, team.id)


def verify_joker(db: Session, event: Event, team: Team, admin: Admin, now: datetime) -> None:
    """Spec section 20: the coordinator verifies the Joker at the final location."""
    if event.status not in (EventStatus.LIVE, EventStatus.PAUSED):
        raise ConflictError("The game isn't running.")
    if team.status != TeamStatus.FINAL:
        raise ConflictError(f"{team.team_name} hasn't cleared every checkpoint yet ({team.status}).")
    team.status = TeamStatus.COMPLETED
    team.completed_at = game_now(event, now)  # verified during a pause: the clock stopped at the pause
    team.frozen_until = None
    audit.log_admin(db, admin, event.id, "JOKER_VERIFIED", None, team.id)
    audit.log_game(db, event.id, team.id, "COMPLETED", f"{team.team_name} found the Joker!")
    audit.notify_team(db, team.id, {"type": "completed"})
    audit.team_changed(db, event.id, team.id, leaderboard=True)


def disqualify(db: Session, event: Event, team: Team, admin: Admin, reason: str) -> None:
    if team.status == TeamStatus.DISQUALIFIED:
        raise ConflictError(f"{team.team_name} is already disqualified.")
    reason = (reason or "").strip()
    if not reason:
        raise AppError("Give a reason for the disqualification.")
    team.prev_status = team.status
    team.status = TeamStatus.DISQUALIFIED
    team.disqualified_reason = reason
    audit.log_admin(db, admin, event.id, "TEAM_DISQUALIFIED", reason, team.id)
    audit.team_changed(db, event.id, team.id, leaderboard=True)


def reinstate(db: Session, event: Event, team: Team, admin: Admin) -> None:
    if team.status != TeamStatus.DISQUALIFIED:
        raise ConflictError(f"{team.team_name} isn't disqualified.")
    if event.status != EventStatus.DRAFT and team.prev_status in (None, TeamStatus.NOT_STARTED):
        # Disqualified before the lock, so the lock never validated its route or
        # cut its sentence. Letting it back in now would start it on a broken route.
        raise ConflictError(
            f"{team.team_name} was disqualified before the configuration was locked. "
            "Unlock the event (back to DRAFT), reinstate the team, regenerate routes and lock again."
        )
    team.status = team.prev_status or TeamStatus.NOT_STARTED
    team.prev_status = None
    team.disqualified_reason = None
    audit.log_admin(db, admin, event.id, "TEAM_REINSTATED", None, team.id)
    audit.team_changed(db, event.id, team.id, leaderboard=True)
