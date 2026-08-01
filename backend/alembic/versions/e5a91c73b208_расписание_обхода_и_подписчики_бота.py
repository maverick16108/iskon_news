"""расписание обхода и подписчики бота

Revision ID: e5a91c73b208
Revises: d7e2b04c9a15
"""

from alembic import op
import sqlalchemy as sa

revision = "e5a91c73b208"
down_revision = "d7e2b04c9a15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fetch_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_result", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "bot_subscribers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("notify", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id"),
    )
    op.create_index("ix_bot_subscribers_chat_id", "bot_subscribers", ["chat_id"])

    op.create_table(
        "bot_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("update_offset", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("bot_state")
    op.drop_index("ix_bot_subscribers_chat_id", table_name="bot_subscribers")
    op.drop_table("bot_subscribers")
    op.drop_table("fetch_settings")
