"""Add configurable inch/mm equivalences."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DIMENSION_DEFAULTS = (
    ("1/2", 12, 13),
    ("3/4", 19, 21),
    ("1", 24, 26),
    ("1 1/4", 30, 32),
    ("1 1/2", 38, 40),
    ("2", 49, 51),
    ("2 1/2", 60, 64),
    ("3", 74, 76),
    ("4", 99, 101),
)
_THICKNESS_DEFAULTS = (
    ("1/16", 1.4, 1.6),
    ("1/8", 2.9, 3.1),
    ("3/16", 4.4, 4.6),
    ("1/4", 5.9, 6.1),
)


def upgrade() -> None:
    op.create_table(
        "measurement_equivalences",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tipo_medida", sa.String(length=20), nullable=False),
        sa.Column("pulgada", sa.String(length=20), nullable=False),
        sa.Column("mm_minimo", sa.Numeric(8, 3), nullable=False),
        sa.Column("mm_maximo", sa.Numeric(8, 3), nullable=False),
        sa.Column("categoria", sa.String(length=50), nullable=True),
        sa.Column(
            "tolerancia_mm",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="1.5",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column(
        "quote_items",
        sa.Column("equivalencia_nota", sa.String(length=200), nullable=True),
    )
    table = sa.table(
        "measurement_equivalences",
        sa.column("tipo_medida", sa.String),
        sa.column("pulgada", sa.String),
        sa.column("mm_minimo", sa.Numeric),
        sa.column("mm_maximo", sa.Numeric),
        sa.column("categoria", sa.String),
        sa.column("tolerancia_mm", sa.Numeric),
    )
    op.bulk_insert(
        table,
        [
            {
                "tipo_medida": kind,
                "pulgada": inch,
                "mm_minimo": minimum,
                "mm_maximo": maximum,
                "categoria": None,
                "tolerancia_mm": 1.5,
            }
            for kind, defaults in (
                ("dimension", _DIMENSION_DEFAULTS),
                ("espesor", _THICKNESS_DEFAULTS),
            )
            for inch, minimum, maximum in defaults
        ],
    )


def downgrade() -> None:
    op.drop_column("quote_items", "equivalencia_nota")
    op.drop_table("measurement_equivalences")
