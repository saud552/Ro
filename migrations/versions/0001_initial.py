from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # users
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # channel_links
    op.create_table(
        "channel_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "owner_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_title", sa.String(length=256), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.UniqueConstraint("owner_id", "channel_id", name="uq_owner_channel"),
    )
    op.create_index("ix_channel_links_channel_id", "channel_links", ["channel_id"])

    # roulettes
    op.create_table(
        "roulettes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "owner_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_message_id", sa.Integer(), nullable=True),
        sa.Column("text_raw", sa.Text(), nullable=False),
        sa.Column("text_style", sa.String(length=16), nullable=False, server_default="plain"),
        sa.Column("winners_count", sa.Integer(), nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_roulettes_channel_id", "roulettes", ["channel_id"])

    # participants
    op.create_table(
        "participants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "roulette_id",
            sa.Integer(),
            sa.ForeignKey("roulettes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "joined_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.UniqueConstraint("roulette_id", "user_id", name="uq_roulette_user"),
    )
    op.create_index("ix_participants_roulette_id", "participants", ["roulette_id"])
    op.create_index("ix_participants_user_id", "participants", ["user_id"])

    # notifications
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "roulette_id",
            sa.Integer(),
            sa.ForeignKey("roulettes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_index("ix_participants_user_id", table_name="participants")
    op.drop_index("ix_participants_roulette_id", table_name="participants")
    op.drop_table("participants")
    op.drop_index("ix_roulettes_channel_id", table_name="roulettes")
    op.drop_table("roulettes")
    op.drop_index("ix_channel_links_channel_id", table_name="channel_links")
    op.drop_table("channel_links")
    op.drop_table("users")
