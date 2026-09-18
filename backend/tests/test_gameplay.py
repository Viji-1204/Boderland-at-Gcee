"""The checkpoint loop: scan -> puzzle -> radar -> ... -> Joker -> results."""
from __future__ import annotations

from datetime import timedelta

from app.services import puzzles
from tests.helpers import (
    answer,
    backdate_attempts,
    clear_checkpoint,
    get_team,
    key,
    now,
    play,
    puzzle_answer,
    route_of,
    scan,
    seed,
    set_team,
    solve_puzzle,
)

API = "/api/v1"


def test_state_before_start_shows_waiting_and_no_route_names(client):
    demo = seed(client, lock=True)
    team = demo.teams["Dragon Warriors"]
    state = client.get(f"{API}/me/state", headers=team["headers"]).json()
    assert state["event"]["status"] == "CONFIGURED"
    assert state["team"]["status"] == "WAITING"
    assert len(state["checkpoints"]) == 8
    assert all(cp["name"] is None for cp in state["checkpoints"])  # nothing revealed yet
    res = scan(client, team, route_of(team["id"])[0].qr_token)
    assert res.status_code == 409 and "hasn't started" in res.json()["detail"]


def test_full_route_happy_path_to_results(client):
    demo = seed(client, start=True)
    team = demo.teams["Dragon Warriors"]
    route = route_of(team["id"])

    for i, loc in enumerate(route, start=1):
        res = scan(client, team, loc.qr_token)
        body = res.json()
        assert body["result"] == "VALID" and body["checkpoint"] == i
        assert body["puzzle"]["kind"] == puzzles.kind_for_code(loc.code) and body["puzzle"]["label"]
        assert body["fragment"]["seq"] == i
        radar = client.get(f"{API}/radar", params={"lat": 13.08, "lng": 80.27}, headers=team["headers"]).json()
        assert radar["locked"] and "puzzle" in radar["reason"].lower()
        assert solve_puzzle(client, team).json()["correct"] is True

    state = client.get(f"{API}/me/state", headers=team["headers"]).json()
    assert state["team"]["status"] == "FINAL"
    assert [f["seq"] for f in state["fragments"]] == list(range(1, 9))
    assert " ".join(f["text"] for f in state["fragments"]) == "ONLY THE BRAVE FIND THE JOKER AT DAWN"
    assert all(state["face_cards"][f] for f in ("JACK", "QUEEN", "KING"))
    assert state["event"]["final_location_name"] == "Coordinator's Bench"

    radar = client.get(f"{API}/radar", params={"lat": 13.0827, "lng": 80.2707}, headers=team["headers"]).json()
    assert radar["locked"] is False and radar["is_final"] is True

    res = client.post(f"{API}/admin/events/{demo.event_id}/teams/{team['id']}/verify-joker", headers=demo.admin)
    assert res.status_code == 200, res.text
    assert get_team(team["id"]).status == "COMPLETED"

    client.post(f"{API}/admin/events/{demo.event_id}/end", headers=demo.admin)
    public = client.get(f"{API}/results/public", headers=team["headers"]).json()
    assert public["rows"][0]["team_name"] == "Dragon Warriors"
    assert public["rows"][0]["finished"] is True
    assert all("foul" not in k for row in public["rows"] for k in row)  # never on the public screen


def test_wrong_repeat_and_unknown_codes(client):
    demo = seed(client, start=True)
    team = demo.teams["Border Runners"]
    route = route_of(team["id"])

    unknown = scan(client, team, "https://example.com/some-poster").json()
    assert unknown["result"] == "INVALID" and unknown["foul_added"] is False

    future = scan(client, team, route[3].qr_token).json()
    assert future["result"] == "WRONG_QR" and future["foul_added"] is True
    assert get_team(team["id"]).foul_count == 1

    clear_checkpoint(client, team, route[0])
    repeat = scan(client, team, route[0].qr_token).json()
    assert repeat["result"] == "REPEAT" and repeat["foul_added"] is False
    assert get_team(team["id"]).foul_count == 1


def test_qr_link_form_is_accepted(client):
    demo = seed(client, start=True)
    team = demo.teams["Border Runners"]
    first = route_of(team["id"])[0]
    res = scan(client, team, f"http://localhost:8000/team-app/#/scan?c={first.qr_token}")
    assert res.json()["result"] == "VALID"


