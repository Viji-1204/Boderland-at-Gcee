"""The checkpoint loop (spec sections 10-13): scan -> puzzle -> radar -> next.

Everything that decides "correct / allowed / complete" happens here. The
phone only sends intents (a scanned code, an answer, its GPS position) and
renders what comes back.
"""
from __future__ import annotations

import copy
import math
import re
import time
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ConflictError, RateLimitError
from app.core.ratelimit import MinInterval
from app.core.timeutil import iso, seconds_until
from app.models import (
    Event,
    EventStatus,
    FaceCard,
    Foul,
    IdempotencyRecord,
    Location,
    RouteStop,
    Scan,
    ScanResult,
    SentenceFragment,
    Team,
    TeamStatus,
)
from app.services import audit, puzzle_service, puzzles
from app.services.event_settings import event_settings
from app.services.geo import distance_and_bearing, valid_coordinate

_scan_limiter = MinInterval(0.8)
_radar_limiter = MinInterval(1.0)
_radar_cache: dict[str, dict] = {}

TOKEN_RE = re.compile(r"BL2-[A-Za-z0-9_-]{6,40}")


# ---------------------------------------------------------------------------
# Shared guards
# ---------------------------------------------------------------------------


def is_frozen(team: Team, now: datetime) -> bool:
    return team.frozen_until is not None and team.frozen_until > now


def is_jammed(team: Team, now: datetime) -> bool:
    """Radar blacked out by a JAM attack; scanning and puzzles still work."""
    return team.jammed_until is not None and team.jammed_until > now


def is_warded(team: Team, now: datetime) -> bool:
    """A WARD is up: attacks are blocked without a prompt."""
    return team.warded_until is not None and team.warded_until > now


def is_guided(team: Team, now: datetime) -> bool:
    """A GUIDE is active: the current target is revealed on the radar."""
    return team.guide_until is not None and team.guide_until > now


def effective_status(team: Team, now: datetime) -> str:
    if team.status in TeamStatus.PLAYING and is_frozen(team, now):
        return TeamStatus.FROZEN
    return team.status


def assert_can_play(event: Event, team: Team, now: datetime, *, allow_frozen: bool = False) -> None:
    if event.status == EventStatus.PAUSED:
        raise ConflictError("The game is paused by the coordinators. Hold tight!")
    if event.status in (EventStatus.DRAFT, EventStatus.CONFIGURED):
        raise ConflictError("The game hasn't started yet.")
    if event.status == EventStatus.ENDED:
        raise ConflictError("The game has ended.")
    if team.status == TeamStatus.DISQUALIFIED:
        raise ConflictError("Your team has been disqualified. Please see a coordinator.")
    if team.status == TeamStatus.COMPLETED:
        raise ConflictError("You've already found the Joker - well played!")
    if team.status not in TeamStatus.PLAYING:
        raise ConflictError("Your team isn't in the game yet - please see a coordinator.")
    if team.started_at is not None and now < team.started_at:
        wait = math.ceil(seconds_until(team.started_at, now))
        raise ConflictError(
            f"Your start time hasn't arrived yet - {wait}s to go.", extra={"start_at": iso(team.started_at)}
        )
    if not allow_frozen and is_frozen(team, now):
        raise ConflictError(
            "You are frozen! Wait for the timer to run out.", extra={"frozen_until": iso(team.frozen_until)}
        )


def team_route(team: Team) -> list[RouteStop]:
    return sorted(team.route, key=lambda stop: stop.seq)


def extract_code(raw: str | None) -> str:
    """Printed QR stickers encode a link to the team app (so a phone's normal
    camera opens it). Accept either that link or the bare token."""
    text = (raw or "").strip()
    match = TOKEN_RE.search(text)
    return match.group(0) if match else text[:120]


# ---------------------------------------------------------------------------
# Idempotency (spec section 10/28): a retried request returns its first result
# ---------------------------------------------------------------------------


