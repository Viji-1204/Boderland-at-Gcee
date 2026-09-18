"""/api/v1/health (Docker's healthcheck) and when the demo event is seeded."""
from __future__ import annotations

import pytest

from app.config import Settings

API = "/api/v1"


def test_health_reports_ok_and_the_database_kind(client):
    res = client.get(f"{API}/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok" and res.json()["database"] in ("sqlite", "postgresql")


def test_health_is_503_when_the_database_does_not_answer(client, monkeypatch):
    import app.database as database

    class DownEngine:
        def connect(self):
            raise OSError("database is down")

    monkeypatch.setattr(database, "engine", DownEngine())
    res = client.get(f"{API}/health")
    assert res.status_code == 503 and res.json() == {"status": "error", "database": "unreachable"}


@pytest.mark.parametrize(
    ("environment", "seed_demo", "expected"),
    [
        ("development", None, True),  # plain local run: demo event on a new database
        ("production", None, False),  # a real server never gets demo teams by accident
        ("production", True, True),  # ...unless SEED_DEMO=true asks for a dry run
        ("development", False, False),
    ],
)
def test_demo_event_is_seeded_only_when_wanted(environment, seed_demo, expected):
    assert Settings.model_construct(environment=environment, seed_demo=seed_demo).should_seed_demo is expected
