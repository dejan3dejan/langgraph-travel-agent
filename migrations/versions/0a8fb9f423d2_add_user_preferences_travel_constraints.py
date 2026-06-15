"""add user_preferences travel_constraints

Revision ID: 0a8fb9f423d2
Revises: 959f075e2b8a
Create Date: 2026-06-15 19:18:44.237503

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a8fb9f423d2'
down_revision: Union[str, Sequence[str], None] = '959f075e2b8a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("user_preferences", sa.Column("travel_constraints", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("user_preferences", "travel_constraints")