def replay(db: Session, team_id: str, key: str | None) -> dict | None:
    if not key:
        return None
    record = db.scalar(
        select(IdempotencyRecord).where(IdempotencyRecord.team_id == team_id, IdempotencyRecord.key == key[:80])
    )
    return None if record is None else {**record.response, "replayed": True}


def remember(db: Session, team_id: str, key: str | None, endpoint: str, response: dict) -> None:
    if key:
        db.add(IdempotencyRecord(team_id=team_id, key=key[:80], endpoint=endpoint, response=response))


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


def process_scan(
    db: Session,
    event: Event,
    team: Team,
    raw_code: str,
    now: datetime,
    lat: float | None = None,
    lng: float | None = None,
    accuracy: float | None = None,
) -> dict:
    assert_can_play(event, team, now)
    if _scan_limiter.check(team.id) > 0:
        raise RateLimitError("Scanning too fast - try again in a second.")

    code = extract_code(raw_code)
    if not code:
        raise AppError("No QR code value received.")

    route = team_route(team)
    total = len(route)
    base = {
        "checkpoint": None,
        "total": total,
        "progress": team.progress,
        "foul_added": False,
        "fragment": None,
        "face_card": None,
        "puzzle": None,
        "location_name": None,
        "geofence_warning": False,
    }

    def record(result: str, loc: Location | None = None, flag: bool = False, dist: float | None = None) -> None:
        db.add(
            Scan(
                event_id=event.id,
                team_id=team.id,
                location_id=loc.id if loc else None,
                code=code,
                result=result,
                geofence_flag=flag,
                distance_m=round(dist, 1) if dist is not None else None,
                created_at=now,
            )
        )

    loc = db.scalar(select(Location).where(Location.event_id == event.id, Location.qr_token == code))
    if loc is None or not loc.is_selected:
        # Not a code of this game (a poster, a typo...). The spec only fouls a
        # valid code that isn't the team's target, so this costs nothing.
        record(ScanResult.INVALID)
        return {**base, "result": ScanResult.INVALID, "message": "That QR code isn't part of this game. No foul - keep hunting."}

    # Optional geofence (spec section 11): a photographed QR forwarded to a
    # team that isn't there shows up as far away.
    flag, dist = False, None
    mode = event_settings(event)["geofence_mode"]
    if mode != "off":
        far = True
        if lat is not None and lng is not None and valid_coordinate(lat, lng):
            dist, _ = distance_and_bearing(lat, lng, loc.latitude, loc.longitude)
            far = dist > loc.geofence_radius_m + min(float(accuracy or 0.0), 100.0)
        if far and mode == "block":
            record(ScanResult.BLOCKED, loc, True, dist)
            return {
                **base,
                "result": ScanResult.BLOCKED,
                "message": "Location check failed - you need to be at the checkpoint to scan it. Turn on location and try again.",
            }
        flag = far

    if team.status == TeamStatus.PUZZLE_LOCKED:
        just_done = route[team.progress - 1] if team.progress >= 1 else None
        if just_done is not None and just_done.location_id == loc.id:
            record(ScanResult.REPEAT, loc, flag, dist)
            session = puzzle_service.session_for(db, team, just_done)
            return {
                **base,
                "result": ScanResult.REPEAT,
                "checkpoint": just_done.seq,
                "message": "Checkpoint already verified - solve its puzzle to unlock the radar.",
                "puzzle": puzzle_service.payload(event, session, just_done.seq, total, now),
            }
        record(ScanResult.LOCKED, loc, flag, dist)
        return {**base, "result": ScanResult.LOCKED, "message": "Solve your current puzzle before scanning another checkpoint."}

    if team.status == TeamStatus.ACTIVE and team.progress < total and route[team.progress].location_id == loc.id:
        return _valid_scan(db, event, team, loc, route, now, base, record, flag, dist)

    if loc.id in {stop.location_id for stop in route[: team.progress]}:
        record(ScanResult.REPEAT, loc, flag, dist)
        return {**base, "result": ScanResult.REPEAT, "message": "You've already cleared this checkpoint. No foul, no change."}

    team.foul_count += 1
    db.add(
        Foul(
            event_id=event.id,
            team_id=team.id,
            reason=f"Wrong QR scanned: {loc.code} ({loc.name})",
            location_id=loc.id,
            source="SYSTEM",
            created_at=now,
        )
    )
    record(ScanResult.WRONG_QR, loc, flag, dist)
    audit.log_game(db, event.id, team.id, "WRONG_QR", f"{team.team_name} scanned {loc.code} out of turn - foul +1")
    audit.team_changed(db, event.id, team.id)
    return {**base, "result": ScanResult.WRONG_QR, "foul_added": True, "message": "THIS IS NOT YOUR QR - FOUL +1"}