def test_puzzle_locked_blocks_other_scans_without_foul(client):
    demo = seed(client, start=True)
    team = demo.teams["Joker's Wild"]
    route = route_of(team["id"])
    assert scan(client, team, route[0].qr_token).json()["result"] == "VALID"
    locked = scan(client, team, route[1].qr_token).json()
    assert locked["result"] == "LOCKED" and locked["foul_added"] is False
    again = scan(client, team, route[0].qr_token).json()
    assert again["result"] == "REPEAT" and again["puzzle"] is not None


def test_moves_need_an_open_puzzle(client):
    demo = seed(client, start=True)
    team = demo.teams["Joker's Wild"]
    res = play(client, team, {"answer": "anything"})
    assert res.status_code == 409 and "no puzzle open" in res.json()["detail"]


def test_wrong_answer_no_penalty_and_cooldown(client, monkeypatch):
    monkeypatch.setattr(puzzles, "kind_for_code", lambda code: "riddle")
    demo = seed(client, start=True, settings={"puzzle_cooldown_s": 5})
    team = demo.teams["Queen's Gambit"]
    scan(client, team, route_of(team["id"])[0].qr_token)
    first = answer(client, team, "definitely wrong")
    assert first.status_code == 200 and first.json()["correct"] is False and first.json()["retry_after_s"] == 5
    assert get_team(team["id"]).foul_count == 0
    too_fast = answer(client, team, puzzle_answer(team["id"]))
    assert too_fast.status_code == 429 and too_fast.json()["retry_after_s"] > 0
    backdate_attempts(team["id"], 30)
    assert answer(client, team, puzzle_answer(team["id"])).json()["correct"] is True


def test_answer_normalisation(client, monkeypatch):
    monkeypatch.setattr(puzzles, "kind_for_code", lambda code: "scramble")
    demo = seed(client, start=True)
    team = demo.teams["Queen's Gambit"]
    scan(client, team, route_of(team["id"])[0].qr_token)
    assert answer(client, team, f"  {puzzle_answer(team['id']).lower()}!  ").json()["correct"] is True


def test_radar_never_reveals_target_coordinates(client):
    demo = seed(client, start=True)
    team = demo.teams["Heart Breakers"]
    route = route_of(team["id"])
    clear_checkpoint(client, team, route[0])
    target = route[1]

    radar = client.get(f"{API}/radar", params={"lat": 13.0800, "lng": 80.2650}, headers=team["headers"]).json()
    assert radar["locked"] is False and radar["distance_m"] > 0
    assert radar["bearing_deg"] % 5 == 0
    blob = str(radar)
    assert str(target.latitude) not in blob and target.name not in blob
    assert radar["target_label"] == "Checkpoint 2 of 8"

    near = client.get(f"{API}/radar", params={"lat": target.latitude, "lng": target.longitude}, headers=team["headers"]).json()
    assert near["near"] is True and near["distance_m"] is None

    needs = client.get(f"{API}/radar", headers=team["headers"]).json()
    assert needs["needs_location"] is True

    state = client.get(f"{API}/me/state", headers=team["headers"]).json()
    blob = str(state)
    assert target.name not in blob and str(target.latitude) not in blob
    assert state["checkpoints"][0]["name"] == route[0].name  # cleared ones are named
    assert state["checkpoints"][1]["state"] == "CURRENT" and state["checkpoints"][1]["name"] is None


def test_leaderboard_is_progress_only(client):
    demo = seed(client, start=True)
    team = demo.teams["Spade Squad"]
    route = route_of(team["id"])
    clear_checkpoint(client, team, route[0])
    scan(client, team, route[5].qr_token)  # wrong -> private foul

    board = client.get(f"{API}/leaderboard", headers=team["headers"]).json()
    assert board["rows"][0]["team_name"] == "Spade Squad" and board["rows"][0]["checkpoints"] == 1
    assert board["rows"][0]["is_you"] is True
    for row in board["rows"]:
        assert set(row) == {"position", "team_name", "checkpoints", "finished", "is_you"}
    assert client.get(f"{API}/leaderboard").status_code == 401  # participants only


