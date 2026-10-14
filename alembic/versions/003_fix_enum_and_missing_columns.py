"""fix_enum_and_missing_columns

Revision ID: 003_fix_enum_and_missing_columns
Revises: 002_phase5_cron
Create Date: 2026-04-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = '003_fix_enum_and_missing_columns'
down_revision = '002_phase5_cron'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    existing_cols = [c['name'] for c in inspector.get_columns('orders')]

    # 1. Agregar valores faltantes al ENUM orderestadoenum si no existen
    enum_values = ['flete_cotizado', 'despachado', 'listo_para_recojo']
    for val in enum_values:
        op.execute(sa.text(f"ALTER TYPE orderestadoenum ADD VALUE IF NOT EXISTS '{val}'"))

    # 2. Agregar columnas faltantes en orders de forma segura e idempotente
    if 'costo_flete' not in existing_cols:
        op.add_column('orders', sa.Column('costo_flete', sa.Numeric(10, 2), nullable=True))

    if 'estado_flete' not in existing_cols:
        op.add_column('orders', sa.Column('estado_flete', sa.String(length=50), nullable=True))

    if 'tracking_token' not in existing_cols:
        op.add_column('orders', sa.Column('tracking_token', sa.String(length=100), nullable=True))

    if 'fecha_pago' not in existing_cols:
        op.add_column('orders', sa.Column('fecha_pago', sa.DateTime(timezone=True), nullable=True))

    if 'voucher_referencia' not in existing_cols:
        op.add_column('orders', sa.Column('voucher_referencia', sa.String(length=100), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    existing_cols = [c['name'] for c in inspector.get_columns('orders')]

    if 'voucher_referencia' in existing_cols:
        op.drop_column('orders', 'voucher_referencia')
    if 'fecha_pago' in existing_cols:
        op.drop_column('orders', 'fecha_pago')
    if 'tracking_token' in existing_cols:
        op.drop_column('orders', 'tracking_token')
    if 'estado_flete' in existing_cols:
        op.drop_column('orders', 'estado_flete')
    if 'costo_flete' in existing_cols:
        op.drop_column('orders', 'costo_flete')