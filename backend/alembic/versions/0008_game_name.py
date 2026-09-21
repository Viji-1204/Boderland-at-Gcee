"""game name

The one game no longer carries a name of its own in the console or the
team app - the brand is the name. Whatever was typed while the app still
had an events list (a test run's name, say) is replaced by the default, so
the results export and logs read sensibly.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-20 19:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE events SET name = 'Borderland @ GCEE - Round 2'")


def downgrade() -> None:
    pass
