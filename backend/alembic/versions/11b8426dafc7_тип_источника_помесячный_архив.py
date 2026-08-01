"""Тип источника: помесячный архив

Revision ID: 11b8426dafc7
Revises: da8c5f8ffe65
Create Date: 2026-08-01 10:40:55.443106

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '11b8426dafc7'
down_revision: Union[str, None] = 'da8c5f8ffe65'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Alembic не отслеживает значения enum в PostgreSQL — добавляем вручную.
    # IF NOT EXISTS делает миграцию безопасной при повторном прогоне.
    op.execute("ALTER TYPE source_kind ADD VALUE IF NOT EXISTS 'archive'")


def downgrade() -> None:
    # Значение из enum в PostgreSQL не удаляется без пересоздания типа.
    # Источники этого типа при откате перестанут читаться — пересоздавать
    # тип ради отката не станем, он потребовал бы блокировки таблицы.
    pass
