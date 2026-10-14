"""phase5_cron

Revision ID: 002
Revises: 001
Create Date: 2026-03-30 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    existing_product_cols = [c['name'] for c in inspector.get_columns('products')]
    existing_order_cols = [c['name'] for c in inspector.get_columns('orders')]

    # Columna stock_reservado en products
    if 'stock_reservado' not in existing_product_cols:
        op.add_column(
            'products',
            sa.Column('stock_reservado', sa.Integer(), nullable=False, server_default='0')
        )

    # Columnas de timeout y recordatorios en orders
    if 'fecha_limite_pago' not in existing_order_cols:
        op.add_column(
            'orders',
            sa.Column('fecha_limite_pago', sa.DateTime(timezone=True), nullable=True)
        )
    if 'recordatorio_enviado' not in existing_order_cols:
        op.add_column(
            'orders',
            sa.Column('recordatorio_enviado', sa.Boolean(), nullable=False, server_default='false')
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    existing_product_cols = [c['name'] for c in inspector.get_columns('products')]
    existing_order_cols = [c['name'] for c in inspector.get_columns('orders')]

    if 'recordatorio_enviado' in existing_order_cols:
        op.drop_column('orders', 'recordatorio_enviado')
    if 'fecha_limite_pago' in existing_order_cols:
        op.drop_column('orders', 'fecha_limite_pago')
    if 'stock_reservado' in existing_product_cols:
        op.drop_column('products', 'stock_reservado')