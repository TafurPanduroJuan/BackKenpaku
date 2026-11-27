"""Claims thread and deadline support (Ley 29571).

Revision ID: 013
Revises: 012
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("claims", sa.Column("fecha_limite", sa.DateTime(timezone=True), nullable=True))
    op.add_column("claims", sa.Column("fecha_atencion", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "claim_messages",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "claim_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("claims.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("autor", sa.String(length=20), nullable=False),
        sa.Column("canal", sa.String(length=20), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_claim_messages_claim_id", "claim_messages", ["claim_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_claim_messages_claim_id", table_name="claim_messages")
    op.drop_table("claim_messages")
    op.drop_column("claims", "fecha_atencion")
    op.drop_column("claims", "fecha_limite")
