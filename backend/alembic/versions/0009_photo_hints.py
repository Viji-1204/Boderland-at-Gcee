"""photo hints

A team standing at its checkpoint that can't find the sticker may ask for
the checkpoint's photo (a limited number of times, never on the last few
checkpoints). Each use is a row here. Only a new table.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-21 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0009'
down_revision: Union[str, None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('photo_hints',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('event_id', sa.String(length=36), nullable=False),
    sa.Column('team_id', sa.String(length=36), nullable=False),
    sa.Column('location_id', sa.String(length=36), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['events.id'], name=op.f('fk_photo_hints_event_id_events'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_photo_hints_location_id_locations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], name=op.f('fk_photo_hints_team_id_teams'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_photo_hints')),
    sa.UniqueConstraint('team_id', 'location_id', name='uq_photo_hint_team_location')
    )
    with op.batch_alter_table('photo_hints', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_photo_hints_event_id'), ['event_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_photo_hints_team_id'), ['team_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('photo_hints', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_photo_hints_team_id'))
        batch_op.drop_index(batch_op.f('ix_photo_hints_event_id'))
    op.drop_table('photo_hints')
