"""Add supplier costs, pricing settings, and exchange-rate history.

Revision ID: 005
Revises: 004
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("sku", sa.String(length=100), nullable=True))
    op.add_column("products", sa.Column("precio_base_usd", sa.Numeric(12, 4), nullable=True))
    op.add_column("products", sa.Column("margen_pct", sa.Numeric(7, 3), nullable=True))
    op.create_index("ix_products_sku", "products", ["sku"], unique=True)

    op.create_table(
        "exchange_rates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("moneda", sa.String(length=3), nullable=False),
        sa.Column("valor_venta", sa.Numeric(12, 6), nullable=False),
        sa.Column("fuente", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_exchange_rates_fecha", "exchange_rates", ["fecha"])

    op.create_table(
        "pricing_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("margen_global_pct", sa.Numeric(7, 3), nullable=False),
        sa.Column("costo_incluye_igv", sa.Boolean(), nullable=False),
        sa.Column("redondeo", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "margen_por_categoria",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("categoria", sa.String(length=50), nullable=False),
        sa.Column("margen_pct", sa.Numeric(7, 3), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("categoria"),
    )
    op.execute(
        sa.text(
            "INSERT INTO pricing_settings "
            "(id, margen_global_pct, costo_incluye_igv, redondeo) "
            "VALUES (1, 20.000, false, 5)"
        )
    )


def downgrade() -> None:
    op.drop_table("margen_por_categoria")
    op.drop_table("pricing_settings")
    op.drop_index("ix_exchange_rates_fecha", table_name="exchange_rates")
    op.drop_table("exchange_rates")
    op.drop_index("ix_products_sku", table_name="products")
    op.drop_column("products", "margen_pct")
    op.drop_column("products", "precio_base_usd")
    op.drop_column("products", "sku")