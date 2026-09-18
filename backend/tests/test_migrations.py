"""The Alembic migration must build exactly the schema the models describe."""
from __future__ import annotations

import pathlib
import tempfile

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.config import settings
from app.database import Base
from app.migrate import alembic_config


def test_migration_matches_models(monkeypatch):
    import app.database as database

    if settings.is_sqlite:
        path = pathlib.Path(tempfile.mkdtemp(prefix="round2-mig-")) / "mig.db"
        engine = create_engine(f"sqlite:///{path.as_posix()}")
    else:  # TEST_DATABASE_URL: migrate the throwaway Postgres test database itself
        engine = database.engine
        Base.metadata.drop_all(engine)
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))

    monkeypatch.setattr(database, "engine", engine)  # env.py uses app.database.engine
    command.upgrade(alembic_config(), "head")

    tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert tables == set(Base.metadata.tables)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], diff


def test_0004_carries_face_cards_onto_existing_routes(monkeypatch):
    """Upgrading a database from before per-team cards: every route stop
    inherits the card its location held, so a configured event plays on."""
    import app.database as database

    if not settings.is_sqlite:
        return  # the SQLite file below is enough to prove the data step
    path = pathlib.Path(tempfile.mkdtemp(prefix="round2-mig-")) / "mig.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    monkeypatch.setattr(database, "engine", engine)
    command.upgrade(alembic_config(), "0003")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO events (id, name, status, settings, final_location_name, created_at) VALUES ('E', 'Old', 'DRAFT', '{}', 'Bench', '2026-01-01')"))
        for code, face in (("L01", "JACK"), ("L02", None), ("L03", "KING")):
            conn.execute(text(
                "INSERT INTO locations (id, event_id, code, name, latitude, longitude, geofence_radius_m, is_selected, face_card, qr_token, created_at) "
                f"VALUES ('{code}', 'E', '{code}', '{code}', 0, 0, 40, 1, {'NULL' if face is None else repr(face)}, 'tok-{code}', '2026-01-01')"
            ))
        conn.execute(text(
            "INSERT INTO teams (id, event_id, team_code, team_name, password_hash, status, power_points, foul_count, progress, start_offset_s, created_at) "
            "VALUES ('T', 'E', 'T1', 'Team', 'x', 'NOT_STARTED', 100, 0, 0, 0, '2026-01-01')"
        ))
        for seq, code in enumerate(("L02", "L01", "L03"), start=1):
            conn.execute(text(f"INSERT INTO route_stops (id, team_id, location_id, seq) VALUES ('S{seq}', 'T', '{code}', {seq})"))
        # Old-style powers: one price row and a bought/used Attack, for 0005 to rename.
        conn.execute(text("INSERT INTO powers (id, event_id, kind, cost, max_per_team, active) VALUES ('P1', 'E', 'ATTACK', 30, 3, 1)"))
        conn.execute(text("INSERT INTO team_powers (id, team_id, kind, owned, used) VALUES ('TP1', 'T', 'ATTACK', 2, 1)"))
        conn.execute(text("INSERT INTO power_usage (id, event_id, kind, team_id, status, created_at) VALUES ('U1', 'E', 'ATTACK', 'T', 'CANCELLED', '2026-01-01')"))
    command.upgrade(alembic_config(), "head")
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT seq, face_card FROM route_stops ORDER BY seq")).all()
        assert rows == [(1, None), (2, "JACK"), (3, "KING")]
        assert "face_card" not in {c["name"] for c in inspect(engine).get_columns("locations")}
        # 0005: kinds renamed, the blocked attack remembers its Shield, new kinds priced.
        assert conn.execute(text("SELECT kind, owned, used FROM team_powers")).all() == [("FREEZE", 2, 1)]
        assert conn.execute(text("SELECT kind, resolved_with FROM power_usage")).all() == [("FREEZE", "SHIELD")]
        prices = dict(conn.execute(text("SELECT kind, cost FROM powers ORDER BY kind")).all())
        assert prices == {"FREEZE": 30, "JAM": 20, "REFLECT": 35, "TRAP": 40, "WARD": 25}
        assert "help_requests" not in inspect(engine).get_table_names()
