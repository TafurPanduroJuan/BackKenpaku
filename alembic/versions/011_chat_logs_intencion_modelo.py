"""Predicción del modelo de intención (APF3) en chat_logs.

Agrega dos columnas NULLABLE (no rompe filas existentes ni requiere valores por defecto):
  - intencion_modelo     INTEGER  0 consulta, 1 cotización, 2 reclamo, 3 compra
  - probabilidad_modelo  FLOAT    confianza del modelo (0 a 1)

`intencion_etiquetada` se conserva: es la regla de palabras clave del MVP (línea base de comparación).

Es idempotente: si la columna ya existe (p. ej. se agregó a mano en la BD de Render) no la vuelve a crear.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columnas() -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("chat_logs")}


def upgrade() -> None:
    existentes = _columnas()
    if "intencion_modelo" not in existentes:
        op.add_column("chat_logs", sa.Column("intencion_modelo", sa.Integer(), nullable=True))
    if "probabilidad_modelo" not in existentes:
        op.add_column("chat_logs", sa.Column("probabilidad_modelo", sa.Float(), nullable=True))


def downgrade() -> None:
    existentes = _columnas()
    if "probabilidad_modelo" in existentes:
        op.drop_column("chat_logs", "probabilidad_modelo")
    if "intencion_modelo" in existentes:
        op.drop_column("chat_logs", "intencion_modelo")
