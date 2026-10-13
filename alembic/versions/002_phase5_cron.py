"""Phase 5: Cron and stock reservation columns

Revision ID: 002_phase5_cron
Revises: 001_initial
Create Date: 2026-10-12 20:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '002_phase5_cron'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Agregar columna stock_reservado a products
    op.add_column(
        'products',
        sa.Column('stock_reservado', sa.Integer(), server_default='0', nullable=False)
    )

    # Agregar columnas de automatización a orders
    op.add_column(
        'orders',
        sa.Column('fecha_limite_pago', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'orders',
        sa.Column('recordatorio_enviado', sa.Boolean(), server_default='false', nullable=False)
    )
    op.add_column(
        'orders',
        sa.Column('stock_reservado', sa.Boolean(), server_default='true', nullable=False)
    )


def downgrade() -> None:
    op.drop_column('orders', 'stock_reservado')
    op.drop_column('orders', 'recordatorio_enviado')
    op.drop_column('orders', 'fecha_limite_pago')
    op.drop_column('products', 'stock_reservado')
