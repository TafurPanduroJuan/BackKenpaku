"""Track product-list imports and asynchronous embedding status.

Revision ID: 006
Revises: 005
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_import_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usuario_email", sa.String(length=150), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=True),
        sa.Column("nuevos", sa.Integer(), server_default="0", nullable=False),
        sa.Column("actualizados", sa.Integer(), server_default="0", nullable=False),
        sa.Column("errores", sa.Integer(), server_default="0", nullable=False),
        sa.Column("indexing_status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("indexing_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("indexing_completed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("indexing_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_import_history_created_at",
        "product_import_history",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_import_history_created_at", table_name="product_import_history")
    op.drop_table("product_import_history")