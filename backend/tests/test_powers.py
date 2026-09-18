"""Powers (spec section 18): Guide; Freeze / Jam / Trap; Shield / Reflect / Ward."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.core.timeutil import utcnow
from app.database import SessionLocal
from app.models import Event, PowerUsage, TeamPower
from app.services import power_service
from tests.helpers import clear_checkpoint, get_team, key, play, route_of, scan, seed, set_team, solve_puzzle

API = "/api/v1"
ATTACKS = ("FREEZE", "JAM", "TRAP")
DEFENCES = ("SHIELD", "REFLECT", "WARD")


def attack(client, attacker, target, kind="FREEZE"):
    return client.post(f"{API}/powers/attack", json={"kind": kind, "target_team_id": target["id"], "idempotency_key": key()}, headers=attacker["headers"])


def defend(client, team, usage_id, defence):
    """defence: SHIELD, REFLECT or None (accept)."""
    return client.post(
        f"{API}/powers/defend",
        json={"usage_id": usage_id, "defence": defence, "idempotency_key": key()},
        headers=team["headers"],
    )


def buy(client, team, kind, quantity=1):
    return client.post(f"{API}/powers/purchase", json={"kind": kind, "quantity": quantity, "idempotency_key": key()}, headers=team["headers"])


def use(client, team, power):  # guide / ward
    return client.post(f"{API}/powers/{power}", json={"idempotency_key": key()}, headers=team["headers"])


def state(client, team):
    return client.get(f"{API}/me/state", headers=team["headers"]).json()


def inventory(client, team):
    return {p["kind"]: p["remaining"] for p in state(client, team)["powers"]["items"]}


def drain(team_id, kind):
    with SessionLocal() as db:
        tp = db.scalar(select(TeamPower).where(TeamPower.team_id == team_id, TeamPower.kind == kind))
        tp.used = tp.owned
        db.commit()


def radar(client, team):
    return client.get(f"{API}/radar", params={"lat": 13.08, "lng": 80.27}, headers=team["headers"]).json()


# --- shop ----------------------------------------------------------------------


def test_catalogue_and_purchase_rules(client):
    demo = seed(client, lock=True)
    team = demo.teams["Dragon Warriors"]
    items = {p["kind"]: p for p in state(client, team)["powers"]["items"]}
    assert set(items) == {"GUIDE", *ATTACKS, *DEFENCES}
    assert {k: v["family"] for k, v in items.items()} == {
        "GUIDE": "HELP", "FREEZE": "ATTACK", "JAM": "ATTACK", "TRAP": "ATTACK", "SHIELD": "DEFENCE", "REFLECT": "DEFENCE", "WARD": "DEFENCE",
    }
    assert items["TRAP"]["cost"] == 40 and items["TRAP"]["max_per_team"] == 1 and items["JAM"]["cost"] == 20
    assert buy(client, team, "FREEZE", -50).status_code == 422  # the old API paid the team for this
    assert buy(client, team, "FREEZE", 0).status_code == 422
    assert buy(client, team, "HELP", 1).status_code == 422  # the old kinds are gone
    ok = buy(client, team, "FREEZE", 2).json()  # demo teams already own 1; cap is 3
    assert ok["owned"] == 3 and ok["power_points"] == 100 - 2 * 30
    over = buy(client, team, "FREEZE", 1)
    assert over.status_code == 409 and "at most" in over.json()["detail"]
    full = buy(client, team, "TRAP", 1)  # demo teams own 1, cap is 1
    assert full.status_code == 409 and "at most" in full.json()["detail"]
    client.post(f"{API}/admin/events/{demo.event_id}/start", headers=demo.admin)
    closed = buy(client, team, "SHIELD", 1)
    assert closed.status_code == 409 and "closed" in closed.json()["detail"]


# --- attack lifecycle ------------------------------------------------------------


def test_attack_shielded_consumes_both_powers(client):
    demo = seed(client, start=True)
    a, t = demo.teams["Dragon Warriors"], demo.teams["Border Runners"]
    res = attack(client, a, t, "FREEZE").json()
    assert res["kind"] == "FREEZE" and res["status"] == "PENDING"
    s = state(client, t)
    assert s["incoming_attack"]["usage_id"] == res["usage_id"] and s["incoming_attack"]["kind"] == "FREEZE"
    assert "60s" in s["incoming_attack"]["effect"]  # the demo event freezes for 60 s
    assert "Dragon" not in str(s["incoming_attack"])  # attacker stays anonymous
    out = defend(client, t, res["usage_id"], "SHIELD").json()
    assert out["status"] == "CANCELLED" and out["resolved_with"] == "SHIELD"
    assert state(client, t)["team"]["status"] != "FROZEN"
    assert inventory(client, t)["SHIELD"] == 0
    assert inventory(client, a)["FREEZE"] == 0
    mine = state(client, a)["outgoing_attacks"][0]
    assert mine["kind"] == "FREEZE" and mine["resolved_with"] == "SHIELD"


def test_accepted_freeze_blocks_everything(client):
    demo = seed(client, start=True)
    a, t = demo.teams["Dragon Warriors"], demo.teams["Border Runners"]
    route = route_of(t["id"])
    scan(client, t, route[0].qr_token)  # target is mid-puzzle when frozen
    usage = attack(client, a, t, "FREEZE").json()["usage_id"]
    assert defend(client, t, usage, None).json()["status"] == "CONFIRMED"

    s = state(client, t)
    assert s["team"]["status"] == "FROZEN" and s["team"]["frozen_until"]
    assert s["team"]["base_status"] == "PUZZLE_LOCKED"  # the lock survives the freeze
    assert scan(client, t, route[0].qr_token).status_code == 409
    # The old API let a frozen team unfreeze itself by answering any puzzle.
    assert play(client, t, {"answer": "anything"}).status_code == 409
    assert radar(client, t)["locked"] and "FROZEN" in radar(client, t)["reason"]
    assert use(client, t, "guide").status_code == 409  # frozen: no guide either
    assert attack(client, demo.teams["Joker's Wild"], t, "FREEZE").status_code == 409  # can't pile on a frozen team

    set_team(t["id"], frozen_until=utcnow() - timedelta(seconds=1))  # time passes
    assert solve_puzzle(client, t).json()["correct"] is True


def test_jam_blacks_out_the_radar_but_not_the_scanner(client):
    demo = seed(client, start=True)
    a, t = demo.teams["Dragon Warriors"], demo.teams["Border Runners"]
    usage = attack(client, a, t, "JAM").json()["usage_id"]
    assert defend(client, t, usage, None).json()["status"] == "CONFIRMED"
    s = state(client, t)
    assert s["team"]["status"] == "ACTIVE" and s["team"]["jammed_until"]  # not frozen
    r = radar(client, t)
    assert r["locked"] and r.get("jammed") and "JAMMED" in r["reason"]
    assert clear_checkpoint(client, t, route_of(t["id"])[0]) is None  # scanning and solving still work
    assert attack(client, demo.teams["Joker's Wild"], t, "JAM").status_code == 409  # already jammed
    assert attack(client, demo.teams["Joker's Wild"], t, "FREEZE").status_code == 200  # a different attack is fine
    set_team(t["id"], jammed_until=utcnow() - timedelta(seconds=1))
    assert state(client, t)["team"]["jammed_until"] is None


def test_trap_plants_a_foul(client):
    demo = seed(client, start=True)
    a, t = demo.teams["Dragon Warriors"], demo.teams["Border Runners"]
    usage = attack(client, a, t, "TRAP").json()["usage_id"]
    assert defend(client, t, usage, None).json()["status"] == "CONFIRMED"
    assert state(client, t)["team"]["foul_count"] == 1
    assert state(client, t)["team"]["status"] == "ACTIVE"
    game_log = client.get(f"{API}/admin/events/{demo.event_id}/logs", params={"log": "game"}, headers=demo.admin).json()
    assert "TEAM_TRAPPED" in {r["kind"] for r in game_log}


def test_reflect_bounces_the_attack_onto_the_attacker(client):
    demo = seed(client, start=True)
    a, t = demo.teams["Dragon Warriors"], demo.teams["Border Runners"]
    usage = attack(client, a, t, "FREEZE").json()["usage_id"]
    out = defend(client, t, usage, "REFLECT").json()
    assert out["status"] == "CANCELLED" and out["resolved_with"] == "REFLECT"
    assert state(client, t)["team"]["status"] == "ACTIVE"  # the target is untouched
    sa = state(client, a)
    assert sa["team"]["status"] == "FROZEN"  # the attacker eats their own freeze
    assert sa["incoming_attack"] is None  # ...and can't defend against it
    assert inventory(client, t)["REFLECT"] == 0
    # A reflected Trap fouls the attacker instead.
    b, c = demo.teams["Joker's Wild"], demo.teams["Queen's Gambit"]
    usage = attack(client, b, c, "TRAP").json()["usage_id"]
    assert defend(client, c, usage, "REFLECT").json()["resolved_with"] == "REFLECT"
    assert get_team(b["id"]).foul_count == 1 and get_team(c["id"]).foul_count == 0


def test_ward_blocks_attacks_without_a_prompt(client):
    demo = seed(client, start=True)
    a, t = demo.teams["Dragon Warriors"], demo.teams["Border Runners"]
    up = use(client, t, "ward").json()
    assert up["warded_until"] and inventory(client, t)["WARD"] == 0
    assert use(client, t, "ward").status_code == 409  # already up
    res = attack(client, a, t, "JAM").json()
    assert res["status"] == "CANCELLED" and res["resolved_with"] == "WARD" and "Ward" in res["message"]
    assert inventory(client, a)["JAM"] == 0  # the attacker still spent it
    assert state(client, t)["incoming_attack"] is None and state(client, t)["team"]["jammed_until"] is None
    set_team(t["id"], warded_until=utcnow() - timedelta(seconds=1))
    assert attack(client, a, t, "FREEZE").json()["status"] == "PENDING"  # ward gone: a normal attack


def test_unanswered_attack_expires_into_its_effect(client):
    demo = seed(client, start=True)
    a, t = demo.teams["Joker's Wild"], demo.teams["Queen's Gambit"]
    usage_id = attack(client, a, t, "JAM").json()["usage_id"]
    with SessionLocal() as db:
        usage = db.get(PowerUsage, usage_id)
        usage.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    with SessionLocal() as db:  # what the background sweeper does every second
        assert power_service.expire_due_attacks(db, db.get(Event, demo.event_id), utcnow()) == 1
        assert power_service.expire_due_attacks(db, db.get(Event, demo.event_id), utcnow()) == 0
    assert get_team(t["id"]).jammed_until > utcnow()
    late = defend(client, t, usage_id, "SHIELD").json()
    assert late["status"] == "EXPIRED" and late["resolved_with"] == "TIMEOUT"  # the old API accepted a defence an hour late


def test_attack_rules(client):
    demo = seed(client, start=True)
    a, t = demo.teams["Heart Breakers"], demo.teams["Spade Squad"]
    assert "own team" in attack(client, a, a).json()["detail"]
    assert attack(client, a, t, "FREEZE").status_code == 200
    second = attack(client, demo.teams["Dragon Warriors"], t, "TRAP")
    assert second.status_code == 409 and "already responding" in second.json()["detail"]
    empty = attack(client, a, demo.teams["Border Runners"], "FREEZE")
    assert empty.status_code == 409 and "no Freeze power" in empty.json()["detail"]
    assert attack(client, a, t, "SHIELD").status_code == 422  # not an attack
    assert attack(client, a, t, "ATTACK").status_code == 422  # the old kind


def test_defend_without_the_named_power(client):
    demo = seed(client, start=True)
    a, t = demo.teams["Heart Breakers"], demo.teams["Spade Squad"]
    drain(t["id"], "REFLECT")
    usage = attack(client, a, t).json()["usage_id"]
    res = defend(client, t, usage, "REFLECT")
    assert res.status_code == 409 and "no Reflect" in res.json()["detail"]
    assert defend(client, t, usage, "WARD").status_code == 422  # a Ward is raised in advance, not answered with
    assert defend(client, t, usage, "SHIELD").json()["status"] == "CANCELLED"  # still pending: the Shield works


# --- guide ------------------------------------------------------------------------


def test_guide_reveals_the_target_with_a_maps_route(client):
    demo = seed(client, start=True)
    team = demo.teams["Dragon Warriors"]
    route = route_of(team["id"])
    before = radar(client, team)
    assert before["guided"] is False and "target" not in before and before["distance_m"] % 5 == 0
    res = use(client, team, "guide").json()
    assert res["guide_until"] and inventory(client, team)["GUIDE"] == 0
    assert use(client, team, "guide").status_code == 409  # already active
    r = radar(client, team)
    assert r["guided"] is True and r["target"]["name"] == route[0].name
    assert r["target"]["latitude"] == route[0].latitude and r["target"]["longitude"] == route[0].longitude
    assert r["target"]["maps_url"].startswith("https://www.google.com/maps/dir/?api=1&destination=") and "travelmode=walking" in r["target"]["maps_url"]
    assert isinstance(r["distance_m"], int) and r["distance_m"] > 0  # exact, not rounded away
    assert state(client, team)["team"]["guide_until"] == res["guide_until"]
    # A Guide cuts through a jam.
    set_team(team["id"], jammed_until=utcnow() + timedelta(minutes=5))
    assert radar(client, team)["guided"] is True
    # Scanning the checkpoint ends it: the next target is hidden again.
    clear_checkpoint(client, team, route[0])
    assert radar(client, team)["locked"] and radar(client, team)["jammed"]  # the jam is back in force
    set_team(team["id"], jammed_until=None)
    after = radar(client, team)
    assert after["guided"] is False and "target" not in after
    assert state(client, team)["team"]["guide_until"] is None


def test_guide_needs_an_open_radar(client):
    demo = seed(client, start=True)
    team = demo.teams["Dragon Warriors"]
    scan(client, team, route_of(team["id"])[0].qr_token)  # now on a puzzle
    res = use(client, team, "guide")
    assert res.status_code == 409 and "puzzle" in res.json()["detail"].lower()
    solve_puzzle(client, team)
    assert use(client, team, "guide").status_code == 200
    assert use(client, demo.teams["Border Runners"], "help").status_code == 404  # the old endpoint is gone


def test_results_count_powers_by_family(client):
    demo = seed(client, start=True)
    a, t = demo.teams["Dragon Warriors"], demo.teams["Border Runners"]
    use(client, a, "guide")
    usage = attack(client, a, t, "JAM").json()["usage_id"]
    defend(client, t, usage, "SHIELD")
    use(client, t, "ward")
    client.post(f"{API}/admin/events/{demo.event_id}/end", headers=demo.admin)
    rows = {r["team_name"]: r for r in client.get(f"{API}/admin/events/{demo.event_id}/results", headers=demo.admin).json()["coordinator"]}
    assert (rows["Dragon Warriors"]["attacks_used"], rows["Dragon Warriors"]["guides_used"]) == (1, 1)
    assert rows["Border Runners"]["defences_used"] == 2  # the Shield and the Ward
    assert client.get(f"{API}/admin/events/{demo.event_id}/help", headers=demo.admin).status_code == 404
