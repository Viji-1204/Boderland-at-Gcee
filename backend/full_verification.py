"""End-to-end smoke run of a whole Round 2 event through the real HTTP API.

    cd backend
    python full_verification.py

It runs against a TEMPORARY database (never backend/data/round2.db) and
prints what happened. The old version of this script re-seeded - i.e. wiped -
whatever database it found. To smoke-test Postgres instead, set
SMOKE_DATABASE_URL to an EMPTY throwaway database.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

TMP = pathlib.Path(tempfile.mkdtemp(prefix="round2-smoke-"))
os.environ["DATABASE_URL"] = os.environ.get("SMOKE_DATABASE_URL") or f"sqlite:///{(TMP / 'smoke.db').as_posix()}"
os.environ["AUTO_MIGRATE"] = "true"
os.environ["SEED_DEMO"] = "true"
os.environ["ENVIRONMENT"] = "development"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core import ratelimit  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Location, PuzzleSession, RouteStop  # noqa: E402
from app.seed import DEMO_TEAMS  # noqa: E402
from app.services import puzzles, scan_service  # noqa: E402
from app.services.puzzles import rps, tictactoe  # noqa: E402

API = "/api/v1"
scan_service._scan_limiter = ratelimit.MinInterval(0)  # the script is faster than any human
scan_service._radar_limiter = ratelimit.MinInterval(0)
# The two games are luck/skill against the server; make the computer lose so
# the run is repeatable (only in this script).
rps.computer_throw = lambda rng: "scissors"
tictactoe.ai_move = lambda board, rng: max(i for i, ch in enumerate(board) if ch == ".")
step = 0


def ok(message: str) -> None:
    global step
    step += 1
    print(f"  [{step:02d}] OK  {message}")


def expect(condition: bool, message: str) -> None:
    if not condition:
        print(f"  FAILED: {message}")
        sys.exit(1)
    ok(message)


def route(team_id: str) -> list[Location]:
    with SessionLocal() as db:
        stops = db.query(RouteStop).filter(RouteStop.team_id == team_id).order_by(RouteStop.seq).all()
        return [db.get(Location, s.location_id) for s in stops]


def main() -> None:
    where = os.environ["DATABASE_URL"].split("@")[-1] if "@" in os.environ["DATABASE_URL"] else f"temporary database in {TMP}"
    print(f"Round 2 smoke run ({where})\n")
    n = 0
    with TestClient(app) as client:
        admin_token = client.post(f"{API}/auth/admin/login", json={"username": "admin", "password": "admin123"}).json()["access_token"]
        admin = {"Authorization": f"Bearer {admin_token}"}
        event = client.get(f"{API}/admin/events", headers=admin).json()[0]
        eid = event["id"]
        expect(event["status"] == "DRAFT", f"demo event seeded: {event['name']}")

        client.patch(f"{API}/admin/events/{eid}", json={"settings": {"puzzle_cooldown_s": 0, "staggered_start_offset_s": 0}}, headers=admin)
        checks = client.get(f"{API}/admin/events/{eid}/readiness", headers=admin).json()
        expect(all(c["ok"] for c in checks), f"readiness checklist all green ({len(checks)} checks)")

        teams = {}
        for code, name, _leader, phone, _sentence in DEMO_TEAMS:
            res = client.post(f"{API}/auth/team/login", json={"team_code": code, "password": phone[:4]}).json()
            teams[name] = {"id": res["team_id"], "h": {"Authorization": f"Bearer {res['access_token']}"}}
        expect(len(teams) == 6, "all 6 teams log in with Round 1-style code + phone password")

        expect(client.post(f"{API}/admin/events/{eid}/lock", headers=admin).status_code == 200, "configuration locked")
        expect(client.post(f"{API}/admin/events/{eid}/start", headers=admin).status_code == 200, "event LIVE")

        dragon, runners = teams["Dragon Warriors"], teams["Border Runners"]
        attack = client.post(f"{API}/powers/attack", json={"target_team_id": runners["id"]}, headers=dragon["h"]).json()
        defended = client.post(f"{API}/powers/defend", json={"usage_id": attack["usage_id"], "use_defence": True}, headers=runners["h"]).json()
        expect(defended["status"] == "CANCELLED", "attack blocked with a Defence power")

        played = []
        for loc in route(dragon["id"]):
            n += 1
            res = client.post(f"{API}/scan", json={"code": loc.qr_token}, headers=dragon["h"]).json()
            assert res["result"] == "VALID", res
            with SessionLocal() as db:
                session = db.scalar(select(PuzzleSession).where(PuzzleSession.team_id == dragon["id"], PuzzleSession.location_id == loc.id))
            for move in puzzles.BY_KIND[session.kind].solution(session.state):
                reply = client.post(f"{API}/puzzle/play", json=move, headers=dragon["h"]).json()
            assert reply["solved"], reply
            played.append(puzzles.label(session.kind))
        state = client.get(f"{API}/me/state", headers=dragon["h"]).json()
        expect(state["team"]["status"] == "FINAL", f"Dragon Warriors cleared all {n} checkpoints: {', '.join(played)}")
        expect(" ".join(f["text"] for f in state["fragments"]).startswith("ONLY THE BRAVE"), "sentence assembled in route order")

        client.post(f"{API}/admin/events/{eid}/teams/{dragon['id']}/verify-joker", headers=admin)
        client.post(f"{API}/admin/events/{eid}/end", headers=admin)
        public = client.get(f"{API}/results/public", headers=dragon["h"]).json()["rows"]
        expect(public[0]["team_name"] == "Dragon Warriors" and "foul_count" not in public[0], "public results ranked, fouls hidden")
        export = client.get(f"{API}/admin/events/{eid}/results/export", headers=admin)
        expect(export.status_code == 200 and export.content[:2] == b"PK", "coordinator results exported as .xlsx")
    print("\nAll good.")


if __name__ == "__main__":
    main()
