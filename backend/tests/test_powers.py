"""Help / Attack / Defence (spec section 18)."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.core.timeutil import utcnow
from app.database import SessionLocal
from app.models import Event, PowerUsage
from app.services import power_service
from tests.helpers import get_team, key, play, route_of, scan, seed, set_team, solve_puzzle

API = "/api/v1"


def attack(client, attacker, target):
    return client.post(f"{API}/powers/attack", json={"target_team_id": target["id"], "idempotency_key": key()}, headers=attacker["headers"])


def defend(client, team, usage_id, use_defence):
    return client.post(
        f"{API}/powers/defend",
        json={"usage_id": usage_id, "use_defence": use_defence, "idempotency_key": key()},
        headers=team["headers"],
    )


def buy(client, team, kind, quantity=1):
    return client.post(f"{API}/powers/purchase", json={"kind": kind, "quantity": quantity, "idempotency_key": key()}, headers=team["headers"])


def test_purchase_rules(client):
    demo = seed(client, lock=True)
    team = demo.teams["Dragon Warriors"]
    assert buy(client, team, "ATTACK", -50).status_code == 422  # the old API paid the team for this
    assert buy(client, team, "ATTACK", 0).status_code == 422
    ok = buy(client, team, "ATTACK", 2).json()  # demo teams already own 1; cap is 3
    assert ok["owned"] == 3 and ok["power_points"] == 100 - 2 * 30
    over = buy(client, team, "ATTACK", 1)
    assert over.status_code == 409 and "at most" in over.json()["detail"]
    client.post(f"{API}/admin/events/{demo.event_id}/start", headers=demo.admin)
    closed = buy(client, team, "DEFENCE", 1)
    assert closed.status_code == 409 and "closed" in closed.json()["detail"]


def test_attack_defended_consumes_both_powers(client):
    demo = seed(client, start=True)
    a, t = demo.teams["Dragon Warriors"], demo.teams["Border Runners"]
    res = attack(client, a, t).json()
    state = client.get(f"{API}/me/state", headers=t["headers"]).json()
    assert state["incoming_attack"]["usage_id"] == res["usage_id"]
    assert "Dragon" not in str(state["incoming_attack"])  # attacker stays anonymous
    out = defend(client, t, res["usage_id"], True).json()
    assert out["status"] == "CANCELLED"
    state = client.get(f"{API}/me/state", headers=t["headers"]).json()
    assert state["team"]["status"] != "FROZEN"
    inv = {p["kind"]: p["remaining"] for p in state["powers"]["items"]}
    assert inv["DEFENCE"] == 0
    a_inv = {p["kind"]: p["remaining"] for p in client.get(f"{API}/me/state", headers=a["headers"]).json()["powers"]["items"]}
    assert a_inv["ATTACK"] == 0


def test_accepted_attack_freezes_and_blocks_everything(client):
    demo = seed(client, start=True)
    a, t = demo.teams["Dragon Warriors"], demo.teams["Border Runners"]
    route = route_of(t["id"])
    scan(client, t, route[0].qr_token)  # target is mid-puzzle when frozen
    usage = attack(client, a, t).json()["usage_id"]
    assert defend(client, t, usage, False).json()["status"] == "CONFIRMED"

    state = client.get(f"{API}/me/state", headers=t["headers"]).json()
    assert state["team"]["status"] == "FROZEN" and state["team"]["frozen_until"]
    assert state["team"]["base_status"] == "PUZZLE_LOCKED"  # the lock survives the freeze
    assert scan(client, t, route[0].qr_token).status_code == 409
    # The old API let a frozen team unfreeze itself by answering any puzzle.
    assert play(client, t, {"answer": "anything"}).status_code == 409
    radar = client.get(f"{API}/radar", params={"lat": 13.08, "lng": 80.27}, headers=t["headers"]).json()
    assert radar["locked"] and "FROZEN" in radar["reason"]
    assert attack(client, demo.teams["Joker's Wild"], t).status_code == 409  # can't pile on a frozen team

    set_team(t["id"], frozen_until=utcnow() - timedelta(seconds=1))  # time passes
    assert solve_puzzle(client, t).json()["correct"] is True


def test_unanswered_attack_expires_into_freeze(client):
    demo = seed(client, start=True)
    a, t = demo.teams["Joker's Wild"], demo.teams["Queen's Gambit"]
    usage_id = attack(client, a, t).json()["usage_id"]
    with SessionLocal() as db:
        usage = db.get(PowerUsage, usage_id)
        usage.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    with SessionLocal() as db:  # what the background sweeper does every second
        assert power_service.expire_due_attacks(db, db.get(Event, demo.event_id), utcnow()) == 1
        assert power_service.expire_due_attacks(db, db.get(Event, demo.event_id), utcnow()) == 0
    assert get_team(t["id"]).frozen_until > utcnow()
    late = defend(client, t, usage_id, True).json()
    assert late["status"] == "EXPIRED"  # the old API accepted a defence an hour late


def test_attack_rules(client):
    demo = seed(client, start=True)
    a, t = demo.teams["Heart Breakers"], demo.teams["Spade Squad"]
    assert "own team" in attack(client, a, a).json()["detail"]
    assert attack(client, a, t).status_code == 200
    second = attack(client, demo.teams["Dragon Warriors"], t)
    assert second.status_code == 409 and "already responding" in second.json()["detail"]
    empty = attack(client, a, demo.teams["Border Runners"])
    assert empty.status_code == 409 and "no Attack power" in empty.json()["detail"]


def test_defend_without_defence_power(client):
    demo = seed(client, start=True)
    a, t = demo.teams["Heart Breakers"], demo.teams["Spade Squad"]
    with SessionLocal() as db:
        from app.models import TeamPower

        tp = db.scalar(select(TeamPower).where(TeamPower.team_id == t["id"], TeamPower.kind == "DEFENCE"))
        tp.used = tp.owned
        db.commit()
    usage = attack(client, a, t).json()["usage_id"]
    res = defend(client, t, usage, True)
    assert res.status_code == 409 and "no Defence" in res.json()["detail"]


def test_help_flow(client):
    demo = seed(client, start=True)
    team = demo.teams["Dragon Warriors"]
    res = client.post(f"{API}/powers/help", json={"message": "stuck at the library", "idempotency_key": key()}, headers=team["headers"])
    assert res.status_code == 200 and res.json()["status"] == "PENDING"
    dup = client.post(f"{API}/powers/help", json={"idempotency_key": key()}, headers=team["headers"])
    assert dup.status_code == 409  # one open request at a time
    queue = client.get(f"{API}/admin/events/{demo.event_id}/help", headers=demo.admin).json()
    help_id = queue[0]["id"]
    assert queue[0]["message"] == "stuck at the library"
    for status in ("ACKNOWLEDGED", "RESOLVED"):
        r = client.post(f"{API}/admin/events/{demo.event_id}/help/{help_id}", json={"status": status}, headers=demo.admin)
        assert r.status_code == 200
        assert client.get(f"{API}/me/state", headers=team["headers"]).json()["help"]["status"] == status
    again = client.post(f"{API}/powers/help", json={"idempotency_key": key()}, headers=team["headers"])
    assert again.status_code == 409 and "no Help power" in again.json()["detail"]
