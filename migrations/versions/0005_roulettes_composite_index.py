from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0005_roulettes_composite_index"
down_revision = "0004_settings_and_bot_chats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_roulettes_channel_id_is_open", "roulettes", ["channel_id", "is_open"])


def downgrade() -> None:
    op.drop_index("ix_roulettes_channel_id_is_open", table_name="roulettes")
