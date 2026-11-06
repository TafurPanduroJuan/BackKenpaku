"""Add category-specific product fields.

Revision ID: 008
Revises: 007
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("tipo", sa.String(length=100), nullable=True))
    op.add_column("products", sa.Column("forma", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "forma")
    op.drop_column("products", "tipo")
