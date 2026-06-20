"""add shared itineraries

Revision ID: b3c1d7e9f2a4
Revises: 0a8fb9f423d2
Create Date: 2026-06-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c1d7e9f2a4'
down_revision: Union[str, Sequence[str], None] = '0a8fb9f423d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "shared_itineraries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("itinerary_text", sa.Text(), nullable=False),
        sa.Column("geo", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("shared_itineraries")
