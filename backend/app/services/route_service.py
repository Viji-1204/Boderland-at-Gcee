"""Route generation and validation (spec sections 5 and 6).

Rules:
* Every team visits every selected location once. Seq 1 is its starting
  checkpoint.
* Every team meets a Jack, a Queen and a King, in that order. The three are
  dealt per team: when routes are generated, three of the team's stops are
  picked at random and the cards are laid on them in visit order. So two
  teams find the Jack at different checkpoints. The runtime check in
  scan_service is only a defensive fallback.
* No two teams share a full sequence (of locations; the cards on top can
  coincide).
* Starting checkpoints are handed out round-robin. Teams sharing a start get
  a staggered start offset.

Besides the hard rules, the generator samples several valid candidates per
team and keeps the one that least often puts two teams at the same location
on the same step. That spreads teams across the campus.
"""
from __future__ import annotations

import math
import random
from collections import Counter
from typing import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ConflictError
from app.models import Event, EventStatus, FaceCard, Location, RouteStop, Team, TeamStatus
from app.services.event_settings import event_settings

MIN_SELECTED = 7
MAX_SELECTED = 9
MAX_POOL = 15


def selected_locations(db: Session, event_id: str) -> list[Location]:
    return list(
        db.scalars(
            select(Location)
            .where(Location.event_id == event_id, Location.is_selected.is_(True))
            .order_by(Location.code)
        )
    )


def route_teams(db: Session, event_id: str) -> list[Team]:
    """Teams that need a route: everyone not disqualified."""
    return list(
        db.scalars(
            select(Team)
            .where(Team.event_id == event_id, Team.status != TeamStatus.DISQUALIFIED)
            .order_by(Team.team_name)
        )
    )


def face_cards_ok(faces: Sequence[str | None]) -> bool:
    """``faces`` is a route's card per stop, in visit order: exactly one Jack,
    one Queen and one King, met in that order."""
    return [f for f in faces if f] == list(FaceCard.ORDER)


def deal_face_cards(n: int, rng: random.Random) -> list[str | None]:
    """Lay the Jack, Queen and King on three random stops of an ``n``-stop
    route, in visit order (so the order rule holds by construction)."""
    faces: list[str | None] = [None] * n
    for slot, face in zip(sorted(rng.sample(range(n), len(FaceCard.ORDER))), FaceCard.ORDER):
        faces[slot] = face
    return faces


def start_capacity(n_locations: int) -> int:
    """How many distinct routes begin at any one start: the other stops in
    any order. (The cards are dealt on top and don't limit this.)"""
    return math.factorial(max(n_locations - 1, 0))


def capacity_summary(locs: Sequence[Location], team_count: int) -> dict:
    n = len(locs)
    per_start = start_capacity(n)
    total = n * per_start
    feasible = bool(locs) and team_count <= total
    if locs and team_count:
        # Round-robin gives each start at most ceil(teams / starts) teams.
        feasible = feasible and per_start >= math.ceil(team_count / n)
    return {
        "selected_locations": n,
        "starting_points": n,
        "unique_routes": total,
        "teams": team_count,
        "feasible": feasible,
        "message": (
            f"{n} locations support up to {total} valid unique routes for {team_count} team(s)."
            if feasible
            else f"{n} locations support up to {total} valid unique routes - you have {team_count} team(s). "
            "Add more locations or reduce the team count."
        ),
    }


def _check_pool(locs: Sequence[Location]) -> None:
    if not MIN_SELECTED <= len(locs) <= MAX_SELECTED:
        raise AppError(
            f"Select between {MIN_SELECTED} and {MAX_SELECTED} locations for the event "
            f"(currently {len(locs)} selected)."
        )


def _random_route(start: Location, others: list[Location], rng: random.Random) -> list[Location]:
    """Uniformly random route from ``start``."""
    rest = others[:]
    rng.shuffle(rest)
    return [start, *rest]


def recompute_start_offsets(db: Session, event: Event) -> None:
    """Teams sharing a starting checkpoint get staggered starts (spec section 6)."""
    stagger = int(event_settings(event)["staggered_start_offset_s"])
    groups: dict[str, list[Team]] = {}
    for team in route_teams(db, event.id):
        first = next((stop for stop in team.route if stop.seq == 1), None)
        if first is not None:
            groups.setdefault(first.location_id, []).append(team)
        else:
            team.start_offset_s = 0
    for teams in groups.values():
        for index, team in enumerate(sorted(teams, key=lambda t: t.team_name.casefold())):
            team.start_offset_s = index * stagger


def _ensure_draft(event: Event) -> None:
    if event.status != EventStatus.DRAFT:
        raise ConflictError("Routes can only be changed while the event is in DRAFT. Unlock the configuration first.")