def test_idempotent_retry_returns_original_result(client):
    demo = seed(client, start=True)
    team = demo.teams["Spade Squad"]
    wrong = route_of(team["id"])[4]
    k = key()
    first = client.post(f"{API}/scan", json={"code": wrong.qr_token, "idempotency_key": k}, headers=team["headers"]).json()
    retry = client.post(f"{API}/scan", json={"code": wrong.qr_token, "idempotency_key": k}, headers=team["headers"]).json()
    assert first["result"] == "WRONG_QR" and retry.get("replayed") is True
    assert get_team(team["id"]).foul_count == 1  # not fouled twice


def test_rescan_after_last_checkpoint_does_not_crash(client):
    """Regression: the old scan service raised IndexError (HTTP 500) here."""
    demo = seed(client, start=True)
    team = demo.teams["Dragon Warriors"]
    route = route_of(team["id"])
    for loc in route:
        clear_checkpoint(client, team, loc)
    res = scan(client, team, route[2].qr_token)
    assert res.status_code == 200 and res.json()["result"] == "REPEAT"


def test_staggered_start_blocks_early_scans(client):
    demo = seed(client, start=True)
    team = demo.teams["Dragon Warriors"]
    set_team(team["id"], started_at=now() + timedelta(seconds=90))
    res = scan(client, team, route_of(team["id"])[0].qr_token)
    assert res.status_code == 409 and res.json()["start_at"]


def test_paused_event_blocks_actions_and_resume_restores(client):
    demo = seed(client, start=True)
    team = demo.teams["Dragon Warriors"]
    first = route_of(team["id"])[0]
    client.post(f"{API}/admin/events/{demo.event_id}/pause", headers=demo.admin)
    assert scan(client, team, first.qr_token).status_code == 409
    client.post(f"{API}/admin/events/{demo.event_id}/resume", headers=demo.admin)
    assert scan(client, team, first.qr_token).json()["result"] == "VALID"


def test_geofence_block_mode(client):
    demo = seed(client, start=True)
    client.patch(f"{API}/admin/events/{demo.event_id}", json={"settings": {"geofence_mode": "block"}}, headers=demo.admin)
    team = demo.teams["Border Runners"]
    loc = route_of(team["id"])[0]
    far = scan(client, team, loc.qr_token, lat=12.0, lng=79.0).json()
    assert far["result"] == "BLOCKED" and far["foul_added"] is False
    ok = scan(client, team, loc.qr_token, lat=loc.latitude, lng=loc.longitude, accuracy=10).json()
    assert ok["result"] == "VALID"


def test_start_checkpoint_is_shown_once_the_game_is_live(client):
    """The app sends each team to its start with a map route - the
    volunteers don't have to. Only the start: checkpoint 2 stays secret."""
    demo = seed(client, lock=True)
    team = demo.teams["Dragon Warriors"]
    route = route_of(team["id"])
    assert client.get(f"{API}/me/state", headers=team["headers"]).json()["start"] is None  # not before the start
    client.post(f"{API}/admin/events/{demo.event_id}/start", headers=demo.admin)
    s = client.get(f"{API}/me/state", headers=team["headers"]).json()
    assert s["start"]["name"] == route[0].name and s["start"]["code"] == route[0].code and s["start"]["total"] == 8
    assert s["start"]["latitude"] == route[0].latitude and "travelmode=walking" in s["start"]["maps_url"]
    assert s["checkpoints"][1]["name"] is None  # the rest of the route is still hidden
    r = client.get(f"{API}/radar", params={"lat": 13.08, "lng": 80.27}, headers=team["headers"]).json()
    assert r["is_start"] is True and r["guided"] is True and r["target"]["name"] == route[0].name and r["guide_until"] is None
    assert r["target_label"].startswith("Starting checkpoint")
    scan(client, team, route[0].qr_token)
    assert client.get(f"{API}/me/state", headers=team["headers"]).json()["start"] is None  # scanned: gone
    solve_puzzle(client, team)
    r = client.get(f"{API}/radar", params={"lat": 13.08, "lng": 80.27}, headers=team["headers"]).json()
    assert r["is_start"] is False and r["guided"] is False and "target" not in r  # checkpoint 2: radar only
