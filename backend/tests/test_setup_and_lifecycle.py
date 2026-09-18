"""Route generation rules, readiness, lifecycle, coordinator controls, results."""
from __future__ import annotations

import random
from datetime import timedelta

from sqlalchemy import select

from app.core.timeutil import utcnow
from app.database import SessionLocal
from app.models import AdminAction, GameEvent, Team
from app.services import route_service
from app.services.event_service import split_sentence
from tests.helpers import clear_checkpoint, face_cards_of, get_event, get_team, route_of, scan, seed, set_team

API = "/api/v1"


def test_route_capacity_math():
    locs = [object() for _ in range(7)]
    assert route_service.start_capacity(7) == 720  # 6!
    summary = route_service.capacity_summary(locs, 6)
    assert summary["feasible"] is True and summary["unique_routes"] == 5040 and summary["starting_points"] == 7
    summary = route_service.capacity_summary(locs, 6000)
    assert summary["feasible"] is False and "reduce the team count" in summary["message"]


def test_face_cards_are_dealt_in_order():
    rng = random.Random(7)
    for _ in range(200):
        faces = route_service.deal_face_cards(8, rng)
        assert len(faces) == 8 and route_service.face_cards_ok(faces)
    assert not route_service.face_cards_ok(["QUEEN", "JACK", "KING", None])
    assert not route_service.face_cards_ok(["JACK", "QUEEN", None])
    assert not route_service.face_cards_ok(["JACK", "JACK", "QUEEN", "KING"])


def test_generated_routes_follow_every_rule(client):
    demo = seed(client)
    routes = {name: route_of(t["id"]) for name, t in demo.teams.items()}
    selected = {l.id for l in next(iter(routes.values()))}
    assert len(selected) == 8
    seen = set()
    for route in routes.values():
        assert {l.id for l in route} == selected and len(route) == 8
        seen.add(tuple(l.id for l in route))
    assert len(seen) == len(routes)  # unique
    starts = [r[0].id for r in routes.values()]
    assert len(set(starts)) == len(starts)  # 6 teams, 8 starts -> all different
    # Every team holds its own Jack, Queen and King, met in that order.
    for name, team in demo.teams.items():
        cards = face_cards_of(team["id"])
        assert set(cards) == {"JACK", "QUEEN", "KING"}, name
        order = [l.id for l in routes[name]]
        assert order.index(cards["JACK"]) < order.index(cards["QUEEN"]) < order.index(cards["KING"]), name


def test_face_cards_differ_between_teams(client):
    """The cards are dealt per team: with 6 teams and 8 stops, at least two
    teams must hold the Jack at different checkpoints. (The chance that all
    six draws agree on a stop is 8^-5 - never in practice.)"""
    demo = seed(client)
    jacks = {face_cards_of(t["id"])["JACK"] for t in demo.teams.values()}
    assert len(jacks) > 1


def test_shared_starts_get_staggered_offsets(client):
    demo = seed(client, settings={"staggered_start_offset_s": 90})
    team_ids = [t["id"] for t in demo.teams.values()]
    # Force two teams onto the same start via a manual route edit.
    a, b = team_ids[0], team_ids[1]
    route_b = route_of(b)
    route_a = route_of(a)
    new_a = [route_b[0].id] + [l.id for l in route_a if l.id != route_b[0].id]
    # Cards follow the checkpoints they were on; put them back in visit order.
    cards = face_cards_of(a)
    holders = sorted(cards.values(), key=new_a.index)
    face_cards = dict(zip(("JACK", "QUEEN", "KING"), holders))
    res = client.put(f"{API}/admin/events/{demo.event_id}/teams/{a}/route", json={"location_ids": new_a, "face_cards": face_cards}, headers=demo.admin)
    assert res.status_code == 200, res.text
    offsets = sorted([get_team(a).start_offset_s, get_team(b).start_offset_s])
    assert offsets == [0, 90]