def _valid_scan(db, event, team, loc, route, now, base, record, flag, dist) -> dict:
    total = len(route)
    stop = route[team.progress]
    seq = stop.seq
    team.progress += 1
    team.last_checkpoint_at = now
    team.guide_until = None  # the Guide showed the way to this checkpoint; the next one is hidden again

    fragment = db.scalar(select(SentenceFragment).where(SentenceFragment.team_id == team.id, SentenceFragment.seq == seq))

    face, foul_added = None, False
    if stop.face_card:  # this team's Jack, Queen or King sits on this stop
        expected = next((f for f in FaceCard.ORDER if getattr(team, f"{f.lower()}_found_at") is None), None)
        setattr(team, f"{stop.face_card.lower()}_found_at", now)
        face = stop.face_card
        if expected != stop.face_card:
            # Routes are validated to hold the cards in order, so this only
            # fires if the data was changed underneath (spec section 15).
            team.foul_count += 1
            foul_added = True
            db.add(
                Foul(
                    event_id=event.id,
                    team_id=team.id,
                    reason=f"Face card out of order: found the {stop.face_card.title()} before the {expected.title() if expected else '?'}",
                    location_id=loc.id,
                    source="SYSTEM",
                    created_at=now,
                )
            )

    # Every checkpoint has a built-in puzzle; deal this team's version now.
    team.status = TeamStatus.PUZZLE_LOCKED
    session = puzzle_service.session_for(db, team, stop)

    record(ScanResult.VALID, loc, flag, dist)
    note = f" and found the {face.title()}" if face else ""
    warn = " [location check: far from checkpoint]" if flag else ""
    audit.log_game(db, event.id, team.id, "CHECKPOINT", f"{team.team_name} verified checkpoint {seq}/{total} ({loc.code}){note}{warn}")
    audit.team_changed(db, event.id, team.id, leaderboard=True)

    return {
        **base,
        "result": ScanResult.VALID,
        "checkpoint": seq,
        "progress": team.progress,
        "location_name": loc.name,
        "message": f"CHECKPOINT {seq} OF {total} VERIFIED - solve the puzzle to unlock the radar.",
        "fragment": {"seq": seq, "text": fragment.text} if fragment else None,
        "face_card": face,
        "foul_added": foul_added,
        "puzzle": puzzle_service.payload(event, session, seq, total, now),
        "geofence_warning": flag,
    }


# ---------------------------------------------------------------------------
# Puzzle (spec section 12)
# ---------------------------------------------------------------------------


def current_puzzle(db: Session, event: Event, team: Team, now: datetime) -> dict | None:
    """The puzzle of the checkpoint just verified. The server decides which
    puzzle that is, so a client can't play some other puzzle instead."""
    if team.status != TeamStatus.PUZZLE_LOCKED or team.progress < 1:
        return None
    route = team_route(team)
    stop = route[team.progress - 1]
    session = puzzle_service.session_for_reading(db, team, stop)
    return puzzle_service.payload(event, session, stop.seq, len(route), now)


