from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_settings_and_bot_chats"
down_revision = "0003_feature_access_and_purchases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(length=64), nullable=False, unique=True),
        sa.Column("value", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
    )

    op.create_table(
        "bot_chats",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=True),
        sa.Column(
            "added_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("chat_id", name="uq_bot_chat_id"),
    )
    op.create_index("ix_bot_chats_chat_id", "bot_chats", ["chat_id"])


def downgrade() -> None:
    op.drop_index("ix_bot_chats_chat_id", table_name="bot_chats")
    op.drop_table("bot_chats")
    op.drop_table("app_settings")
