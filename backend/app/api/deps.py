"""Auth dependencies (same token rules as Round 1) and the team-action wrapper."""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError, UnauthorizedError
from app.core.locks import team_locks
from app.core.security import decode_token, password_fingerprint
from app.core.timeutil import utcnow
from app.database import get_db
from app.models import Admin, AdminRole, Event, Team
from app.services import power_service
from app.services.scan_service import remember, replay

team_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/team/login", auto_error=False, scheme_name="TeamToken")
admin_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/admin/login", auto_error=False, scheme_name="AdminToken")


def claims_for(token: str | None, expected_type: str) -> dict:
    if not token:
        raise UnauthorizedError("Missing credentials - please log in.")
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise UnauthorizedError("Session expired. Please log in again.") from exc
    if payload.get("type") != expected_type:
        raise UnauthorizedError(f"Not a {expected_type} token.")
    return payload


def get_current_team(token: str | None = Depends(team_scheme), db: Session = Depends(get_db)) -> Team:
    payload = claims_for(token, "team")
    team = db.get(Team, payload.get("sub"))
    if team is None:
        raise UnauthorizedError("Team not found - please log in again.")
    if payload.get("pwv") != password_fingerprint(team.password_hash):
        raise UnauthorizedError("Your team's password was changed - please log in again.")
    return team


def get_current_admin(token: str | None = Depends(admin_scheme), db: Session = Depends(get_db)) -> Admin:
    payload = claims_for(token, "admin")
    admin = db.get(Admin, payload.get("sub"))
    if admin is None or not admin.is_active:
        raise UnauthorizedError("Admin account not found or deactivated.")
    if payload.get("pwv") != password_fingerprint(admin.password_hash):
        raise UnauthorizedError("Your password was changed - please log in again.")
    return admin


def require_super(admin: Admin = Depends(get_current_admin)) -> Admin:
    if admin.role != AdminRole.SUPER_ADMIN:
        raise ForbiddenError("Only a SUPER_ADMIN can do this.")
    return admin


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def load_event(db: Session, event_id: str) -> Event:
    event = db.get(Event, event_id)
    if event is None:
        raise NotFoundError("Event not found.")
    return event


def load_team(db: Session, event: Event, team_id: str) -> Team:
    team = db.get(Team, team_id)
    if team is None or team.event_id != event.id:
        raise NotFoundError("Team not found in this event.")
    return team


def run_team_action(
    db: Session,
    team: Team,
    key: str | None,
    endpoint: str,
    action: Callable[[Event, datetime], dict],
    extra_lock_ids: tuple[str, ...] = (),
) -> dict:
    """Run one game-changing team request, serialised per team (spec section 7).

    1. resolve any expired attacks first (takes its own locks);
    2. lock the team (and any other team the action changes);
    3. re-read the team and event, so concurrent phones act on fresh state;
    4. replay the stored response if this idempotency key was seen before;
    5. otherwise run, remember and commit, all inside the lock.
    """
    event = load_event(db, team.event_id)
    power_service.expire_due_attacks(db, event, utcnow())
    with team_locks(team.id, *extra_lock_ids):
        db.refresh(team, with_for_update=True)
        db.refresh(event)
        cached = replay(db, team.id, key)
        if cached is not None:
            return cached
        result = action(event, utcnow())
        remember(db, team.id, key, endpoint, result)
        db.commit()
        return result
