"""Test setup: every test gets a fresh schema in a temporary SQLite file.

The database URL is pointed at a temp directory *before* the app is
imported, so tests can never touch backend/data/round2.db.

To run the same tests on Postgres, point TEST_DATABASE_URL at a throwaway
database whose name ends in "_test" (every test drops all its tables):

    docker run -d --rm --name bl2-pg-test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=round2_test -p 127.0.0.1:55432:5432 postgres:16
    TEST_DATABASE_URL=postgresql+psycopg2://postgres:test@127.0.0.1:55432/round2_test python -m pytest
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="round2-tests-"))
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["AUTO_MIGRATE"] = "false"
os.environ["SEED_DEMO"] = "false"
os.environ["ENVIRONMENT"] = "test"
os.environ["JWT_SECRET"] = "test-secret-not-for-production"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bcrypt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_real_gensalt = bcrypt.gensalt
bcrypt.gensalt = lambda rounds=4, prefix=b"2b": _real_gensalt(4, prefix)  # fast hashes in tests only

import app.models  # noqa: E402,F401
from app.config import settings  # noqa: E402
from app.database import Base, engine  # noqa: E402

from sqlalchemy.engine import make_url  # noqa: E402

_test_db_name = make_url(settings.database_url).database or ""
assert "round2-tests-" in _test_db_name or (not settings.is_sqlite and _test_db_name.endswith("_test")), (
    "tests must never run against the real database"
)


@pytest.fixture(autouse=True)
def fresh_schema():
    Base.metadata.drop_all(engine)  # the throwaway test DB only (asserted above)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def no_rate_limits(monkeypatch):
    """Scan/radar limiters are per-second; tests fire faster than that."""
    from app.core import ratelimit
    from app.services import auth_service, scan_service

    monkeypatch.setattr(scan_service, "_scan_limiter", ratelimit.MinInterval(0))
    monkeypatch.setattr(scan_service, "_radar_limiter", ratelimit.MinInterval(0))
    monkeypatch.setattr(auth_service, "_throttle", ratelimit.FailureThrottle(settings.login_max_failures, 300))
    monkeypatch.setattr(auth_service, "_account_throttle", ratelimit.FailureThrottle(settings.login_max_failures * 4, 300))
    scan_service._radar_cache.clear()


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