def generate_routes(db: Session, event: Event, rng: random.Random | None = None) -> dict:
    _ensure_draft(event)
    rng = rng or random.SystemRandom()
    locs = selected_locations(db, event.id)
    _check_pool(locs)
    teams = route_teams(db, event.id)
    if not teams:
        raise AppError("Add teams before generating routes.")

    summary = capacity_summary(locs, len(teams))
    if not summary["feasible"]:
        raise ConflictError(summary["message"])

    eligible = locs[:]
    rng.shuffle(eligible)
    starts = [eligible[i % len(eligible)] for i in range(len(teams))]

    n = len(locs)
    used: set[tuple[str, ...]] = set()
    at_position = [Counter() for _ in range(n)]
    chosen: dict[str, list[Location]] = {}

    for team, start in zip(teams, starts):
        others = [loc for loc in locs if loc.id != start.id]
        best: list[Location] | None = None
        best_score = 0
        sampled = 0
        for _attempt in range(5000):
            candidate = _random_route(start, others, rng)
            key = tuple(loc.id for loc in candidate)
            if key in used:
                continue
            sampled += 1
            # Position 0 is the shared start (staggered), so it doesn't count.
            score = sum(at_position[i][loc.id] for i, loc in enumerate(candidate) if i > 0)
            if best is None or score < best_score:
                best, best_score = candidate, score
            if best_score == 0 or sampled >= 60:
                break
        if best is None:
            raise ConflictError(f"Could not find a unique route for {team.team_name}. Add more locations.")
        used.add(tuple(loc.id for loc in best))
        for i, loc in enumerate(best):
            at_position[i][loc.id] += 1
        chosen[team.id] = best

    db.execute(delete(RouteStop).where(RouteStop.team_id.in_([t.id for t in teams])))
    db.flush()
    for team in teams:
        faces = deal_face_cards(n, rng)  # each team's own Jack, Queen and King
        for seq, (loc, face) in enumerate(zip(chosen[team.id], faces), start=1):
            db.add(RouteStop(team_id=team.id, location_id=loc.id, seq=seq, face_card=face))
    db.flush()
    for team in teams:
        db.refresh(team, attribute_names=["route"])
    recompute_start_offsets(db, event)
    return summary


def set_manual_route(
    db: Session,
    event: Event,
    team: Team,
    location_ids: list[str],
    face_cards: dict[str, str] | None = None,
    rng: random.Random | None = None,
) -> None:
    """Coordinator override for one team; re-validated like a generated route.

    ``face_cards`` maps JACK/QUEEN/KING to the location that holds it. Left
    out, the team keeps its cards where they were (if it had all three) and
    otherwise gets them dealt at random, like a generated route.
    """
    _ensure_draft(event)
    locs = selected_locations(db, event.id)
    by_id = {loc.id: loc for loc in locs}
    if len(location_ids) != len(set(location_ids)):
        raise AppError("A route can't visit the same location twice.")
    if set(location_ids) != set(by_id):
        raise AppError("A route must visit every selected location exactly once.")
    key = tuple(location_ids)
    for other in route_teams(db, event.id):
        if other.id != team.id and tuple(s.location_id for s in other.route) == key:
            raise ConflictError(f"{other.team_name} already has exactly this route - routes must be unique.")

    if face_cards is None:
        kept = {s.face_card: s.location_id for s in team.route if s.face_card}
        face_cards = kept if all(f in kept for f in FaceCard.ORDER) else None
    if face_cards is None:
        faces = deal_face_cards(len(location_ids), rng or random.SystemRandom())
    else:
        holders = [face_cards.get(f) for f in FaceCard.ORDER]
        if any(not h for h in holders):
            raise AppError("Choose a checkpoint for each of the Jack, Queen and King.")
        if len(set(holders)) != len(holders):
            raise AppError("Each face card needs its own checkpoint.")
        if any(h not in by_id for h in holders):
            raise AppError("A face card must sit on one of the route's checkpoints.")
        faces = [next((f for f in FaceCard.ORDER if face_cards[f] == loc_id), None) for loc_id in location_ids]
        if not face_cards_ok(faces):
            raise AppError("Face cards must be met in order: Jack, then Queen, then King.")

    db.execute(delete(RouteStop).where(RouteStop.team_id == team.id))
    db.flush()
    for seq, (loc_id, face) in enumerate(zip(location_ids, faces), start=1):
        db.add(RouteStop(team_id=team.id, location_id=loc_id, seq=seq, face_card=face))
    db.flush()
    db.refresh(team, attribute_names=["route"])
    recompute_start_offsets(db, event)


def route_problems(db: Session, event: Event) -> list[str]:
    """Every reason the current routes can't be locked; empty list = all good."""
    ids = {loc.id for loc in selected_locations(db, event.id)}
    problems: list[str] = []
    seen: dict[tuple[str, ...], str] = {}
    for team in route_teams(db, event.id):
        stops = sorted(team.route, key=lambda s: s.seq)
        loc_ids = [s.location_id for s in stops]
        if not stops:
            problems.append(f"{team.team_name} has no route.")
            continue
        if len(loc_ids) != len(ids) or set(loc_ids) != ids:
            problems.append(f"{team.team_name}'s route doesn't match the selected locations.")
            continue
        if not face_cards_ok([s.face_card for s in stops]):
            problems.append(f"{team.team_name}'s route doesn't hold a Jack, a Queen and a King in that order - regenerate or edit it.")
            continue
        key = tuple(loc_ids)
        if key in seen:
            problems.append(f"{team.team_name} and {seen[key]} have identical routes.")
        seen[key] = team.team_name
    return problems
