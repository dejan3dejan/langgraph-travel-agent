"""add shared itinerary lifecycle (revoke token, expiry)

Revision ID: c4d2e8a1f6b7
Revises: b3c1d7e9f2a4
Create Date: 2026-06-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d2e8a1f6b7'
down_revision: Union[str, Sequence[str], None] = 'b3c1d7e9f2a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("shared_itineraries", sa.Column("revoke_token", sa.String(), nullable=True))
    op.add_column("shared_itineraries", sa.Column("expires_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("shared_itineraries", "expires_at")
    op.drop_column("shared_itineraries", "revoke_token")
