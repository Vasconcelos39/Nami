"""ajustes do admin em obras de fora

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-25 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('ajuste_obra',
    sa.Column('fonte_id', sa.String(length=32), nullable=False),
    sa.Column('obra_id', sa.String(length=64), nullable=False),
    sa.Column('titulo_original', sa.String(length=300), nullable=False),
    sa.Column('bloqueada', sa.Boolean(), nullable=False),
    sa.Column('classificacao', sa.String(length=15), nullable=True),
    sa.Column('titulo', sa.String(length=300), nullable=True),
    sa.Column('descricao', sa.Text(), nullable=True),
    sa.Column('capa', sa.Boolean(), nullable=False),
    sa.Column('motivo', sa.String(length=500), nullable=True),
    sa.Column('atualizado_em', sa.DateTime(), nullable=False),
    sa.CheckConstraint("classificacao IS NULL OR classificacao IN ('safe', 'suggestive', 'erotica', 'pornographic')", name=op.f('ck_ajuste_obra_classificacao')),
    sa.PrimaryKeyConstraint('fonte_id', 'obra_id', name=op.f('pk_ajuste_obra'))
    )
    op.create_table('capitulo_oculto',
    sa.Column('fonte_id', sa.String(length=32), nullable=False),
    sa.Column('capitulo_id', sa.String(length=64), nullable=False),
    sa.Column('obra_id', sa.String(length=64), nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('fonte_id', 'capitulo_id', name=op.f('pk_capitulo_oculto'))
    )
    op.create_index('ix_capitulo_oculto_obra', 'capitulo_oculto', ['fonte_id', 'obra_id'], unique=False)
    op.create_table('capitulo_extra',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('fonte_id', sa.String(length=32), nullable=False),
    sa.Column('obra_id', sa.String(length=64), nullable=False),
    sa.Column('numero', sa.String(length=20), nullable=True),
    sa.Column('volume', sa.String(length=20), nullable=True),
    sa.Column('titulo', sa.String(length=300), nullable=True),
    sa.Column('idioma', sa.String(length=10), nullable=False),
    sa.Column('total_paginas', sa.Integer(), nullable=False),
    sa.Column('pasta', sa.String(length=100), nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_capitulo_extra'))
    )
    op.create_index('ix_capitulo_extra_obra', 'capitulo_extra', ['fonte_id', 'obra_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_capitulo_extra_obra', table_name='capitulo_extra')
    op.drop_table('capitulo_extra')
    op.drop_index('ix_capitulo_oculto_obra', table_name='capitulo_oculto')
    op.drop_table('capitulo_oculto')
    op.drop_table('ajuste_obra')
