"""add interaction_signals

Revision ID: f1a9c3e7d204
Revises: e7a4c2d9b513
Create Date: 2026-06-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a9c3e7d204'
down_revision: Union[str, Sequence[str], None] = 'e7a4c2d9b513'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "interaction_signals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("session_id", sa.String(), sa.ForeignKey("chat_sessions.session_id"), nullable=True),
        sa.Column("trip_id", sa.String(), sa.ForeignKey("trips.id"), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_interaction_signals_event_type", "interaction_signals", ["event_type"])
    op.create_index("ix_interaction_signals_created_at", "interaction_signals", ["created_at"])
    op.create_index("ix_interaction_signals_session_id", "interaction_signals", ["session_id"])
    op.create_index("ix_interaction_signals_user_created", "interaction_signals", ["user_id", "created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_interaction_signals_user_created", table_name="interaction_signals")
    op.drop_index("ix_interaction_signals_session_id", table_name="interaction_signals")
    op.drop_index("ix_interaction_signals_created_at", table_name="interaction_signals")
    op.drop_index("ix_interaction_signals_event_type", table_name="interaction_signals")
    op.drop_table("interaction_signals")
