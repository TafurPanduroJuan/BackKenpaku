"""Create immutable quote snapshots and line items.

Revision ID: 007
Revises: 006
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quotes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("codigo", sa.String(length=18), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("igv", sa.Numeric(12, 2), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("tipo_cambio_usado", sa.Numeric(12, 6), nullable=True),
        sa.Column("fecha_emision", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valida_hasta", sa.DateTime(timezone=True), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("parent_codigo", sa.String(length=18), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["parent_codigo"], ["quotes.codigo"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("codigo"),
    )
    op.create_index("ix_quotes_codigo", "quotes", ["codigo"], unique=True)
    op.create_index("ix_quotes_conversation_id", "quotes", ["conversation_id"])

    op.create_table(
        "quote_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("texto_original", sa.Text(), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("nombre_snapshot", sa.String(length=200), nullable=False),
        sa.Column("medida_snapshot", sa.String(length=100), nullable=True),
        sa.Column("cantidad", sa.Numeric(12, 3), nullable=False),
        sa.Column("unidad", sa.String(length=40), nullable=True),
        sa.Column("cantidad_asumida", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("precio_unitario_snapshot", sa.Numeric(10, 2), nullable=True),
        sa.Column("subtotal_linea", sa.Numeric(12, 2), nullable=True),
        sa.Column("estado_linea", sa.String(length=20), nullable=False),
        sa.Column("opciones_json", sa.JSON(), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quote_items_quote_id", "quote_items", ["quote_id"])


def downgrade() -> None:
    op.drop_index("ix_quote_items_quote_id", table_name="quote_items")
    op.drop_table("quote_items")
    op.drop_index("ix_quotes_conversation_id", table_name="quotes")
    op.drop_index("ix_quotes_codigo", table_name="quotes")
    op.drop_table("quotes")