"""add trip members (collaboration)

Revision ID: e7a4c2d9b513
Revises: d5e3f9a2b8c1
Create Date: 2026-06-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a4c2d9b513'
down_revision: Union[str, Sequence[str], None] = 'd5e3f9a2b8c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "trip_members",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("trip_id", sa.String(), sa.ForeignKey("trips.id"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="viewer"),
        sa.Column("invited_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("trip_id", "user_id", name="uq_trip_member"),
        sa.CheckConstraint("role IN ('viewer', 'editor')", name="ck_trip_member_role"),
    )
    op.create_index("ix_trip_members_trip_id", "trip_members", ["trip_id"])
    op.create_index("ix_trip_members_user_id", "trip_members", ["user_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_trip_members_user_id", table_name="trip_members")
    op.drop_index("ix_trip_members_trip_id", table_name="trip_members")
    op.drop_table("trip_members")
