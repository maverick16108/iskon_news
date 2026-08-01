"""отметка последней сводки

Revision ID: d1a73e59c806
Revises: c9e14b73f082
"""

from alembic import op
import sqlalchemy as sa

revision = "d1a73e59c806"
down_revision = "c9e14b73f082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fetch_settings",
        sa.Column("last_reported_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Чтобы первая же сводка не перечислила всё, что накопилось за всё время
    op.execute("UPDATE fetch_settings SET last_reported_at = now()")


def downgrade() -> None:
    op.drop_column("fetch_settings", "last_reported_at")
