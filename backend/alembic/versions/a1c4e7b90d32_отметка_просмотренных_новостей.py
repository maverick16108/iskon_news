"""отметка просмотренных новостей

Revision ID: a1c4e7b90d32
Revises: 3ad00c25bc93
"""

from alembic import op
import sqlalchemy as sa

revision = "a1c4e7b90d32"
down_revision = "3ad00c25bc93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "article_views",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "viewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id", "user_id", name="uq_article_view"),
    )
    op.create_index("ix_article_views_article_id", "article_views", ["article_id"])
    op.create_index("ix_article_views_user_id", "article_views", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_article_views_user_id", table_name="article_views")
    op.drop_index("ix_article_views_article_id", table_name="article_views")
    op.drop_table("article_views")
