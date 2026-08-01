"""граница возраста новостей

Revision ID: c9e14b73f082
Revises: b3d5027ac914
"""

from alembic import op
import sqlalchemy as sa

revision = "c9e14b73f082"
down_revision = "b3d5027ac914"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fetch_settings",
        sa.Column("min_published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("fetch_settings", sa.Column("max_age_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("fetch_settings", "max_age_days")
    op.drop_column("fetch_settings", "min_published_at")
