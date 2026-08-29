"""диапазон длины поста

Revision ID: b7d3e91a4c26
Revises: f4c9a1e7503b
"""

from alembic import op
import sqlalchemy as sa

revision = "b7d3e91a4c26"
down_revision = "f4c9a1e7503b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Значения по умолчанию совпадают с прежним поведением: верхняя граница —
    # те же 1000 символов, что были зашиты в коде, нижняя — 600.
    op.add_column(
        "llm_settings",
        sa.Column("post_min_chars", sa.Integer(), nullable=False, server_default="600"),
    )
    op.add_column(
        "llm_settings",
        sa.Column("post_max_chars", sa.Integer(), nullable=False, server_default="1000"),
    )
    op.alter_column("llm_settings", "post_min_chars", server_default=None)
    op.alter_column("llm_settings", "post_max_chars", server_default=None)


def downgrade() -> None:
    op.drop_column("llm_settings", "post_max_chars")
    op.drop_column("llm_settings", "post_min_chars")