def answer_puzzle(db: Session, event: Event, team: Team, answer: str, now: datetime) -> dict:
    """A typed answer (scrambled words, riddle)."""
    return play_puzzle(db, event, team, {"answer": answer}, now)


def play_puzzle(db: Session, event: Event, team: Team, move: dict, now: datetime) -> dict:
    """Any move on the open puzzle: an answer, a throw, a square, the swaps
    made, a filled-in crossword. Checked answers are unlimited and cost
    nothing, but a short cooldown follows each one so short answers can't be
    brute-forced by a script (spec section 12)."""
    assert_can_play(event, team, now)
    if team.status != TeamStatus.PUZZLE_LOCKED or team.progress < 1:
        raise ConflictError("There's no puzzle open right now.")
    route = team_route(team)
    total = len(route)
    stop = route[team.progress - 1]
    session = puzzle_service.session_for(db, team, stop)
    module = puzzles.BY_KIND[session.kind]

    cooldown = int(event_settings(event)["puzzle_cooldown_s"])
    if module.CHECKED and cooldown and session.last_attempt_at is not None:
        elapsed = (now - session.last_attempt_at).total_seconds()
        if elapsed < cooldown:
            wait = cooldown - elapsed
            raise RateLimitError(f"Wait {math.ceil(wait)}s before your next try.", extra={"retry_after_s": round(wait, 1)})

    state = copy.deepcopy(session.state)
    outcome = module.act(state, move or {}, puzzle_service.rng)
    session.state = state
    if outcome.attempt:
        session.attempts += 1
        session.last_attempt_at = now

    if not outcome.solved:
        if outcome.attempt:
            audit.notify_dashboard(db, event.id)
        return {
            "correct": False,
            "solved": False,
            "next": None,
            "message": outcome.message,
            "retry_after_s": cooldown if module.CHECKED and outcome.attempt else 0,
            "puzzle": puzzle_service.payload(event, session, stop.seq, total, now),
            **outcome.extra,
        }

    session.solved_at = now
    finished = team.progress >= total
    team.status = TeamStatus.FINAL if finished else TeamStatus.ACTIVE
    audit.log_game(
        db,
        event.id,
        team.id,
        "PUZZLE_SOLVED",
        f"{team.team_name} solved the checkpoint {stop.seq} puzzle ({module.LABEL})"
        + (" - all checkpoints cleared, heading to the Joker" if finished else ""),
    )
    audit.team_changed(db, event.id, team.id)
    return {
        "correct": True,
        "solved": True,
        "next": "FINAL" if finished else "RADAR",
        "retry_after_s": 0,
        "message": outcome.message
        + (
            " PUZZLE SOLVED - every checkpoint cleared! Follow the radar to the final destination and find the Joker."
            if finished
            else " PUZZLE SOLVED - radar unlocked. Head to your next checkpoint."
        ),
    }


# ---------------------------------------------------------------------------
# Radar (spec section 13)
# ---------------------------------------------------------------------------


def _proximity_text(distance: float, near: bool, final: bool) -> str:
    if near:
        return "YOU'RE HERE - find the coordinators and the Joker!" if final else "GOAL IS NEAR - find the QR code!"
    if distance <= 100:
        return "Very close..."
    if distance <= 250:
        return "Getting warmer"
    if distance <= 600:
        return "On the right track"
    return "Far away - keep moving"


