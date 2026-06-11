"""empty baseline

The first revision. It deliberately applies no schema: running it creates only
Alembic's own ``alembic_version`` bookkeeping table, proving the migrate-on-boot
seam works end to end before any real schema depends on it. Domain schema arrives
in P1+.

Revision ID: 0001_empty_baseline
Revises:
Create Date: 2026-06-11

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "0001_empty_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
