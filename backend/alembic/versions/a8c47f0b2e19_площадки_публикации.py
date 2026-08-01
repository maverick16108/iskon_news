"""площадки публикации

Revision ID: a8c47f0b2e19
Revises: f2b6d81e45c7
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a8c47f0b2e19"
down_revision = "f2b6d81e45c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Тип создаём сами и просим create_table его не трогать: иначе
    # SQLAlchemy выпустит CREATE TYPE второй раз и миграция упадёт
    sa.Enum("telegram", "max", name="platform_kind").create(op.get_bind(), checkfirst=True)
    platform_kind = postgresql.ENUM("telegram", "max", name="platform_kind", create_type=False)

    op.create_table(
        "platforms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", platform_kind, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("token", sa.String(length=255), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("bot_username", sa.String(length=128), nullable=True),
        sa.Column("bot_id", sa.String(length=64), nullable=True),
        sa.Column("last_status", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.add_column("telegram_channels", sa.Column("platform_id", sa.Integer(), nullable=True))
    op.create_index("ix_telegram_channels_platform_id", "telegram_channels", ["platform_id"])
    op.create_foreign_key(
        "fk_telegram_channels_platform",
        "telegram_channels",
        "platforms",
        ["platform_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Переносим то, что уже настроено: до сих пор площадка была ровно одна
    op.execute(
        """
        INSERT INTO platforms (kind, title, token, is_enabled, created_at, updated_at)
        SELECT 'telegram', 'Telegram', bot_token, is_enabled, now(), now()
        FROM telegram_settings
        ORDER BY id
        LIMIT 1
        """
    )
    # Если настроек ещё не было — заводим пустую площадку Telegram,
    # чтобы экран не оказался пустым на новой установке
    op.execute(
        """
        INSERT INTO platforms (kind, title, token, is_enabled, created_at, updated_at)
        SELECT 'telegram', 'Telegram', NULL, false, now(), now()
        WHERE NOT EXISTS (SELECT 1 FROM platforms)
        """
    )

    op.execute(
        """
        UPDATE telegram_channels
        SET platform_id = (SELECT id FROM platforms ORDER BY id LIMIT 1)
        WHERE platform_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_telegram_channels_platform", "telegram_channels", type_="foreignkey")
    op.drop_index("ix_telegram_channels_platform_id", table_name="telegram_channels")
    op.drop_column("telegram_channels", "platform_id")
    op.drop_table("platforms")
    sa.Enum(name="platform_kind").drop(op.get_bind(), checkfirst=True)
