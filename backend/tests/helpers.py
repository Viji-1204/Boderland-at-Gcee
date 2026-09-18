"""Shared helpers: seed the demo event, log in, walk a team through checkpoints."""
from __future__ import annotations

import itertools
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select

from app.core.timeutil import utcnow
from app.database import SessionLocal
from app.models import Event, Location, PuzzleSession, RouteStop, Team
from app.seed import DEMO_TEAMS, ensure_super_admin, seed_demo_event
from app.services import puzzles
from app.services.puzzles import rps, tictactoe

_keys = itertools.count(1)


def key() -> str:
    return f"test-key-{next(_keys)}"


@dataclass
class Demo:
    event_id: str
    admin: dict
    teams: dict = field(default_factory=dict)  # team_name -> {"id","code","password","headers"}


def seed(client, *, lock: bool = False, start: bool = False, settings: dict | None = None) -> Demo:
    with SessionLocal() as db:
        ensure_super_admin(db)
        event = seed_demo_event(db)
        db.commit()
        event_id = event.id
        ids = {t.team_name: t.id for t in db.scalars(select(Team).where(Team.event_id == event_id))}

    res = client.post("/api/v1/auth/admin/login", json={"username": "admin", "password": "admin123"})
    assert res.status_code == 200, res.text
    admin = {"Authorization": f"Bearer {res.json()['access_token']}"}
    demo = Demo(event_id=event_id, admin=admin)

    patch = {"puzzle_cooldown_s": 0, "staggered_start_offset_s": 0}
    patch.update(settings or {})
    res = client.patch(f"/api/v1/admin/events/{event_id}", json={"settings": patch}, headers=admin)
    assert res.status_code == 200, res.text

    for code, name, _leader, phone, _sentence in DEMO_TEAMS:
        res = client.post("/api/v1/auth/team/login", json={"team_code": code, "password": phone[:4]})
        assert res.status_code == 200, res.text
        demo.teams[name] = {
            "id": ids[name],
            "code": code,
            "password": phone[:4],
            "headers": {"Authorization": f"Bearer {res.json()['access_token']}"},
        }
    if lock or start:
        res = client.post(f"/api/v1/admin/events/{event_id}/lock", headers=admin)
        assert res.status_code == 200, res.text
    if start:
        res = client.post(f"/api/v1/admin/events/{event_id}/start", headers=admin)
        assert res.status_code == 200, res.text
    return demo


def route_of(team_id: str) -> list[Location]:
    with SessionLocal() as db:
        stops = db.scalars(select(RouteStop).where(RouteStop.team_id == team_id).order_by(RouteStop.seq)).all()
        return [db.get(Location, s.location_id) for s in stops]


def face_cards_of(team_id: str) -> dict[str, str]:
    """JACK/QUEEN/KING -> location id, as dealt on this team's route."""
    with SessionLocal() as db:
        stops = db.scalars(select(RouteStop).where(RouteStop.team_id == team_id).order_by(RouteStop.seq)).all()
        return {s.face_card: s.location_id for s in stops if s.face_card}


def token_for(location: Location) -> str:
    return location.qr_token


def scan(client, team: dict, code: str, **extra):
    return client.post("/api/v1/scan", json={"code": code, "idempotency_key": key(), **extra}, headers=team["headers"])


def answer(client, team: dict, text: str):
    return client.post("/api/v1/puzzle/answer", json={"answer": text, "idempotency_key": key()}, headers=team["headers"])


def play(client, team: dict, move: dict):
    return client.post("/api/v1/puzzle/play", json={**move, "idempotency_key": key()}, headers=team["headers"])


def open_session(team_id: str) -> PuzzleSession:
    """The team's puzzle at the checkpoint it has just verified."""
    with SessionLocal() as db:
        team = db.get(Team, team_id)
        stop = sorted(team.route, key=lambda s: s.seq)[team.progress - 1]
        return db.scalar(select(PuzzleSession).where(PuzzleSession.team_id == team_id, PuzzleSession.location_id == stop.location_id))


def puzzle_answer(team_id: str) -> str:
    """The answer to a typed puzzle (scrambled words, riddle)."""
    session = open_session(team_id)
    return puzzles.BY_KIND[session.kind].solution(session.state)[0]["answer"]


@contextmanager
def predictable_opponents():
    """The computer always throws scissors and always takes the last free square."""
    saved = rps.computer_throw, tictactoe.ai_move
    rps.computer_throw = lambda rng: "scissors"
    tictactoe.ai_move = lambda board, rng: max(i for i, ch in enumerate(board) if ch == ".")
    try:
        yield
    finally:
        rps.computer_throw, tictactoe.ai_move = saved


def solve_puzzle(client, team: dict):
    session = open_session(team["id"])
    res = None
    with predictable_opponents():
        for move in puzzles.BY_KIND[session.kind].solution(session.state):
            res = play(client, team, move)
            assert res.status_code == 200, res.text
    assert res.json()["solved"] is True, res.text
    return res


def clear_checkpoint(client, team: dict, location: Location) -> None:
    res = scan(client, team, location.qr_token)
    assert res.status_code == 200 and res.json()["result"] == "VALID", res.text
    solve_puzzle(client, team)


def backdate_attempts(team_id: str, seconds: int = 60) -> None:
    with SessionLocal() as db:
        for session in db.scalars(select(PuzzleSession).where(PuzzleSession.team_id == team_id)):
            if session.last_attempt_at is not None:
                session.last_attempt_at = session.last_attempt_at - timedelta(seconds=seconds)
        db.commit()


def set_team(team_id: str, **values) -> None:
    with SessionLocal() as db:
        team = db.get(Team, team_id)
        for k, v in values.items():
            setattr(team, k, v)
        db.commit()


def get_team(team_id: str) -> Team:
    with SessionLocal() as db:
        return db.get(Team, team_id)


def get_event(event_id: str) -> Event:
    with SessionLocal() as db:
        return db.get(Event, event_id)


def now():
    return utcnow()
