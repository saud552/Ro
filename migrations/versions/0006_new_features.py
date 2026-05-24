from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0006_new_features"
down_revision = "0005_roulettes_composite_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Subscriptions table
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subscription_type", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("one_time_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("referral_code", sa.String(length=32), nullable=False),
        sa.Column("referral_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_subscription_user"),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])

    # Voting contests
    op.create_table(
        "voting_contests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("group_id", sa.BigInteger(), nullable=True),
        sa.Column("channel_message_id", sa.Integer(), nullable=True),
        sa.Column("text_raw", sa.Text(), nullable=False),
        sa.Column("text_style", sa.String(length=16), nullable=False, server_default="plain"),
        sa.Column("voting_type", sa.String(length=16), nullable=False, server_default="normal"),
        sa.Column("stars_per_vote", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("allow_multiple_votes", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("require_subscription", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("anti_bot_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("exclude_leavers", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("premium_only", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voting_contests_owner_id", "voting_contests", ["owner_id"])
    op.create_index("ix_voting_contests_channel_id", "voting_contests", ["channel_id"])

    # Voting candidates
    op.create_table(
        "voting_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contest_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("channel_message_id", sa.Integer(), nullable=True),
        sa.Column("vote_code", sa.String(length=32), nullable=False),
        sa.Column("normal_votes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("star_votes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["contest_id"], ["voting_contests.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("contest_id", "user_id", name="uq_contest_candidate_user"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voting_candidates_contest_id", "voting_candidates", ["contest_id"])
    op.create_index("ix_voting_candidates_user_id", "voting_candidates", ["user_id"])
    op.create_index("ix_voting_candidates_vote_code", "voting_candidates", ["vote_code"])

    # Voting votes
    op.create_table(
        "voting_votes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contest_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("voter_id", sa.BigInteger(), nullable=False),
        sa.Column("is_star_vote", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("stars_amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["contest_id"], ["voting_contests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["voting_candidates.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("contest_id", "candidate_id", "voter_id", name="uq_vote_unique"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voting_votes_contest_id", "voting_votes", ["contest_id"])
    op.create_index("ix_voting_votes_voter_id", "voting_votes", ["voter_id"])

    # Deserves contests
    op.create_table(
        "deserves_contests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("group_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_message_id", sa.Integer(), nullable=True),
        sa.Column("text_raw", sa.Text(), nullable=False),
        sa.Column("text_style", sa.String(length=16), nullable=False, server_default="plain"),
        sa.Column("require_subscription", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("anti_bot_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("exclude_leavers", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("premium_only", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deserves_contests_owner_id", "deserves_contests", ["owner_id"])
    op.create_index("ix_deserves_contests_channel_id", "deserves_contests", ["channel_id"])
    op.create_index("ix_deserves_contests_group_id", "deserves_contests", ["group_id"])

    # Deserves candidates
    op.create_table(
        "deserves_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contest_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("vote_code", sa.String(length=32), nullable=False),
        sa.Column("vote_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["contest_id"], ["deserves_contests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deserves_candidates_contest_id", "deserves_candidates", ["contest_id"])
    op.create_index("ix_deserves_candidates_user_id", "deserves_candidates", ["user_id"])
    op.create_index("ix_deserves_candidates_vote_code", "deserves_candidates", ["vote_code"])

    # Deserves votes
    op.create_table(
        "deserves_votes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contest_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("voter_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["contest_id"], ["deserves_contests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["deserves_candidates.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("contest_id", "candidate_id", "voter_id", name="uq_deserves_vote_unique"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deserves_votes_contest_id", "deserves_votes", ["contest_id"])
    op.create_index("ix_deserves_votes_voter_id", "deserves_votes", ["voter_id"])

    # Quiz contests
    op.create_table(
        "quiz_contests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("group_id", sa.BigInteger(), nullable=True),
        sa.Column("text_raw", sa.Text(), nullable=False),
        sa.Column("text_style", sa.String(length=16), nullable=False, server_default="plain"),
        sa.Column("winners_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("question_interval", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("require_subscription", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("anti_bot_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("exclude_leavers", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("premium_only", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("current_question", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quiz_contests_owner_id", "quiz_contests", ["owner_id"])
    op.create_index("ix_quiz_contests_channel_id", "quiz_contests", ["channel_id"])
    op.create_index("ix_quiz_contests_group_id", "quiz_contests", ["group_id"])

    # Quiz questions
    op.create_table(
        "quiz_questions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contest_id", sa.Integer(), nullable=False),
        sa.Column("question_number", sa.Integer(), nullable=False),
        sa.Column("text_raw", sa.Text(), nullable=False),
        sa.Column("correct_answer", sa.String(length=256), nullable=False),
        sa.Column("time_limit", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["contest_id"], ["quiz_contests.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("contest_id", "question_number", name="uq_quiz_contest_question"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quiz_questions_contest_id", "quiz_questions", ["contest_id"])

    # Quiz answers
    op.create_table(
        "quiz_answers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contest_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("answer_text", sa.String(length=256), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("answered_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["contest_id"], ["quiz_contests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["quiz_questions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("question_id", "user_id", name="uq_quiz_question_user"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quiz_answers_contest_id", "quiz_answers", ["contest_id"])
    op.create_index("ix_quiz_answers_user_id", "quiz_answers", ["user_id"])

    # Quiz participant scores
    op.create_table(
        "quiz_participant_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contest_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_answers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["contest_id"], ["quiz_contests.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("contest_id", "user_id", name="uq_quiz_contest_user_score"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quiz_participant_scores_contest_id", "quiz_participant_scores", ["contest_id"])
    op.create_index("ix_quiz_participant_scores_user_id", "quiz_participant_scores", ["user_id"])

    # Referrals
    op.create_table(
        "referrals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("referrer_id", sa.BigInteger(), nullable=False),
        sa.Column("referred_id", sa.BigInteger(), nullable=False),
        sa.Column("referral_code", sa.String(length=32), nullable=False),
        sa.Column("points_earned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["referrer_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("referred_id", name="uq_referred_user"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_referrals_referrer_id", "referrals", ["referrer_id"])
    op.create_index("ix_referrals_referral_code", "referrals", ["referral_code"])


def downgrade() -> None:
    op.drop_table("referrals")
    op.drop_table("quiz_participant_scores")
    op.drop_table("quiz_answers")
    op.drop_table("quiz_questions")
    op.drop_table("quiz_contests")
    op.drop_table("deserves_votes")
    op.drop_table("deserves_candidates")
    op.drop_table("deserves_contests")
    op.drop_table("voting_votes")
    op.drop_table("voting_candidates")
    op.drop_table("voting_contests")
    op.drop_table("subscriptions")