"""power catalogue

Help / Attack / Defence become families of powers:

* HELP -> GUIDE (reveals the current target instead of calling a volunteer);
  the coordinator help queue (``help_requests``) goes away with it.
* ATTACK -> FREEZE, joined by JAM (radar blackout) and TRAP (plants a foul).
* DEFENCE -> SHIELD, joined by REFLECT (bounce the attack back) and WARD
  (armed in advance, auto-blocks).

Existing rows are renamed in place, so what teams already bought and used
keeps its meaning. Every existing event gets price rows for the new kinds
at the default prices (editable in Event Setup).

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-18 17:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RENAMES = {"HELP": "GUIDE", "ATTACK": "FREEZE", "DEFENCE": "SHIELD"}
# kind -> (cost, max_per_team); the same numbers as event_service.DEFAULT_POWER_PRICES
NEW_KINDS = {"JAM": (20, 3), "TRAP": (40, 1), "REFLECT": (35, 2), "WARD": (25, 2)}


def upgrade() -> None:
    with op.batch_alter_table('teams', schema=None) as batch_op:
        batch_op.add_column(sa.Column('jammed_until', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('warded_until', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('guide_until', sa.DateTime(), nullable=True))

    with op.batch_alter_table('power_usage', schema=None) as batch_op:
        batch_op.add_column(sa.Column('resolved_with', sa.String(length=12), nullable=True))

    for table in ("powers", "team_powers", "power_usage"):
        for old, new in RENAMES.items():
            op.execute(f"UPDATE {table} SET kind = '{new}' WHERE kind = '{old}'")
    # A landed attack was ACCEPTED or timed out; a blocked one used a Shield.
    op.execute("UPDATE power_usage SET resolved_with = 'ACCEPTED' WHERE kind = 'FREEZE' AND status = 'CONFIRMED'")
    op.execute("UPDATE power_usage SET resolved_with = 'TIMEOUT' WHERE kind = 'FREEZE' AND status = 'EXPIRED'")
    op.execute("UPDATE power_usage SET resolved_with = 'SHIELD' WHERE kind = 'FREEZE' AND status = 'CANCELLED'")

    bind = op.get_bind()
    powers = sa.table(
        "powers",
        sa.column("id", sa.String), sa.column("event_id", sa.String), sa.column("kind", sa.String),
        sa.column("cost", sa.Integer), sa.column("max_per_team", sa.Integer), sa.column("active", sa.Boolean),
    )
    events = [row[0] for row in bind.execute(sa.text("SELECT id FROM events")).all()]
    present = {(row[0], row[1]) for row in bind.execute(sa.text("SELECT event_id, kind FROM powers")).all()}
    import uuid

    rows = [
        {"id": str(uuid.uuid4()), "event_id": event_id, "kind": kind, "cost": cost, "max_per_team": cap, "active": True}
        for event_id in events
        for kind, (cost, cap) in NEW_KINDS.items()
        if (event_id, kind) not in present
    ]
    if rows:
        bind.execute(powers.insert(), rows)

    with op.batch_alter_table('help_requests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_help_requests_team_id'))
        batch_op.drop_index(batch_op.f('ix_help_requests_status'))
        batch_op.drop_index(batch_op.f('ix_help_requests_event_id'))
    op.drop_table('help_requests')


def downgrade() -> None:
    op.create_table('help_requests',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('event_id', sa.String(length=36), nullable=False),
    sa.Column('team_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=14), nullable=False),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('acknowledged_at', sa.DateTime(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(), nullable=True),
    sa.Column('handled_by', sa.String(length=80), nullable=True),
    sa.ForeignKeyConstraint(['event_id'], ['events.id'], name=op.f('fk_help_requests_event_id_events'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], name=op.f('fk_help_requests_team_id_teams'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_help_requests'))
    )
    with op.batch_alter_table('help_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_help_requests_event_id'), ['event_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_help_requests_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_help_requests_team_id'), ['team_id'], unique=False)

    # The new kinds have no meaning in the old code: drop their rows.
    new_kinds = "', '".join(NEW_KINDS)
    for table in ("powers", "team_powers", "power_usage"):
        op.execute(f"DELETE FROM {table} WHERE kind IN ('{new_kinds}')")
        for old, new in RENAMES.items():
            op.execute(f"UPDATE {table} SET kind = '{old}' WHERE kind = '{new}'")

    with op.batch_alter_table('power_usage', schema=None) as batch_op:
        batch_op.drop_column('resolved_with')

    with op.batch_alter_table('teams', schema=None) as batch_op:
        batch_op.drop_column('guide_until')
        batch_op.drop_column('warded_until')
        batch_op.drop_column('jammed_until')
