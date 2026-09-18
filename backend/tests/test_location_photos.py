"""Checkpoint photos (Setup Routes): kept in the database, admin-only."""
from __future__ import annotations

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import LocationPhoto
from tests.helpers import seed

API = "/api/v1"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"full-size"
THUMB = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"thumb"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _loc(client, demo, code="L01", event_id=None):
    locs = client.get(f"{API}/admin/events/{event_id or demo.event_id}/locations", headers=demo.admin).json()
    return next(loc for loc in locs if loc["code"] == code)


def _upload(client, demo, loc_id, data=JPEG, thumb=THUMB, name="spot.jpg", ctype="image/jpeg"):
    files = {"file": (name, data, ctype)}
    if thumb is not None:
        files["thumb"] = ("thumb.jpg", thumb, "image/jpeg")
    return client.post(f"{API}/admin/events/{demo.event_id}/locations/{loc_id}/photo", files=files, headers=demo.admin)


def _photo_rows() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count(LocationPhoto.id)))


def test_photo_is_stored_listed_served_and_replaced(client):
    demo = seed(client)
    loc = _loc(client, demo)
    assert loc["has_photo"] is False and loc["photo_updated_at"] is None

    res = _upload(client, demo, loc["id"])
    assert res.status_code == 200, res.text
    assert res.json()["has_photo"] is True and res.json()["photo_updated_at"]
    assert _loc(client, demo)["has_photo"] is True

    url = f"{API}/admin/events/{demo.event_id}/locations/{loc['id']}/photo"
    full = client.get(url, headers=demo.admin)
    assert full.status_code == 200 and full.content == JPEG and full.headers["content-type"] == "image/jpeg"
    assert full.headers["x-content-type-options"] == "nosniff"
    assert client.get(url, params={"thumb": 1}, headers=demo.admin).content == THUMB

    # Replacing keeps one row. With no thumbnail, the full image stands in for it.
    assert _upload(client, demo, loc["id"], data=PNG, thumb=None, name="x.png", ctype="image/png").status_code == 200
    small = client.get(url, params={"thumb": 1}, headers=demo.admin)
    assert small.content == PNG and small.headers["content-type"] == "image/png"
    assert _photo_rows() == 1


def test_only_real_images_within_the_limits_are_accepted(client):
    demo = seed(client)
    loc_id = _loc(client, demo)["id"]
    fake = _upload(client, demo, loc_id, data=b"<html><script>alert(1)</script></html>")  # labelled image/jpeg
    assert fake.status_code == 400 and "JPEG, PNG or WebP" in fake.json()["detail"]
    huge = _upload(client, demo, loc_id, data=b"\xff\xd8\xff" + b"\x00" * (5 * 1024 * 1024))
    assert huge.status_code == 400 and "too big (max 5 MB)" in huge.json()["detail"]
    bad_thumb = _upload(client, demo, loc_id, thumb=b"GIF89a-not-allowed")
    assert bad_thumb.status_code == 400 and "thumbnail" in bad_thumb.json()["detail"]
    assert _loc(client, demo)["has_photo"] is False and _photo_rows() == 0


def test_removing_a_photo_and_deleting_a_checkpoint_take_the_photo_away(client):
    demo = seed(client)
    kept, deleted = _loc(client, demo, "L01"), _loc(client, demo, "L09")  # L09: in the pool, not in the game
    for loc in (kept, deleted):
        assert _upload(client, demo, loc["id"]).status_code == 200
    base = f"{API}/admin/events/{demo.event_id}/locations"
    assert client.delete(f"{base}/{kept['id']}/photo", headers=demo.admin).status_code == 204
    assert client.get(f"{base}/{kept['id']}/photo", headers=demo.admin).status_code == 404
    assert _loc(client, demo, "L01")["has_photo"] is False
    assert client.delete(f"{base}/{deleted['id']}", headers=demo.admin).status_code == 204
    assert _photo_rows() == 0


def test_photos_can_be_fixed_during_the_game_not_after_and_teams_never_get_them(client):
    demo = seed(client, start=True)
    loc_id = _loc(client, demo)["id"]
    assert _upload(client, demo, loc_id).status_code == 200  # adding one on the day is fine
    url = f"{API}/admin/events/{demo.event_id}/locations/{loc_id}/photo"
    assert client.get(url, headers=demo.teams["Dragon Warriors"]["headers"]).status_code == 401
    assert client.post(f"{API}/admin/events/{demo.event_id}/end", headers=demo.admin).status_code == 200
    late = _upload(client, demo, loc_id)
    assert late.status_code == 409 and "ended" in late.json()["detail"]
    assert client.get(url, headers=demo.admin).status_code == 200  # still viewable afterwards


def test_copying_an_event_keeps_its_checkpoint_photos(client):
    demo = seed(client)
    _upload(client, demo, _loc(client, demo)["id"])
    res = client.post(f"{API}/admin/events", json={"name": "Real hunt", "clone_from_event_id": demo.event_id}, headers=demo.admin)
    assert res.status_code in (200, 201), res.text
    copy = _loc(client, demo, event_id=res.json()["id"])
    assert copy["has_photo"] is True
    got = client.get(f"{API}/admin/events/{res.json()['id']}/locations/{copy['id']}/photo", headers=demo.admin)
    assert got.content == JPEG
