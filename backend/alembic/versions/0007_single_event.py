"""single event

The app runs one game. Databases from before this held any number of
events (demo hunts, test runs, the real one side by side); only one
survives: a game in play (LIVE/PAUSED) first, then a locked one, then a
draft, then an ended one - newest first within each group.
The others are deleted with everything that belonged to them (teams,
routes, scans, fouls, power purchases, logs). Checkpoints are a shared
library and are untouched.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-20 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, status, created_at FROM events")).all()
    if len(rows) < 2:
        return
    rank = {"LIVE": 0, "PAUSED": 0, "CONFIGURED": 1, "DRAFT": 2, "ENDED": 3}
    rows = sorted(rows, key=lambda r: str(r[2] or ""), reverse=True)  # newest first...
    rows.sort(key=lambda r: rank.get(r[1], 3))  # ...but a game in play beats a locked one beats a draft beats an ended one
    keep = rows[0][0]
    # Child rows cascade in the database (every FK to events/teams is ON DELETE
    # CASCADE), but SQLite only honours that with foreign keys switched on, so
    # the dependants are removed explicitly first.
    others = [r[0] for r in rows[1:]]
    marks = ", ".join(f":e{i}" for i in range(len(others)))
    params = {f"e{i}": eid for i, eid in enumerate(others)}
    team_marks = f"SELECT id FROM teams WHERE event_id IN ({marks})"
    for table in ("route_stops", "sentence_fragments", "team_powers", "puzzle_sessions", "puzzle_attempts", "idempotency_keys"):
        bind.execute(sa.text(f"DELETE FROM {table} WHERE team_id IN ({team_marks})"), params)
    for table in ("power_usage", "scans", "fouls", "game_events", "admin_actions", "powers", "teams"):
        bind.execute(sa.text(f"DELETE FROM {table} WHERE event_id IN ({marks})"), params)
    bind.execute(sa.text(f"DELETE FROM events WHERE id IN ({marks})"), params)


def downgrade() -> None:
    pass  # the deleted events can't be restored; a single event is still a valid state for older code