def test_manual_route_validation(client):
    demo = seed(client)
    team_id = demo.teams["Dragon Warriors"]["id"]
    other = route_of(demo.teams["Border Runners"]["id"])
    dup = client.put(f"{API}/admin/events/{demo.event_id}/teams/{team_id}/route", json={"location_ids": [l.id for l in other]}, headers=demo.admin)
    assert dup.status_code == 409 and "unique" in dup.json()["detail"]
    route = route_of(team_id)
    ids = [l.id for l in route]
    short = client.put(f"{API}/admin/events/{demo.event_id}/teams/{team_id}/route", json={"location_ids": ids[:-1]}, headers=demo.admin)
    assert short.status_code == 400
    cards = face_cards_of(team_id)
    swapped = {"JACK": cards["KING"], "QUEEN": cards["QUEEN"], "KING": cards["JACK"]}
    bad = client.put(f"{API}/admin/events/{demo.event_id}/teams/{team_id}/route", json={"location_ids": ids, "face_cards": swapped}, headers=demo.admin)
    assert bad.status_code == 400 and "order" in bad.json()["detail"]
    same = {"JACK": cards["JACK"], "QUEEN": cards["JACK"], "KING": cards["KING"]}
    bad = client.put(f"{API}/admin/events/{demo.event_id}/teams/{team_id}/route", json={"location_ids": ids, "face_cards": same}, headers=demo.admin)
    assert bad.status_code == 400 and "own checkpoint" in bad.json()["detail"]
    # Without face_cards the team keeps its cards where they were...
    reversed_ids = ids[::-1]
    ok = client.put(f"{API}/admin/events/{demo.event_id}/teams/{team_id}/route", json={"location_ids": reversed_ids}, headers=demo.admin)
    assert ok.status_code == 400 and "order" in ok.json()["detail"]  # ...which is now the wrong way round
    ok = client.put(f"{API}/admin/events/{demo.event_id}/teams/{team_id}/route", json={"location_ids": ids}, headers=demo.admin)
    assert ok.status_code == 200 and face_cards_of(team_id) == cards
    stops = next(t for t in ok.json()["teams"] if t["team_id"] == team_id)["stops"]
    assert [s["face_card"] for s in stops if s["face_card"]] == ["JACK", "QUEEN", "KING"]


def test_readiness_and_lock_requirements(client):
    demo = seed(client)
    checks = client.get(f"{API}/admin/events/{demo.event_id}/readiness", headers=demo.admin).json()
    assert all(c["ok"] for c in checks), checks
    team_id = demo.teams["Spade Squad"]["id"]
    client.patch(f"{API}/admin/events/{demo.event_id}/teams/{team_id}", json={"sentence": "TOO SHORT"}, headers=demo.admin)
    res = client.post(f"{API}/admin/events/{demo.event_id}/lock", headers=demo.admin)
    assert res.status_code == 409 and "sentence" in res.json()["detail"].lower()
    assert get_event(demo.event_id).status == "DRAFT"


def test_split_sentence():
    assert split_sentence("A B C D E F G H I J", 8) == ["A B", "C D", "E", "F", "G", "H", "I", "J"]
    assert split_sentence("ONE | TWO THREE | FOUR", 3) == ["ONE", "TWO THREE", "FOUR"]
    assert split_sentence("ONE | TWO", 3) is None
    assert split_sentence("TOO SHORT", 8) is None


def test_lifecycle_transitions_are_guarded(client):
    demo = seed(client)
    eid = demo.event_id
    assert client.post(f"{API}/admin/events/{eid}/start", headers=demo.admin).status_code == 409  # must lock first
    assert client.post(f"{API}/admin/events/{eid}/lock", headers=demo.admin).status_code == 200
    assert client.post(f"{API}/admin/events/{eid}/unlock", headers=demo.admin).status_code == 200
    assert client.post(f"{API}/admin/events/{eid}/lock", headers=demo.admin).status_code == 200
    assert client.post(f"{API}/admin/events/{eid}/start", headers=demo.admin).status_code == 200
    again = client.post(f"{API}/admin/events/{eid}/start", headers=demo.admin)
    assert again.status_code == 409  # the old API reset every start time here
    # setup is frozen while live
    team_id = demo.teams["Spade Squad"]["id"]
    assert client.post(f"{API}/admin/events/{eid}/routes/generate", headers=demo.admin).status_code == 409
    assert client.post(f"{API}/admin/events/{eid}/teams", json={"team_name": "Late", "password": "1234"}, headers=demo.admin).status_code == 409
    assert client.patch(f"{API}/admin/events/{eid}/teams/{team_id}", json={"sentence": "x"}, headers=demo.admin).status_code == 409
    assert client.post(f"{API}/admin/events/{eid}/end", headers=demo.admin).status_code == 200
    assert client.post(f"{API}/admin/events/{eid}/pause", headers=demo.admin).status_code == 409


def test_resume_gives_back_paused_time(client):
    demo = seed(client, start=True)
    team_id = demo.teams["Dragon Warriors"]["id"]
    before = get_team(team_id).started_at
    client.post(f"{API}/admin/events/{demo.event_id}/pause", headers=demo.admin)
    from app.models import Event

    with SessionLocal() as db:  # pretend the pause lasted 10 minutes
        ev = db.get(Event, demo.event_id)
        ev.paused_at = utcnow() - timedelta(minutes=10)
        db.commit()
    client.post(f"{API}/admin/events/{demo.event_id}/resume", headers=demo.admin)
    shift = (get_team(team_id).started_at - before).total_seconds()
    assert 590 <= shift <= 610


