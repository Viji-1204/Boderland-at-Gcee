"""Event lifecycle (spec section 2): DRAFT -> CONFIGURED -> LIVE <-> PAUSED -> ENDED."""
from __future__ import annotations

import secrets
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ConflictError
from app.core.timeutil import utcnow
from app.models import (
    Admin,
    Event,
    EventStatus,
    Location,
    LocationPhoto,
    Power,
    PowerKind,
    PowerUsage,
    SentenceFragment,
    Team,
    TeamStatus,
    UsageStatus,
)
from app.services import audit
from app.services.event_settings import event_settings, validate_settings_patch
from app.services.geo import valid_coordinate
from app.services.route_service import (
    MAX_SELECTED,
    MIN_SELECTED,
    capacity_summary,
    recompute_start_offsets,
    route_problems,
    route_teams,
    selected_locations,
)

DEFAULT_POWER_PRICES = {
    PowerKind.HELP: (10, 2),
    PowerKind.ATTACK: (30, 3),
    PowerKind.DEFENCE: (20, 3),
}


def new_qr_token(db: Session) -> str:
    """Unguessable per-location QR value (spec section 11)."""
    while True:
        token = "BL2-" + secrets.token_urlsafe(9)
        if db.scalar(select(Location.id).where(Location.qr_token == token)) is None:
            return token


def ensure_status(event: Event, *allowed: str, action: str) -> None:
    if event.status not in allowed:
        raise ConflictError(f"Can't {action} while the event is {event.status}.")


# ---------------------------------------------------------------------------
# Creation / settings
# ---------------------------------------------------------------------------


def create_event(db: Session, admin: Admin, name: str, clone_from: Event | None = None) -> Event:
    event = Event(name=name.strip(), status=EventStatus.DRAFT, settings={})
    db.add(event)
    db.flush()

    if clone_from is not None:
        event.settings = dict(clone_from.settings or {})
        event.final_location_name = clone_from.final_location_name
        event.final_latitude = clone_from.final_latitude
        event.final_longitude = clone_from.final_longitude
        for src in db.scalars(select(Location).where(Location.event_id == clone_from.id)):
            loc = Location(
                event_id=event.id,
                code=src.code,
                name=src.name,
                latitude=src.latitude,
                longitude=src.longitude,
                geofence_radius_m=src.geofence_radius_m,
                is_selected=src.is_selected,
                qr_token=new_qr_token(db),  # fresh codes: never reuse last event's printouts
            )
            db.add(loc)
            db.flush()
            if src.photo is not None:  # same campus spot, same reference photo
                loc.photo = LocationPhoto(
                    content_type=src.photo.content_type,
                    data=src.photo.data,
                    thumb_content_type=src.photo.thumb_content_type,
                    thumb=src.photo.thumb,
                    size_bytes=src.photo.size_bytes,
                )
        for src in db.scalars(select(Power).where(Power.event_id == clone_from.id)):
            db.add(Power(event_id=event.id, kind=src.kind, cost=src.cost, max_per_team=src.max_per_team, active=src.active))
    else:
        for kind, (cost, cap) in DEFAULT_POWER_PRICES.items():
            db.add(Power(event_id=event.id, kind=kind, cost=cost, max_per_team=cap, active=True))

    audit.log_admin(db, admin, event.id, "EVENT_CREATED", f"{event.name}" + (f" (copied from {clone_from.name})" if clone_from else ""))
    db.flush()
    return event


def update_event(db: Session, event: Event, admin: Admin, changes: dict) -> Event:
    if "name" in changes and changes["name"] is not None:
        name = str(changes["name"]).strip()
        if not name:
            raise AppError("Event name can't be empty.")
        event.name = name

    final_fields = {"final_location_name", "final_latitude", "final_longitude"}
    if final_fields & {k for k, v in changes.items() if v is not None}:
        ensure_status(event, EventStatus.DRAFT, EventStatus.CONFIGURED, action="move the final destination")
        if changes.get("final_location_name"):
            event.final_location_name = str(changes["final_location_name"]).strip()[:120]
        if changes.get("final_latitude") is not None:
            event.final_latitude = float(changes["final_latitude"])
        if changes.get("final_longitude") is not None:
            event.final_longitude = float(changes["final_longitude"])

    patch = changes.get("settings") or {}
    if patch:
        clean = validate_settings_patch(patch)
        before = event_settings(event)
        if event.status in (EventStatus.LIVE, EventStatus.PAUSED, EventStatus.ENDED):
            locked_keys = {"staggered_start_offset_s", "starting_power_points"}
            if locked_keys & set(clean):
                raise ConflictError("Start offsets and starting power points can't change once the event is live.")
        event.settings = {**(event.settings or {}), **clean}
        after = event_settings(event)

        if "starting_power_points" in clean and after["starting_power_points"] != before["starting_power_points"]:
            delta = after["starting_power_points"] - before["starting_power_points"]
            for team in db.scalars(select(Team).where(Team.event_id == event.id)):
                team.power_points = max(0, team.power_points + delta)
        if "staggered_start_offset_s" in clean:
            recompute_start_offsets(db, event)

        audit.log_admin(db, admin, event.id, "SETTINGS_CHANGED", ", ".join(f"{k}={v}" for k, v in clean.items()))
    audit.notify_dashboard(db, event.id)
    return event


