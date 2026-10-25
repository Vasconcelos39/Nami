"""verificação de idade

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ADD COLUMN simples, sem batch: o batch recriaria a tabela e perderia o
    # COLLATE NOCASE do username ("Ana" e "ana" virariam contas diferentes).
    op.add_column('usuario', sa.Column('adulto_bloqueado', sa.Boolean(), nullable=False, server_default=sa.false()))
    # A confirmação antiga era só uma caixinha. Quem tinha ligado o +18 passa
    # pela verificação nova (data de nascimento + senha) pra ligar de novo.
    op.execute("UPDATE usuario SET maioridade_confirmada_em = NULL, mostrar_adulto = 0")


def downgrade() -> None:
    # Pelo mesmo motivo, DROP COLUMN direto (SQLite 3.35 ou mais novo).
    op.execute("ALTER TABLE usuario DROP COLUMN adulto_bloqueado")
