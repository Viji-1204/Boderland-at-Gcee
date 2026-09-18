"""The built-in puzzle a team gets at a checkpoint: dealing it and showing it.

Playing it (answers, moves) lives in scan_service with the rest of the
checkpoint loop.
"""
from __future__ import annotations

import random
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Event, PuzzleSession, RouteStop, Team
from app.services import puzzles
from app.services.event_settings import event_settings

rng = random.SystemRandom()


def _find(db: Session, team: Team, stop: RouteStop) -> PuzzleSession | None:
    return db.scalar(select(PuzzleSession).where(PuzzleSession.team_id == team.id, PuzzleSession.location_id == stop.location_id))


def session_for(db: Session, team: Team, stop: RouteStop) -> PuzzleSession:
    """The team's puzzle at this checkpoint, dealt the first time it's needed
    (normally when its QR is verified, inside that scan's transaction)."""
    found = _find(db, team, stop)
    if found is not None:
        return found
    kind = puzzles.kind_for_code(stop.location.code)
    module = puzzles.BY_KIND[kind]
    earlier = sum(1 for s in team.route if s.seq < stop.seq and puzzles.kind_for_code(s.location.code) == kind)
    session = PuzzleSession(
        team_id=team.id,
        location_id=stop.location_id,
        kind=kind,
        state=module.new_state(puzzles.pick(team.id, kind, earlier, module.SIZE), rng),
    )
    db.add(session)
    db.flush()
    return session


def session_for_reading(db: Session, team: Team, stop: RouteStop) -> PuzzleSession:
    """For read-only requests: a team locked on a puzzle before it had a
    session (e.g. across an upgrade) gets one dealt here. Nothing else is
    pending in such a request, so losing a race to another phone is safe."""
    try:
        session = session_for(db, team, stop)
        db.commit()
        return session
    except IntegrityError:
        db.rollback()
        return _find(db, team, stop)


def payload(event: Event, session: PuzzleSession, seq: int, total: int, now: datetime) -> dict:
    """What the phone may see: never the answer."""
    module = puzzles.BY_KIND[session.kind]
    wait = 0.0
    cooldown = int(event_settings(event)["puzzle_cooldown_s"])
    if module.CHECKED and cooldown and session.last_attempt_at is not None:
        wait = max(0.0, cooldown - (now - session.last_attempt_at).total_seconds())
    return {
        "id": session.id,
        "checkpoint": seq,
        "total": total,
        "kind": session.kind,
        "label": module.LABEL,
        "instructions": module.INSTRUCTIONS,
        "retry_after_s": round(wait, 1),
        "data": module.view(session.state),
    }