def test_coordinator_controls_are_audited(client):
    demo = seed(client, start=True)
    eid, team = demo.event_id, demo.teams["Border Runners"]
    base = f"{API}/admin/events/{eid}/teams/{team['id']}"
    assert client.post(f"{base}/foul", json={"action": "add", "reason": "cut through the garden"}, headers=demo.admin).json()["foul_count"] == 1
    assert client.post(f"{base}/foul", json={"action": "remove", "reason": "disputed"}, headers=demo.admin).json()["foul_count"] == 0
    assert client.post(f"{base}/foul", json={"action": "remove"}, headers=demo.admin).status_code == 409
    assert client.post(f"{base}/freeze", json={"duration_s": 60}, headers=demo.admin).json()["frozen_until"]
    assert client.post(f"{base}/unfreeze", headers=demo.admin).status_code == 200
    scan(client, team, route_of(team["id"])[0].qr_token)
    assert client.post(f"{base}/unlock-puzzle", json={"reason": "prop missing"}, headers=demo.admin).json()["status"] == "ACTIVE"
    assert client.post(f"{base}/verify-joker", headers=demo.admin).status_code == 409  # not FINAL yet
    assert client.post(f"{base}/disqualify", json={"reason": "used a car"}, headers=demo.admin).json()["status"] == "DISQUALIFIED"
    assert scan(client, team, route_of(team["id"])[1].qr_token).status_code == 409
    assert client.post(f"{base}/reinstate", headers=demo.admin).json()["status"] == "ACTIVE"

    admin_log = client.get(f"{API}/admin/events/{eid}/logs", params={"log": "admin"}, headers=demo.admin).json()
    kinds = [r["kind"] for r in admin_log]
    for expected in ("FOUL_ADDED", "FOUL_REMOVED", "TEAM_FROZEN", "TEAM_UNFROZEN", "PUZZLE_UNLOCKED", "TEAM_DISQUALIFIED", "TEAM_REINSTATED"):
        assert expected in kinds
    game_log = client.get(f"{API}/admin/events/{eid}/logs", params={"log": "game"}, headers=demo.admin).json()
    assert not {"FOUL_ADDED", "TEAM_DISQUALIFIED"} & {r["kind"] for r in game_log}  # the two logs stay separate


def test_ranking_uses_fouls_then_time(client):
    demo = seed(client, start=True)
    fast_foul, slow_clean = demo.teams["Dragon Warriors"], demo.teams["Border Runners"]
    for team in (fast_foul, slow_clean):
        for loc in route_of(team["id"]):
            clear_checkpoint(client, team, loc)
        client.post(f"{API}/admin/events/{demo.event_id}/teams/{team['id']}/verify-joker", headers=demo.admin)
    now = utcnow()
    set_team(fast_foul["id"], started_at=now - timedelta(minutes=20), completed_at=now, foul_count=2)
    set_team(slow_clean["id"], started_at=now - timedelta(minutes=40), completed_at=now, foul_count=0)
    results = client.get(f"{API}/admin/events/{demo.event_id}/results", headers=demo.admin).json()
    names = [r["team_name"] for r in results["coordinator"]]
    assert names[:2] == ["Border Runners", "Dragon Warriors"]
    assert results["coordinator"][1]["foul_count"] == 2
    assert all("foul_count" not in r for r in results["public"])
    export = client.get(f"{API}/admin/events/{demo.event_id}/results/export", headers=demo.admin)
    assert export.status_code == 200 and export.content[:2] == b"PK"


def test_dashboard_shows_everything_to_coordinators(client):
    demo = seed(client, start=True)
    team = demo.teams["Joker's Wild"]
    scan(client, team, route_of(team["id"])[0].qr_token)
    dash = client.get(f"{API}/admin/events/{demo.event_id}/dashboard", headers=demo.admin).json()
    row = next(r for r in dash["teams"] if r["id"] == team["id"])
    assert row["status"] == "PUZZLE_LOCKED" and row["target"]["code"].startswith("L")
    assert dash["counts"]["teams"] == 6 and dash["recent"]


def test_clone_event_copies_setup_with_fresh_qr_codes(client):
    demo = seed(client)
    res = client.post(f"{API}/admin/events", json={"name": "Round 2 - 2027", "clone_from_event_id": demo.event_id}, headers=demo.admin)
    assert res.status_code == 201
    new_id = res.json()["id"]
    old_locs = {l["code"]: l for l in client.get(f"{API}/admin/events/{demo.event_id}/locations", headers=demo.admin).json()}
    new_locs = {l["code"]: l for l in client.get(f"{API}/admin/events/{new_id}/locations", headers=demo.admin).json()}
    assert set(old_locs) == set(new_locs)
    assert all(old_locs[c]["qr_token"] != new_locs[c]["qr_token"] for c in old_locs)
    assert all(new_locs[c]["puzzle_type"] == old_locs[c]["puzzle_type"] for c in new_locs)
