"""área madura

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-25 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sessao', sa.Column('madura_ate', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.execute("ALTER TABLE sessao DROP COLUMN madura_ate")
