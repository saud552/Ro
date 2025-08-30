from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0003_feature_access_and_purchases"
down_revision = "0002_roulette_gates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feature_access",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feature_key", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("one_time_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.UniqueConstraint("user_id", "feature_key", name="uq_user_feature"),
    )
    op.create_index("ix_feature_access_user_id", "feature_access", ["user_id"])

    op.create_table(
        "purchases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("payload", sa.String(length=64), nullable=False),
        sa.Column("stars_amount", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
    )
    op.create_index("ix_purchases_user_id", "purchases", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_purchases_user_id", table_name="purchases")
    op.drop_table("purchases")
    op.drop_index("ix_feature_access_user_id", table_name="feature_access")
    op.drop_table("feature_access")
