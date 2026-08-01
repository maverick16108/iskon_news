"""повторы новостей и дайджесты

Revision ID: c3f81a52d7b4
Revises: a1c4e7b90d32
"""

from alembic import op
import sqlalchemy as sa

revision = "c3f81a52d7b4"
down_revision = "a1c4e7b90d32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Alembic не умеет добавлять значение в существующий enum сам
    op.execute("ALTER TYPE source_kind ADD VALUE IF NOT EXISTS 'newsletter'")

    op.add_column("articles", sa.Column("title_key", sa.String(length=512), nullable=True))
    op.create_index("ix_articles_title_key", "articles", ["title_key"])

    op.create_table(
        "article_mentions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=True),
        sa.Column(
            "seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id", "source_id", name="uq_article_mention"),
    )
    op.create_index("ix_article_mentions_article_id", "article_mentions", ["article_id"])
    op.create_index("ix_article_mentions_source_id", "article_mentions", ["source_id"])

    # Ключи заголовков для уже собранных статей: без этого повторы среди
    # старых новостей не подсветятся, пока их кто-нибудь не перезаберёт.
    op.execute(
        r"""
        UPDATE articles
        SET title_key = left(regexp_replace(lower(title), '[^0-9a-zа-яё]+', '', 'g'), 512)
        """
    )

    # Источник, из которого статья пришла, — тоже упоминание
    op.execute(
        """
        INSERT INTO article_mentions (article_id, source_id, url, seen_at)
        SELECT id, source_id, url, fetched_at FROM articles
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_article_mentions_source_id", table_name="article_mentions")
    op.drop_index("ix_article_mentions_article_id", table_name="article_mentions")
    op.drop_table("article_mentions")
    op.drop_index("ix_articles_title_key", table_name="articles")
    op.drop_column("articles", "title_key")
    # Значение enum обратно не убираем: PostgreSQL этого не умеет
