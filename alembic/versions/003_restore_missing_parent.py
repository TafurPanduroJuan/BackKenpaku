"""Restore the missing revision identifier referenced by revision 004.

Revision ID: 003
Revises: 003_fix_enum_and_missing_columns
"""
from typing import Sequence, Union

revision: str = "003"
down_revision: Union[str, None] = "003_fix_enum_and_missing_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass