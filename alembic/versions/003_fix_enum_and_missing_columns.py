
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '003_fix_enum_and_missing_columns'
down_revision: Union[str, None] = '002_phase5_cron'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        # 1. Añadir valores faltantes al enum orderestadoenum
        check = bind.execute(
            sa.text(
                "SELECT enumlabel FROM pg_enum "
                "JOIN pg_type ON pg_enum.enumtypid = pg_type.oid "
                "WHERE pg_type.typname = 'orderestadoenum'"
            )
        ).fetchall()
        existing_values = {row[0] for row in check}

        new_values = ["flete_cotizado", "despachado", "listo_para_recojo"]
        for val in new_values:
            if val not in existing_values:
                op.execute(
                    sa.text(f"ALTER TYPE orderestadoenum ADD VALUE '{val}'")
                )

    # 2. Añadir columnas faltantes en orders (idempotente)
    inspector = sa.inspect(bind)
    existing_cols = {col["name"] for col in inspector.get_columns("orders")}

    if "costo_flete" not in existing_cols:
        op.add_column("orders", sa.Column("costo_flete", sa.Numeric(10, 2), server_default="0.00", nullable=False))

    if "estado_flete" not in existing_cols:
        op.add_column("orders", sa.Column("estado_flete", sa.String(50), server_default="sin_cotizar", nullable=False))

    if "tracking_token" not in existing_cols:
        op.add_column("orders", sa.Column("tracking_token", sa.String(64), nullable=True))
        op.create_index("ix_orders_tracking_token", "orders", ["tracking_token"], unique=True)

    if "fecha_pago" not in existing_cols:
        op.add_column("orders", sa.Column("fecha_pago", sa.DateTime(timezone=True), nullable=True))

    if "voucher_referencia" not in existing_cols:
        op.add_column("orders", sa.Column("voucher_referencia", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {col["name"] for col in inspector.get_columns("orders")}

    if "voucher_referencia" in existing_cols:
        op.drop_column("orders", "voucher_referencia")
    if "fecha_pago" in existing_cols:
        op.drop_column("orders", "fecha_pago")
    if "tracking_token" in existing_cols:
        op.drop_index("ix_orders_tracking_token", table_name="orders")
        op.drop_column("orders", "tracking_token")
    if "estado_flete" in existing_cols:
        op.drop_column("orders", "estado_flete")
    if "costo_flete" in existing_cols:
        op.drop_column("orders", "costo_flete")