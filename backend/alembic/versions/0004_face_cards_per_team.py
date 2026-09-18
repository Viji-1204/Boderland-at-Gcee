"""face cards per team

The Jack, Queen and King move from ``locations`` (one of each per event,
chosen by hand in Setup Routes) to ``route_stops`` (one of each per team,
dealt at random when routes are generated). Existing routes keep their
cards: each stop inherits the card its location held, so a configured or
live event plays on unchanged.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-18 16:20:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('route_stops', schema=None) as batch_op:
        batch_op.add_column(sa.Column('face_card', sa.String(length=10), nullable=True))
        batch_op.create_unique_constraint('uq_route_team_face_card', ['team_id', 'face_card'])

    # Carry the event-wide cards over to every team's route.
    op.execute(
        "UPDATE route_stops SET face_card = ("
        "SELECT face_card FROM locations WHERE locations.id = route_stops.location_id)"
    )

    with op.batch_alter_table('locations', schema=None) as batch_op:
        batch_op.drop_constraint('uq_location_face_card', type_='unique')
        batch_op.drop_column('face_card')


def downgrade() -> None:
    # Per-team cards can't be folded back into one card per location (teams
    # hold them at different checkpoints), so the column comes back empty:
    # set the Jack, Queen and King again in the old Setup Routes section.
    with op.batch_alter_table('locations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('face_card', sa.String(length=10), nullable=True))
        batch_op.create_unique_constraint('uq_location_face_card', ['event_id', 'face_card'])

    with op.batch_alter_table('route_stops', schema=None) as batch_op:
        batch_op.drop_constraint('uq_route_team_face_card', type_='unique')
        batch_op.drop_column('face_card')
