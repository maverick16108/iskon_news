"""состояние подключения к модели

Revision ID: f4c9a1e7503b
Revises: e6b208c14a37
"""

from alembic import op
import sqlalchemy as sa

revision = "f4c9a1e7503b"
down_revision = "e6b208c14a37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_settings", sa.Column("last_ok_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("llm_settings", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column(
        "llm_settings", sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "llm_settings",
        sa.Column("out_of_money", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("llm_settings", "out_of_money", server_default=None)


def downgrade() -> None:
    op.drop_column("llm_settings", "out_of_money")
    op.drop_column("llm_settings", "last_error_at")
    op.drop_column("llm_settings", "last_error")
    op.drop_column("llm_settings", "last_ok_at")