# ---------------------------------------------------------------------------
# Readiness checklist (shown in the admin console; lock requires all "ok")
# ---------------------------------------------------------------------------


def split_sentence(sentence: str | None, parts: int) -> list[str] | None:
    """Split a team's sentence into ``parts`` fragments (spec section 14).

    Use ``|`` in the sentence to choose the cut points yourself; otherwise
    words are shared out as evenly as possible.
    """
    text = (sentence or "").strip()
    if not text or parts < 1:
        return None
    if "|" in text:
        chunks = [c.strip() for c in text.split("|")]
        return chunks if len(chunks) == parts and all(chunks) else None
    words = text.split()
    if len(words) < parts:
        return None
    base, extra = divmod(len(words), parts)
    out, i = [], 0
    for k in range(parts):
        size = base + (1 if k < extra else 0)
        out.append(" ".join(words[i : i + size]))
        i += size
    return out


def readiness(db: Session, event: Event) -> list[dict]:
    locs = selected_locations(db, event.id)
    n = len(locs)
    teams = route_teams(db, event.id)
    checks: list[dict] = []

    def add(key: str, label: str, ok: bool, detail: str) -> None:
        checks.append({"key": key, "label": label, "ok": ok, "detail": detail})

    add(
        "locations",
        f"{MIN_SELECTED}-{MAX_SELECTED} checkpoints selected",
        MIN_SELECTED <= n <= MAX_SELECTED,
        f"{n} selected",
    )
    missing_coords = [loc.code for loc in locs if not valid_coordinate(loc.latitude, loc.longitude)]
    add("coordinates", "Every checkpoint has GPS coordinates", bool(locs) and not missing_coords,
        "All set" if locs and not missing_coords else f"Missing: {', '.join(missing_coords) or 'no checkpoints'}")

    add("teams", "At least one team", bool(teams), f"{len(teams)} team(s)")

    cap = capacity_summary(locs, len(teams)) if locs else {"feasible": False, "message": "No checkpoints selected"}
    add("capacity", "Enough unique routes for every team", bool(locs) and cap["feasible"], cap["message"])

    # A valid route also holds the team's Jack, Queen and King in order.
    problems = route_problems(db, event) if teams else ["No teams yet."]
    add("routes", "Every team has a valid, unique route with its Jack, Queen and King", not problems, "All valid" if not problems else problems[0] + (f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""))

    bad_sentences = [t.team_name for t in teams if split_sentence(t.sentence, n) is None]
    add("sentences", f"Every team's sentence splits into {n} fragments", bool(teams) and not bad_sentences,
        "All set" if teams and not bad_sentences else f"Check: {', '.join(bad_sentences[:4]) or 'no teams'}" + ("..." if len(bad_sentences) > 4 else ""))

    add("final", "Final destination (Joker) has GPS coordinates", valid_coordinate(event.final_latitude, event.final_longitude),
        event.final_location_name or "Not set")
    return checks


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


def lock(db: Session, event: Event, admin: Admin) -> None:
    ensure_status(event, EventStatus.DRAFT, action="lock the configuration")
    failing = [c for c in readiness(db, event) if not c["ok"]]
    if failing:
        raise ConflictError(
            "Not ready to lock: " + "; ".join(f"{c['label']} ({c['detail']})" for c in failing),
            extra={"checks": failing},
        )
    n = len(selected_locations(db, event.id))
    teams = route_teams(db, event.id)
    db.execute(delete(SentenceFragment).where(SentenceFragment.team_id.in_([t.id for t in teams])))
    for team in teams:
        for seq, text in enumerate(split_sentence(team.sentence, n) or [], start=1):
            db.add(SentenceFragment(team_id=team.id, seq=seq, text=text))
        team.status = TeamStatus.WAITING
    recompute_start_offsets(db, event)
    event.status = EventStatus.CONFIGURED
    event.config_locked_at = utcnow()
    audit.log_admin(db, admin, event.id, "EVENT_LOCKED", "DRAFT -> CONFIGURED")
    audit.notify_event(db, event.id, {"type": "event_status", "status": event.status})
    audit.notify_dashboard(db, event.id)


