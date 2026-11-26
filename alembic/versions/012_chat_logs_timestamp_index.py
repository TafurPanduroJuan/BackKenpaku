"""Indices de optimización para purga y consultas en chat_logs.

Crea los índices:
  - ix_chat_logs_timestamp sobre la columna 'timestamp'
  - ix_chat_logs_conv_timestamp sobre las columnas ('id_conversacion', 'timestamp')

Es idempotente: comprueba si el índice ya existe antes de crearlo.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _indices() -> set:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("chat_logs")}


def upgrade() -> None:
    existentes = _indices()
    if "ix_chat_logs_timestamp" not in existentes:
        op.create_index("ix_chat_logs_timestamp", "chat_logs", ["timestamp"], unique=False)
    if "ix_chat_logs_conv_timestamp" not in existentes:
        op.create_index(
            "ix_chat_logs_conv_timestamp",
            "chat_logs",
            ["id_conversacion", "timestamp"],
            unique=False,
        )


def downgrade() -> None:
    existentes = _indices()
    if "ix_chat_logs_conv_timestamp" in existentes:
        op.drop_index("ix_chat_logs_conv_timestamp", table_name="chat_logs")
    if "ix_chat_logs_timestamp" in existentes:
        op.drop_index("ix_chat_logs_timestamp", table_name="chat_logs")