def radar(
    db: Session,
    event: Event,
    team: Team,
    now: datetime,
    lat: float | None = None,
    lng: float | None = None,
    accuracy: float | None = None,
) -> dict:
    """Distance and direction to the current target only.

    Never returns the target's coordinates, name or any future checkpoint.
    Distances are rounded, the exact figure is hidden inside the "near"
    radius, and calls are throttled, which makes triangulating a target from
    a sofa much harder.

    The one exception is a paid-for Guide: while it lasts, the answer also
    carries the current target's name and exact position, so the app can
    show a Google Maps route. A jammed radar shows nothing - unless a Guide
    is active, which cuts through the jam.
    """
    settings = event_settings(event)
    guided = is_guided(team, now)

    def locked(reason: str, **extra) -> dict:
        return {"locked": True, "reason": reason, **extra}

    if event.status == EventStatus.PAUSED:
        return locked("The game is paused.")
    if event.status in (EventStatus.DRAFT, EventStatus.CONFIGURED):
        return locked("The radar switches on when the game starts.")
    if event.status == EventStatus.ENDED:
        return locked("The game has ended.")
    if team.status == TeamStatus.DISQUALIFIED:
        return locked("Your team has been disqualified.")
    if team.status == TeamStatus.COMPLETED:
        return locked("You found the Joker - the hunt is over for you!")
    if team.status not in TeamStatus.PLAYING:
        return locked("Your team isn't in the game yet.")
    if team.started_at is not None and now < team.started_at:
        return locked("Your start time hasn't arrived yet.", start_at=iso(team.started_at))
    if is_frozen(team, now):
        return locked("FROZEN - your radar is off until the timer runs out.", frozen_until=iso(team.frozen_until))
    if team.status == TeamStatus.PUZZLE_LOCKED:
        return locked("Solve the checkpoint puzzle to unlock the radar.")
    if is_jammed(team, now) and not guided:
        return locked("JAMMED - a rival scrambled your radar. Keep moving, or use a Guide.", jammed_until=iso(team.jammed_until), jammed=True)

    route = team_route(team)
    if team.status == TeamStatus.FINAL:
        if not valid_coordinate(event.final_latitude, event.final_longitude):
            return locked("Head to the coordinators' bench to find the Joker.")
        target = (event.final_latitude, event.final_longitude)
        label, final = f"Final destination: {event.final_location_name}", True
        target_name = event.final_location_name
    else:
        if team.progress >= len(route):  # defensive: no usable route (never a 500)
            return locked("Your route isn't set up - please see a coordinator.")
        loc = route[team.progress].location
        target = (loc.latitude, loc.longitude)
        label, final = f"Checkpoint {team.progress + 1} of {len(route)}", False
        target_name = loc.name

    base = {"locked": False, "target_label": label, "is_final": final, "near_radius_m": settings["radar_near_radius_m"], "guided": guided, "guide_until": iso(team.guide_until) if guided else None}
    if guided:
        # The Guide: the target itself, plus a walking route in Google Maps
        # (a plain link, no API key; the phone's Maps app opens it).
        base["target"] = {
            "name": target_name if not final else event.final_location_name,
            "latitude": target[0],
            "longitude": target[1],
            "maps_url": f"https://www.google.com/maps/dir/?api=1&destination={target[0]:.6f},{target[1]:.6f}&travelmode=walking",
        }
    if lat is None or lng is None or not valid_coordinate(lat, lng):
        return {**base, "needs_location": True, "reason": "Turn on location to use the radar."}

    cache_key = f"{team.id}:{team.progress}:{team.status}"
    if not guided and _radar_limiter.check(team.id) > 0 and cache_key in _radar_cache:
        return {**_radar_cache[cache_key], "throttled": True}

    distance, bearing = distance_and_bearing(lat, lng, target[0], target[1])
    near = distance <= settings["radar_near_radius_m"]
    step = 5 if distance < 300 else 10 if distance < 1000 else 50
    result = {
        **base,
        "needs_location": False,
        "near": near,
        # Guided: the exact figures. Otherwise rounded, and hidden once near.
        "distance_m": int(round(distance)) if guided else (None if near else int(round(distance / step) * step)),
        "bearing_deg": int(round(bearing)) % 360 if guided else int(round(bearing / 5.0) * 5) % 360,
        "proximity": _proximity_text(distance, near, final),
        "accuracy_m": round(float(accuracy), 1) if accuracy is not None else None,
        "at": time.time(),
    }
    if guided:
        return result
    if len(_radar_cache) > 5000:
        _radar_cache.clear()
    _radar_cache[cache_key] = result
    return result