def unlock(db: Session, event: Event, admin: Admin) -> None:
    ensure_status(event, EventStatus.CONFIGURED, action="unlock the configuration")
    teams = route_teams(db, event.id)
    db.execute(delete(SentenceFragment).where(SentenceFragment.team_id.in_([t.id for t in teams])))
    for team in teams:
        team.status = TeamStatus.NOT_STARTED
    event.status = EventStatus.DRAFT
    event.config_locked_at = None
    audit.log_admin(db, admin, event.id, "EVENT_UNLOCKED", "CONFIGURED -> DRAFT")
    audit.notify_event(db, event.id, {"type": "event_status", "status": event.status})
    audit.notify_dashboard(db, event.id)


def start(db: Session, event: Event, admin: Admin) -> None:
    ensure_status(event, EventStatus.CONFIGURED, action="start the game")
    now = utcnow()
    event.status = EventStatus.LIVE
    event.started_at = now
    for team in route_teams(db, event.id):
        if team.status != TeamStatus.WAITING:
            continue  # only teams validated at lock (route + sentence) may play
        team.status = TeamStatus.ACTIVE
        team.started_at = now + timedelta(seconds=team.start_offset_s or 0)
    audit.log_admin(db, admin, event.id, "EVENT_STARTED", "CONFIGURED -> LIVE (power purchases now closed)")
    audit.log_game(db, event.id, None, "EVENT_STARTED", f"{event.name} is live.")
    audit.notify_event(db, event.id, {"type": "event_status", "status": event.status})
    audit.notify_dashboard(db, event.id)


def pause(db: Session, event: Event, admin: Admin) -> None:
    ensure_status(event, EventStatus.LIVE, action="pause the game")
    event.status = EventStatus.PAUSED
    event.paused_at = utcnow()
    audit.log_admin(db, admin, event.id, "EVENT_PAUSED", "LIVE -> PAUSED")
    audit.notify_event(db, event.id, {"type": "event_status", "status": event.status})
    audit.notify_dashboard(db, event.id)


def resume(db: Session, event: Event, admin: Admin) -> None:
    """Resume, handing back the paused time to every running clock."""
    ensure_status(event, EventStatus.PAUSED, action="resume the game")
    now = utcnow()
    paused_at = event.paused_at or now
    delta = now - paused_at
    for team in db.scalars(select(Team).where(Team.event_id == event.id)):
        if team.status not in (TeamStatus.COMPLETED, TeamStatus.DISQUALIFIED) and team.started_at is not None:
            team.started_at += delta  # elapsed time excludes the pause
        if team.frozen_until is not None and team.frozen_until > paused_at:
            team.frozen_until += delta
    for usage in db.scalars(
        select(PowerUsage).where(PowerUsage.event_id == event.id, PowerUsage.status == UsageStatus.PENDING)
    ):
        if usage.expires_at is not None and usage.expires_at > paused_at:
            usage.expires_at += delta
    event.status = EventStatus.LIVE
    event.paused_at = None
    audit.log_admin(db, admin, event.id, "EVENT_RESUMED", f"PAUSED -> LIVE after {int(delta.total_seconds())}s")
    audit.notify_event(db, event.id, {"type": "event_status", "status": event.status})
    audit.notify_dashboard(db, event.id)


def end(db: Session, event: Event, admin: Admin) -> None:
    ensure_status(event, EventStatus.LIVE, EventStatus.PAUSED, action="end the game")
    now = utcnow()
    db.execute(
        update(PowerUsage)
        .where(PowerUsage.event_id == event.id, PowerUsage.status == UsageStatus.PENDING)
        .values(status=UsageStatus.CANCELLED, resolved_at=now)
    )
    event.status = EventStatus.ENDED
    event.ended_at = now
    event.paused_at = None
    audit.log_admin(db, admin, event.id, "EVENT_ENDED", "Results are final")
    audit.log_game(db, event.id, None, "EVENT_ENDED", f"{event.name} has ended.")
    audit.notify_event(db, event.id, {"type": "event_status", "status": event.status})
    audit.notify_dashboard(db, event.id)
