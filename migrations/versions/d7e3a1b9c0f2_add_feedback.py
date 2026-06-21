"""add feedback

Revision ID: d7e3a1b9c0f2
Revises: c4d2e8a1f6b7
Create Date: 2026-06-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7e3a1b9c0f2'
down_revision: Union[str, Sequence[str], None] = 'c4d2e8a1f6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "feedback",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("session_id", sa.String(), sa.ForeignKey("chat_sessions.session_id"), nullable=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("kind in ('plan', 'compare', 'app')", name="feedback_kind_valid"),
        sa.CheckConstraint("rating is null or (rating >= 1 and rating <= 5)", name="feedback_rating_range"),
        sa.CheckConstraint("rating is not null or message is not null", name="feedback_has_content"),
    )
    op.create_index("ix_feedback_session_id", "feedback", ["session_id"])
    op.create_index("ix_feedback_user_id", "feedback", ["user_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_feedback_user_id", table_name="feedback")
    op.drop_index("ix_feedback_session_id", table_name="feedback")
    op.drop_table("feedback")
