"""Photo hints: the checkpoint photo taken in Setup Routes, shown to a team
that is standing at its target but can't find the QR sticker.

Rules:
* Only when the radar is open (team ACTIVE, not frozen, not on a puzzle) and
  the phone is within the radar's "near" radius of the current target.
* ``photo_hints_per_team`` per game (default 2). A hint already revealed for
  the current checkpoint stays visible until it is scanned, at no extra cost.
* Never on the last ``photo_hint_locked_last`` checkpoints of the route
  (default 3) - the finish has to be earned.
* A checkpoint without a photo can't be hinted (nothing is charged).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.core.timeutil import iso
from app.models import Event, PhotoHint, Team, TeamStatus
from app.services import audit
from app.services.event_settings import event_settings
from app.services.geo import distance_and_bearing, valid_coordinate
from app.services.scan_service import assert_can_play, team_route


def used_count(db: Session, team_id: str) -> int:
    return db.scalar(select(func.count(PhotoHint.id)).where(PhotoHint.team_id == team_id)) or 0


def revealed_for(db: Session, team_id: str, location_id: str) -> PhotoHint | None:
    return db.scalar(select(PhotoHint).where(PhotoHint.team_id == team_id, PhotoHint.location_id == location_id))


def status(db: Session, event: Event, team: Team) -> dict:
    """What the phone shows: hints left, and whether one can be used right here."""
    settings = event_settings(event)
    per_team = int(settings["photo_hints_per_team"])
    locked_last = int(settings["photo_hint_locked_last"])
    used = used_count(db, team.id)
    out = {
        "per_team": per_team,
        "used": used,
        "remaining": max(0, per_team - used),
        "locked_last": locked_last,
        "usable_here": False,
        "revealed": False,
        "reason": None,
    }
    route = team_route(team)
    n = len(route)
    if per_team <= 0:
        out["reason"] = "Photo hints are off in this game."
        return out
    if team.status not in TeamStatus.PLAYING or team.progress >= n:
        out["reason"] = None  # nothing to hint: no current checkpoint
        return out
    stop = route[team.progress]
    if revealed_for(db, team.id, stop.location_id) is not None:
        out["revealed"] = True
        out["usable_here"] = True
        return out
    if stop.seq > n - locked_last:
        out["reason"] = f"No photo hints on the last {locked_last} checkpoints."
    elif used >= per_team:
        out["reason"] = "No photo hints left."
    elif stop.location.photo is None:
        out["reason"] = "This checkpoint has no photo."
    elif team.status != TeamStatus.ACTIVE:
        out["reason"] = "Solve your puzzle first."
    else:
        out["usable_here"] = True
    return out


def request(db: Session, event: Event, team: Team, lat: float | None, lng: float | None, accuracy: float | None, now: datetime) -> dict:
    assert_can_play(event, team, now)
    if team.status != TeamStatus.ACTIVE:
        raise ConflictError("Solve your puzzle first - photo hints are for finding the next checkpoint.")
    settings = event_settings(event)
    per_team = int(settings["photo_hints_per_team"])
    locked_last = int(settings["photo_hint_locked_last"])
    route = team_route(team)
    n = len(route)
    if per_team <= 0:
        raise ConflictError("Photo hints are off in this game.")
    if team.progress >= n:
        raise ConflictError("Every checkpoint is cleared - there is nothing to hint.")
    stop = route[team.progress]
    loc = stop.location

    existing = revealed_for(db, team.id, loc.id)
    if existing is not None:  # already paid for this checkpoint
        return {"revealed": True, "seq": stop.seq, "remaining": max(0, per_team - used_count(db, team.id)), "message": "Here is the photo again."}

    if stop.seq > n - locked_last:
        raise ConflictError(f"No photo hints on the last {locked_last} checkpoints - this one has to be found the hard way.")
    used = used_count(db, team.id)
    if used >= per_team:
        raise ConflictError("No photo hints left.")
    if loc.photo is None:
        raise ConflictError("This checkpoint has no photo - keep looking, or ask a coordinator.")
    if lat is None or lng is None or not valid_coordinate(lat, lng):
        raise AppError("Turn on location: a photo hint only works when you are at the checkpoint.")
    distance, _ = distance_and_bearing(lat, lng, loc.latitude, loc.longitude)
    slack = min(float(accuracy or 0.0), 25.0)  # a little GPS forgiveness, never more than 25 m
    if distance > float(settings["radar_near_radius_m"]) + slack:
        raise ConflictError("You're not close enough yet - follow the radar until it says YOU'RE HERE, then ask for the photo.")

    db.add(PhotoHint(event_id=event.id, team_id=team.id, location_id=loc.id, seq=stop.seq, created_at=now))
    db.flush()
    remaining = per_team - used - 1
    audit.log_game(db, event.id, team.id, "PHOTO_HINT", f"{team.team_name} used a photo hint at checkpoint {stop.seq}/{n} ({loc.code}) - {remaining} left")
    audit.team_changed(db, event.id, team.id)
    return {"revealed": True, "seq": stop.seq, "remaining": remaining, "message": f"Here is the spot. {remaining} photo hint(s) left."}


def image(db: Session, team: Team, thumb: bool) -> tuple[bytes, str]:
    """The revealed photo of the current target - and only that one."""
    route = team_route(team)
    if team.status not in TeamStatus.PLAYING or team.progress >= len(route):
        raise NotFoundError("No photo hint to show.")
    stop = route[team.progress]
    if revealed_for(db, team.id, stop.location_id) is None:
        raise NotFoundError("No photo hint to show.")
    photo = stop.location.photo
    if photo is None:
        raise NotFoundError("This checkpoint has no photo.")
    if thumb and photo.thumb is not None:
        return photo.thumb, photo.thumb_content_type or photo.content_type
    return photo.data, photo.content_type


def hint_rows(db: Session, event_id: str) -> dict[str, int]:
    """team_id -> photo hints used (for the coordinator dashboard and results)."""
    return dict(
        db.execute(select(PhotoHint.team_id, func.count(PhotoHint.id)).where(PhotoHint.event_id == event_id).group_by(PhotoHint.team_id)).all()
    )


__all__ = ["status", "request", "image", "used_count", "hint_rows", "iso"]
