"""Photo hints: the checkpoint photo for a team standing at the spot that
can't find the sticker - twice per game, never on the last three checkpoints."""
from __future__ import annotations

from tests.helpers import clear_checkpoint, key, route_of, scan, seed, set_team

API = "/api/v1"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"spot"


def _photo_for(client, demo, loc):
    res = client.post(f"{API}/admin/checkpoints/{loc.id}/photo", files={"file": ("spot.jpg", JPEG, "image/jpeg")}, headers=demo.admin)
    assert res.status_code == 200, res.text


def hint(client, team, loc=None, **extra):
    body = {"idempotency_key": key(), **extra}
    if loc is not None:
        body.update({"lat": loc.latitude, "lng": loc.longitude, "accuracy": 8})
    return client.post(f"{API}/me/photo-hint", json=body, headers=team["headers"])


def state(client, team):
    return client.get(f"{API}/me/state", headers=team["headers"]).json()


def test_photo_hint_needs_the_team_at_the_spot_and_shows_the_photo(client):
    demo = seed(client, start=True)
    team = demo.teams["Dragon Warriors"]
    route = route_of(team["id"])
    _photo_for(client, demo, route[0])

    s = state(client, team)["photo_hint"]
    assert s["per_team"] == 2 and s["remaining"] == 2 and s["usable_here"] is True and s["revealed"] is False

    far = hint(client, team, lat=13.0, lng=80.0, accuracy=5)
    assert far.status_code == 409 and "not close enough" in far.json()["detail"]
    nowhere = hint(client, team)
    assert nowhere.status_code == 400 and "location" in nowhere.json()["detail"].lower()

    ok = hint(client, team, route[0]).json()
    assert ok["revealed"] is True and ok["remaining"] == 1 and ok["seq"] == 1
    img = client.get(f"{API}/me/photo-hint/image", headers=team["headers"])
    assert img.status_code == 200 and img.content == JPEG and img.headers["content-type"] == "image/jpeg"
    assert client.get(f"{API}/me/photo-hint/image", headers=demo.teams["Border Runners"]["headers"]).status_code == 404  # not theirs

    again = hint(client, team, route[0]).json()  # same checkpoint: no second charge
    assert again["remaining"] == 1
    s = state(client, team)["photo_hint"]
    assert s["remaining"] == 1 and s["revealed"] is True
    radar = client.get(f"{API}/radar", params={"lat": route[0].latitude, "lng": route[0].longitude}, headers=team["headers"]).json()
    assert radar["near"] is True and radar["photo_hint"]["revealed"] is True

    # Scanning moves on: the photo of the old target is gone, the next has none yet.
    clear_checkpoint(client, team, route[0])
    assert client.get(f"{API}/me/photo-hint/image", headers=team["headers"]).status_code == 404
    assert state(client, team)["photo_hint"]["revealed"] is False


def test_photo_hint_limits(client):
    demo = seed(client, start=True)  # 8 checkpoints: hints allowed on 1-5, never on 6-8
    team = demo.teams["Dragon Warriors"]
    route = route_of(team["id"])
    for loc in route:
        _photo_for(client, demo, loc)

    scan(client, team, route[0].qr_token)  # on a puzzle: radar shut, no hint
    assert hint(client, team, route[0]).status_code == 409
    from tests.helpers import solve_puzzle

    solve_puzzle(client, team)
    assert hint(client, team, route[1]).json()["remaining"] == 1
    clear_checkpoint(client, team, route[1])
    assert hint(client, team, route[2]).json()["remaining"] == 0
    clear_checkpoint(client, team, route[2])
    out = hint(client, team, route[3])
    assert out.status_code == 409 and "No photo hints left" in out.json()["detail"]
    assert state(client, team)["photo_hint"]["reason"] == "No photo hints left."

    # A fresh team at checkpoint 6 of 8: inside the last three, so never.
    other = demo.teams["Border Runners"]
    set_team(other["id"], progress=5)
    r6 = route_of(other["id"])[5]
    last = hint(client, other, r6)
    assert last.status_code == 409 and "last 3" in last.json()["detail"]
    assert state(client, other)["photo_hint"]["reason"] == "No photo hints on the last 3 checkpoints."
    # ...and checkpoint 5 (just outside) is fine.
    set_team(other["id"], progress=4)
    assert hint(client, other, route_of(other["id"])[4]).status_code == 200


def test_photo_hint_needs_a_photo_and_respects_the_settings(client):
    demo = seed(client, start=True)
    team = demo.teams["Dragon Warriors"]
    route = route_of(team["id"])
    none = hint(client, team, route[0])
    assert none.status_code == 409 and "no photo" in none.json()["detail"]
    assert state(client, team)["photo_hint"]["reason"] == "This checkpoint has no photo."
    # Switched off in Game Setup
    client.post(f"{API}/admin/events/{demo.event_id}/end", headers=demo.admin)
    client.post(f"{API}/admin/events/{demo.event_id}/restart", headers=demo.admin)
    client.post(f"{API}/admin/events/{demo.event_id}/unlock", headers=demo.admin)
    assert client.patch(f"{API}/admin/events/{demo.event_id}", json={"settings": {"photo_hints_per_team": 0}}, headers=demo.admin).status_code == 200
    client.post(f"{API}/admin/events/{demo.event_id}/lock", headers=demo.admin)
    client.post(f"{API}/admin/events/{demo.event_id}/start", headers=demo.admin)
    _photo_for(client, demo, route_of(team["id"])[0])
    off = hint(client, team, route_of(team["id"])[0])
    assert off.status_code == 409 and "off" in off.json()["detail"]
    assert state(client, team)["photo_hint"]["reason"] == "Photo hints are off in this game."
