"""длина поста у каждого шаблона

Revision ID: c4a81f6d92b7
Revises: b7d3e91a4c26

Диапазон длины переезжает из настроек подключения в шаблон промпта.
Шаблон назначается источнику, а у разных сайтов материалы разной величины —
одна пара чисел на всё приложение этого не учитывала.
"""

from alembic import op
import sqlalchemy as sa

revision = "c4a81f6d92b7"
down_revision = "b7d3e91a4c26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "prompt_templates",
        sa.Column("post_min_chars", sa.Integer(), nullable=False, server_default="600"),
    )
    op.add_column(
        "prompt_templates",
        sa.Column("post_max_chars", sa.Integer(), nullable=False, server_default="1000"),
    )

    # Переносим то, что уже задано: иначе после выкладки границы молча
    # вернулись бы к значениям по умолчанию.
    op.execute(
        """
        UPDATE prompt_templates SET
            post_min_chars = s.post_min_chars,
            post_max_chars = s.post_max_chars
        FROM llm_settings s
        """
    )

    op.alter_column("prompt_templates", "post_min_chars", server_default=None)
    op.alter_column("prompt_templates", "post_max_chars", server_default=None)

    op.drop_column("llm_settings", "post_max_chars")
    op.drop_column("llm_settings", "post_min_chars")


def downgrade() -> None:
    op.add_column(
        "llm_settings",
        sa.Column("post_min_chars", sa.Integer(), nullable=False, server_default="600"),
    )
    op.add_column(
        "llm_settings",
        sa.Column("post_max_chars", sa.Integer(), nullable=False, server_default="1000"),
    )
    op.execute(
        """
        UPDATE llm_settings SET
            post_min_chars = p.post_min_chars,
            post_max_chars = p.post_max_chars
        FROM prompt_templates p
        WHERE p.is_default
        """
    )
    op.drop_column("prompt_templates", "post_max_chars")
    op.drop_column("prompt_templates", "post_min_chars")
