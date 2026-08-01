"""видеоролики новостей

Revision ID: d7e2b04c9a15
Revises: c3f81a52d7b4
"""

from alembic import op
import sqlalchemy as sa

revision = "d7e2b04c9a15"
down_revision = "c3f81a52d7b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "article_videos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("video_id", sa.String(length=64), nullable=True),
        sa.Column("thumbnail_url", sa.String(length=1024), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_article_videos_article_id", "article_videos", ["article_id"])


def downgrade() -> None:
    op.drop_index("ix_article_videos_article_id", table_name="article_videos")
    op.drop_table("article_videos")
