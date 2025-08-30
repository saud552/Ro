from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_roulette_gates"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roulette_gates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "roulette_id",
            sa.Integer(),
            sa.ForeignKey("roulettes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column("channel_title", sa.String(length=256), nullable=False),
        sa.Column("invite_link", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
    )
    op.create_index("ix_roulette_gates_roulette_id", "roulette_gates", ["roulette_id"])
    op.create_index("ix_roulette_gates_channel_id", "roulette_gates", ["channel_id"])


def downgrade() -> None:
    op.drop_index("ix_roulette_gates_channel_id", table_name="roulette_gates")
    op.drop_index("ix_roulette_gates_roulette_id", table_name="roulette_gates")
    op.drop_table("roulette_gates")
