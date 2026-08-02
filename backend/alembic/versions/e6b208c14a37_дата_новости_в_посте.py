"""дата новости в посте

Revision ID: e6b208c14a37
Revises: d1a73e59c806
"""

from alembic import op
import sqlalchemy as sa

revision = "e6b208c14a37"
down_revision = "d1a73e59c806"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("source_date", sa.DateTime(timezone=True), nullable=True))
    # Уже собранным постам проставляем дату их статьи
    op.execute(
        """
        UPDATE posts SET source_date = articles.published_at
        FROM articles WHERE articles.id = posts.article_id
        """
    )


def downgrade() -> None:
    op.drop_column("posts", "source_date")
