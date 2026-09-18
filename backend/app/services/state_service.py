"""Read models: a team's own state, the public leaderboard, the coordinator dashboard.

Privacy rules (spec sections 7, 13, 16, 17, 29):
* a team sees only its own data;
* a future checkpoint's name and coordinates are never sent (only
  checkpoints already cleared are named; the current one is radar-only).
  The one exception is the starting checkpoint: from the moment the game
  is live until the team scans it, the app shows where it is, with a map
  route - the app sends teams to their start, not the volunteers;
* fouls, freezes, powers and routes never appear on the public leaderboard.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.timeutil import iso
from app.models import (
    Event,
    EventStatus,
    FaceCard,
    GameEvent,
    PowerKind,
    PowerUsage,
    PuzzleSession,
    SentenceFragment,
    Team,
    TeamStatus,
    UsageStatus,
)
from app.services import power_service, results_service
from app.services.event_settings import event_settings
from app.services.geo import maps_directions_url
from app.services.scan_service import current_puzzle, effective_status, is_guided, is_jammed, is_warded, team_route


def _face_cards(team: Team) -> dict:
    return {face: iso(getattr(team, f"{face.lower()}_found_at")) for face in FaceCard.ORDER}


def _start_block(event: Event, team: Team, route: list) -> dict | None:
    """Where the team begins, shown once the game is live and until the
    starting checkpoint is scanned (progress 0)."""
    if event.status not in (EventStatus.LIVE, EventStatus.PAUSED) or team.progress != 0 or not route:
        return None
    if team.status not in TeamStatus.PLAYING:
        return None
    loc = route[0].location
    return {
        "seq": 1,
        "code": loc.code,
        "name": loc.name,
        "latitude": loc.latitude,
        "longitude": loc.longitude,
        "maps_url": maps_directions_url(loc.latitude, loc.longitude),
        "start_at": iso(team.started_at),
        "total": len(route),
    }


def _effects(team: Team, now: datetime) -> dict:
    """The timed effects on a team, as ISO timestamps (null when not active)."""
    return {
        "frozen_until": iso(team.frozen_until) if effective_status(team, now) == TeamStatus.FROZEN else None,
        "jammed_until": iso(team.jammed_until) if is_jammed(team, now) else None,
        "warded_until": iso(team.warded_until) if is_warded(team, now) else None,
        "guide_until": iso(team.guide_until) if is_guided(team, now) else None,
    }


def _powers_block(db: Session, event: Event, team: Team, now: datetime) -> dict:
    inv = power_service.inventory(db, team.id)
    prices = {p.kind: p for p in power_service.catalog(db, event.id)}
    kinds = []
    for kind in PowerKind.ALL:
        price = prices.get(kind)
        tp = inv.get(kind)
        kinds.append(
            {
                "kind": kind,
                "family": PowerKind.FAMILY[kind],
                "label": PowerKind.LABEL[kind],
                "cost": price.cost if price else None,
                "max_per_team": price.max_per_team if price else 0,
                "available": bool(price and price.active),
                "owned": tp.owned if tp else 0,
                "used": tp.used if tp else 0,
                "remaining": tp.remaining if tp else 0,
            }
        )
    return {"purchase_open": power_service.purchase_open(event), "items": kinds, "effects": _effects(team, now)}


def team_state(db: Session, event: Event, team: Team, now: datetime) -> dict:
    settings = event_settings(event)
    route = team_route(team)
    total = len(route)
    status = effective_status(team, now)

    checkpoints = []
    for stop in route:
        if stop.seq <= team.progress:
            checkpoints.append({"seq": stop.seq, "state": "DONE", "name": stop.location.name})
        elif stop.seq == team.progress + 1 and team.status == TeamStatus.ACTIVE:
            checkpoints.append({"seq": stop.seq, "state": "CURRENT", "name": None})
        else:
            checkpoints.append({"seq": stop.seq, "state": "LOCKED", "name": None})

    fragments = [
        {"seq": f.seq, "text": f.text}
        for f in db.scalars(
            select(SentenceFragment)
            .where(SentenceFragment.team_id == team.id, SentenceFragment.seq <= team.progress)
            .order_by(SentenceFragment.seq)
        )
    ]

    incoming = power_service.pending_attack_on(db, team.id)
    outgoing = [
        {"usage_id": u.id, "kind": u.kind, "target_name": name, "status": u.status, "resolved_with": u.resolved_with, "expires_at": iso(u.expires_at), "created_at": iso(u.created_at)}
        for u, name in db.execute(
            select(PowerUsage, Team.team_name)
            .join(Team, Team.id == PowerUsage.target_team_id)
            .where(PowerUsage.team_id == team.id, PowerUsage.kind.in_(PowerKind.ATTACKS))
            .order_by(PowerUsage.created_at.desc())
            .limit(5)
        )
    ]

    elapsed = None
    if team.completed_at and team.started_at:
        elapsed = int((team.completed_at - team.started_at).total_seconds())

    show_final = team.status in (TeamStatus.FINAL, TeamStatus.COMPLETED)
    state = {
        "server_now": iso(now),
        "event": {
            "id": event.id,
            "name": event.name,
            "status": event.status,
            "started_at": iso(event.started_at),
            "final_location_name": event.final_location_name if show_final else None,
            "settings": {
                "radar_near_radius_m": settings["radar_near_radius_m"],
                "attack_response_window_s": settings["attack_response_window_s"],
                "freeze_duration_s": settings["freeze_duration_s"],
                "jam_duration_s": settings["jam_duration_s"],
                "ward_duration_s": settings["ward_duration_s"],
                "guide_duration_s": settings["guide_duration_s"],
                "geofence_mode": settings["geofence_mode"],
            },
        },
        "team": {
            "id": team.id,
            "team_code": team.team_code,
            "team_name": team.team_name,
            "leader_name": team.leader_name,
            "status": status,
            "base_status": team.status,
            "power_points": team.power_points,
            "foul_count": team.foul_count,  # private: only ever sent to this team
            "progress": team.progress,
            "total_checkpoints": total,
            "start_at": iso(team.started_at),
            "frozen_until": iso(team.frozen_until) if status == TeamStatus.FROZEN else None,
            "jammed_until": iso(team.jammed_until) if is_jammed(team, now) else None,
            "warded_until": iso(team.warded_until) if is_warded(team, now) else None,
            "guide_until": iso(team.guide_until) if is_guided(team, now) else None,
            "completed_at": iso(team.completed_at),
            "elapsed_s": elapsed,
        },
        "checkpoints": checkpoints,
        "start": _start_block(event, team, route),
        "face_cards": _face_cards(team),
        "fragments": fragments,
        "fragments_total": total,
        "puzzle": current_puzzle(db, event, team, now),
        "powers": _powers_block(db, event, team, now),
        "incoming_attack": (
            {"usage_id": incoming.id, "kind": incoming.kind, "effect": power_service.attack_effect_text(event, incoming.kind), "expires_at": iso(incoming.expires_at)}
            if incoming is not None and incoming.expires_at and incoming.expires_at > now
            else None
        ),
        "outgoing_attacks": outgoing,
        "result": None,
    }
    if event.status == EventStatus.ENDED:
        mine = next((r for r in results_service.public_results(db, event) if r["team_name"] == team.team_name), None)
        state["result"] = mine
    return state


def leaderboard(db: Session, event: Event, viewer_team_id: str | None = None) -> dict:
    """Checkpoint progress only (spec section 17)."""
    teams = list(
        db.scalars(
            select(Team).where(
                Team.event_id == event.id,
                Team.status.notin_([TeamStatus.DISQUALIFIED]),
            )
        )
    )
    total = max((len(t.route) for t in teams), default=0)
    far_future = datetime.max

    def sort_key(t: Team):
        finished = t.status == TeamStatus.COMPLETED
        return (
            0 if finished else 1,
            (t.completed_at or far_future) if finished else far_future,
            -t.progress,
            t.last_checkpoint_at or far_future,
            t.team_name.casefold(),
        )

    rows = []
    for position, t in enumerate(sorted(teams, key=sort_key), start=1):
        rows.append(
            {
                "position": position,
                "team_name": t.team_name,
                "checkpoints": t.progress,
                "finished": t.status == TeamStatus.COMPLETED,
                "is_you": t.id == viewer_team_id,
            }
        )
    return {"event_status": event.status, "total_checkpoints": total, "rows": rows}


def dashboard(db: Session, event: Event, now: datetime) -> dict:
    """Everything, for coordinators only."""
    teams = list(db.scalars(select(Team).where(Team.event_id == event.id).order_by(Team.team_name)))
    team_ids = [t.id for t in teams]
    pending_attacks = {
        u.target_team_id: u
        for u in db.scalars(
            select(PowerUsage).where(
                PowerUsage.event_id == event.id,
                PowerUsage.kind.in_(PowerKind.ATTACKS),
                PowerUsage.status == UsageStatus.PENDING,
            )
        )
    }
    attempts: dict[str, int] = {}
    if team_ids:
        attempts = dict(
            db.execute(
                select(PuzzleSession.team_id, func.coalesce(func.sum(PuzzleSession.attempts), 0))
                .where(PuzzleSession.team_id.in_(team_ids))
                .group_by(PuzzleSession.team_id)
            ).all()
        )
    powers_left: dict[str, dict] = {}
    for tid in team_ids:
        powers_left[tid] = {k: v.remaining for k, v in power_service.inventory(db, tid).items()}

    rows = []
    counts = {"teams": len(teams), "playing": 0, "frozen": 0, "jammed": 0, "puzzle": 0, "final": 0, "completed": 0, "disqualified": 0}
    for t in teams:
        status = effective_status(t, now)
        route = team_route(t)
        target = None
        if t.status == TeamStatus.ACTIVE and t.progress < len(route):
            loc = route[t.progress].location
            target = {"seq": t.progress + 1, "code": loc.code, "name": loc.name}
        elif t.status == TeamStatus.PUZZLE_LOCKED and t.progress >= 1:
            loc = route[t.progress - 1].location
            target = {"seq": t.progress, "code": loc.code, "name": f"{loc.name} (puzzle)"}
        elif t.status == TeamStatus.FINAL:
            target = {"seq": None, "code": "JOKER", "name": event.final_location_name}

        if status == TeamStatus.FROZEN:
            counts["frozen"] += 1
        if t.status in TeamStatus.PLAYING and is_jammed(t, now):
            counts["jammed"] += 1
        if t.status in TeamStatus.PLAYING:
            counts["playing"] += 1
        if t.status == TeamStatus.PUZZLE_LOCKED:
            counts["puzzle"] += 1
        if t.status == TeamStatus.FINAL:
            counts["final"] += 1
        if t.status == TeamStatus.COMPLETED:
            counts["completed"] += 1
        if t.status == TeamStatus.DISQUALIFIED:
            counts["disqualified"] += 1

        attack = pending_attacks.get(t.id)
        rows.append(
            {
                "id": t.id,
                "team_code": t.team_code,
                "team_name": t.team_name,
                "leader_name": t.leader_name,
                "leader_phone": t.leader_phone,
                "status": status,
                "base_status": t.status,
                "progress": t.progress,
                "total": len(route),
                "target": target,
                "foul_count": t.foul_count,
                "power_points": t.power_points,
                "powers": powers_left.get(t.id, {}),
                "face_cards": _face_cards(t),
                "start_at": iso(t.started_at),
                "start_offset_s": t.start_offset_s,
                "frozen_until": iso(t.frozen_until) if status == TeamStatus.FROZEN else None,
                "effects": _effects(t, now),
                "completed_at": iso(t.completed_at),
                "puzzle_attempts": attempts.get(t.id, 0),
                "incoming_attack": {"kind": attack.kind, "expires_at": iso(attack.expires_at)} if attack else None,
                "incoming_attack_expires_at": iso(attack.expires_at) if attack else None,
                "disqualified_reason": t.disqualified_reason,
            }
        )

    recent = [
        {"kind": e.kind, "message": e.message, "team_id": e.team_id, "at": iso(e.created_at)}
        for e in db.scalars(
            select(GameEvent).where(GameEvent.event_id == event.id).order_by(GameEvent.created_at.desc()).limit(40)
        )
    ]
    return {"server_now": iso(now), "counts": counts, "teams": rows, "recent": recent}
