"""главная картинка и обложки роликов

Revision ID: f2b6d81e45c7
Revises: e5a91c73b208
"""

from alembic import op
import sqlalchemy as sa

revision = "f2b6d81e45c7"
down_revision = "e5a91c73b208"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "article_images",
        sa.Column("is_cover", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "article_images",
        sa.Column("from_video", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # Уже отмеченные обложки роликов: их клали в галерею, когда своих
    # картинок у статьи не было
    op.execute(
        """
        UPDATE article_images
        SET from_video = true
        WHERE url LIKE '%img.youtube.com/vi/%'
           OR url LIKE '%i.ytimg.com/vi/%'
        """
    )

    # Главной делаем первую отмеченную картинку каждой статьи: до сих пор
    # порядок и так задавался позицией, поведение не меняется
    op.execute(
        """
        UPDATE article_images AS ai
        SET is_cover = true
        FROM (
            SELECT DISTINCT ON (article_id) id
            FROM article_images
            WHERE is_selected
            ORDER BY article_id, position
        ) AS first_selected
        WHERE ai.id = first_selected.id
        """
    )

    op.alter_column("article_images", "is_cover", server_default=None)
    op.alter_column("article_images", "from_video", server_default=None)


def downgrade() -> None:
    op.drop_column("article_images", "from_video")
    op.drop_column("article_images", "is_cover")
