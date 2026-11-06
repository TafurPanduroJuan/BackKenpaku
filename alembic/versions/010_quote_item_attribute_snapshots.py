"""Store quote-line measurement and finish snapshots."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "quote_items",
        sa.Column("espesor_snapshot", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "quote_items",
        sa.Column("acabado_snapshot", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("quote_items", "acabado_snapshot")
    op.drop_column("quote_items", "espesor_snapshot")
