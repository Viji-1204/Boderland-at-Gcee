"""Logins - the Round 1 system (team code + password, admin username +
password, bcrypt, JWT), hardened:

* Two throttles. One is per client+account. The other is per account alone,
  so rotating the client address (e.g. a spoofed X-Forwarded-For) can't reset
  it. Team passwords are only 4 phone digits, so this matters.
* Unknown accounts still pay for a bcrypt check, so response time doesn't
  reveal which team codes exist.
* Tokens carry a fingerprint of the password hash (``pwv``). Resetting a
  password logs out every existing session.
"""
from __future__ import annotations

import math

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import RateLimitError, UnauthorizedError
from app.core.ratelimit import FailureThrottle
from app.core.security import burn_password_check, create_access_token, password_fingerprint, verify_password
from app.models import Admin, Event, EventStatus, Team

_throttle = FailureThrottle(settings.login_max_failures, settings.login_window_seconds)
# Per account, whatever the client: bounds distributed / spoofed-address guessing.
_account_throttle = FailureThrottle(settings.login_max_failures * 4, settings.login_window_seconds)


def _check_throttle(client_key: str, account_key: str) -> None:
    wait = max(_throttle.blocked_for(client_key), _account_throttle.blocked_for(account_key))
    if wait > 0:
        minutes = max(1, math.ceil(wait / 60))
        raise RateLimitError(f"Too many failed attempts. Try again in {minutes} minute(s).")


def _fail(client_key: str, account_key: str) -> None:
    _throttle.fail(client_key)
    _account_throttle.fail(account_key)


def team_login(db: Session, team_code: str, password: str, client: str) -> dict:
    code = (team_code or "").strip()
    account_key = f"team:{code.casefold()}"
    client_key = f"{client}|{account_key}"
    _check_throttle(client_key, account_key)

    # A code can exist in several events (e.g. last year's). Prefer the
    # event that isn't over, then the newest.
    candidates = db.execute(
        select(Team, Event)
        .join(Event, Event.id == Team.event_id)
        .where(func.lower(Team.team_code) == code.lower())
        .order_by(case((Event.status == EventStatus.ENDED, 1), else_=0), Event.created_at.desc())
    ).all()
    if not candidates:
        burn_password_check(password or "")
    for team, event in candidates:
        if verify_password(password or "", team.password_hash):
            _throttle.reset(client_key)
            token = create_access_token(
                team.id,
                "team",
                {"event_id": team.event_id, "team_code": team.team_code, "pwv": password_fingerprint(team.password_hash)},
            )
            return {
                "access_token": token,
                "token_type": "bearer",
                "team_id": team.id,
                "team_name": team.team_name,
                "team_code": team.team_code,
                "event_id": event.id,
            }
    _fail(client_key, account_key)
    raise UnauthorizedError("Invalid team code or password")


def admin_login(db: Session, username: str, password: str, client: str) -> dict:
    name = (username or "").strip()
    account_key = f"admin:{name.casefold()}"
    client_key = f"{client}|{account_key}"
    _check_throttle(client_key, account_key)
    admin = db.scalar(select(Admin).where(func.lower(Admin.username) == name.lower()))
    if admin is None:
        burn_password_check(password or "")
    if admin is None or not admin.is_active or not verify_password(password or "", admin.password_hash):
        _fail(client_key, account_key)
        raise UnauthorizedError("Invalid username or password")
    _throttle.reset(client_key)
    token = create_access_token(
        admin.id, "admin", {"role": admin.role, "username": admin.username, "pwv": password_fingerprint(admin.password_hash)}
    )
    return {"access_token": token, "token_type": "bearer", "role": admin.role, "username": admin.username}
