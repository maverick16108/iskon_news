"""архивные материалы

Revision ID: b3d5027ac914
Revises: a8c47f0b2e19
"""

from alembic import op
import sqlalchemy as sa

revision = "b3d5027ac914"
down_revision = "a8c47f0b2e19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "articles",
        sa.Column("is_archive", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("articles", sa.Column("content_date", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_articles_is_archive", "articles", ["is_archive"])
    op.alter_column("articles", "is_archive", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_articles_is_archive", table_name="articles")
    op.drop_column("articles", "content_date")
    op.drop_column("articles", "is_archive")
