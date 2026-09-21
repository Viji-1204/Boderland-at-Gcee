"""checkpoint library

Checkpoints stop belonging to an event: ``locations`` becomes one library
shared by every event, with a globally unique code (L01-L15). A new event
reuses the same spots and their QR stickers instead of getting copies.

Existing databases may hold several events each with its own L01..L08.
They are merged by code: the copy from the newest event that hasn't ended
becomes the library's, every other event's routes, scans and puzzle
sessions are re-pointed at it, and the duplicates are removed.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-20 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _merge_duplicates(bind) -> None:
    events = {row[0]: (row[1], str(row[2] or "")) for row in bind.execute(sa.text("SELECT id, status, created_at FROM events")).all()}
    by_code: dict[str, list[tuple[str, str]]] = {}
    for loc_id, event_id, code in bind.execute(sa.text("SELECT id, event_id, code FROM locations")).all():
        by_code.setdefault(code, []).append((loc_id, event_id))
    for code, rows in by_code.items():
        if len(rows) < 2:
            continue
        # Newest event first; any event that hasn't ended beats an ended one.
        rows.sort(key=lambda r: events.get(r[1], ("", ""))[1], reverse=True)
        rows.sort(key=lambda r: 0 if events.get(r[1], ("ENDED", ""))[0] != "ENDED" else 1)
        keep = rows[0][0]
        for dup, _event in rows[1:]:
            for table in ("route_stops", "scans", "puzzle_sessions"):
                bind.execute(sa.text(f"UPDATE {table} SET location_id = :keep WHERE location_id = :dup"), {"keep": keep, "dup": dup})
            for table in ("location_photos", "puzzles"):
                bind.execute(sa.text(f"DELETE FROM {table} WHERE location_id = :dup"), {"dup": dup})
            bind.execute(sa.text("DELETE FROM locations WHERE id = :dup"), {"dup": dup})


def upgrade() -> None:
    _merge_duplicates(op.get_bind())
    with op.batch_alter_table('locations', schema=None) as batch_op:
        batch_op.drop_constraint('uq_location_event_code', type_='unique')
        batch_op.drop_index(batch_op.f('ix_locations_event_id'))
        batch_op.drop_constraint(batch_op.f('fk_locations_event_id_events'), type_='foreignkey')
        batch_op.drop_column('event_id')
        batch_op.create_unique_constraint('uq_location_code', ['code'])


def downgrade() -> None:
    # The per-event copies can't be reconstructed. Every checkpoint is handed
    # to the newest event (older events then have no checkpoints of their own).
    bind = op.get_bind()
    with op.batch_alter_table('locations', schema=None) as batch_op:
        batch_op.drop_constraint('uq_location_code', type_='unique')
        batch_op.add_column(sa.Column('event_id', sa.String(length=36), nullable=True))
    newest = bind.execute(sa.text("SELECT id FROM events ORDER BY created_at DESC LIMIT 1")).scalar()
    if newest:
        bind.execute(sa.text("UPDATE locations SET event_id = :e"), {"e": newest})
    else:
        bind.execute(sa.text("DELETE FROM locations"))
    with op.batch_alter_table('locations', schema=None) as batch_op:
        batch_op.alter_column('event_id', existing_type=sa.String(length=36), nullable=False)
        batch_op.create_foreign_key(batch_op.f('fk_locations_event_id_events'), 'events', ['event_id'], ['id'], ondelete='CASCADE')
        batch_op.create_index(batch_op.f('ix_locations_event_id'), ['event_id'], unique=False)
        batch_op.create_unique_constraint('uq_location_event_code', ['event_id', 'code'])
