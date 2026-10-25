"""novidades

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-25 14:00:00.000000

"""
from datetime import UTC, datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Rascunho do primeiro post, pra quem já usava a Nami: conta o que mudou desde
# a 0.6. Só os admins veem até alguém clicar em "Publicar" no painel.
RASCUNHO_TITULO = "A Nami ganhou um monte de coisa nova"
RASCUNHO_TEXTO = """\
Oi, pessoal! Saiu uma atualização grande. O que mudou:

- **Busca que completa sozinha:** é só começar a digitar o nome da obra que a Nami já mostra as opções, com capa. Dá pra escolher com as setinhas e o Enter.
- **"Só no site oficial":** algumas obras (principalmente as licenciadas, tipo Frieren) não têm nenhum capítulo pra ler aqui, só links pro site oficial. Agora elas aparecem com essa faixa na capa, pra ninguém clicar à toa.
- **Ícone novo** na aba do navegador: a ondinha da Nami.
- **Esta área de Novidades:** quando sair post novo, aparece uma bolinha em "Novidades" no menu.
- Por baixo dos panos: mais proteção contra quem tenta abusar do site.

**Importante pra quem usa o +18:** o jeito de ligar mudou. Agora fica no finalzinho de "Sua conta", em "Verificação de idade", e pede a data de nascimento e a senha da conta. Quem já tinha ligado precisa confirmar de novo.

Achou algum problema ou teve uma ideia? Manda pelo Suporte!"""


def upgrade() -> None:
    op.create_table('noticia',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('titulo', sa.String(length=120), nullable=False),
    sa.Column('texto', sa.Text(), nullable=False),
    sa.Column('autor_id', sa.Integer(), nullable=True),
    sa.Column('publicada_em', sa.DateTime(), nullable=True),
    sa.Column('criada_em', sa.DateTime(), nullable=False),
    sa.Column('atualizada_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['autor_id'], ['usuario.id'], name=op.f('fk_noticia_autor_id_usuario'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_noticia'))
    )
    op.create_index(op.f('ix_noticia_publicada_em'), 'noticia', ['publicada_em'], unique=False)
    # ADD COLUMN simples, sem batch (o batch recriaria a tabela e perderia o COLLATE NOCASE).
    op.add_column('usuario', sa.Column('noticias_vistas_em', sa.DateTime(), nullable=True))

    # Instalação nova (sem nenhuma conta ainda) não precisa saber o que mudou.
    if op.get_bind().execute(sa.text("SELECT count(*) FROM usuario")).scalar():
        agora = datetime.now(UTC).replace(tzinfo=None)
        noticia = sa.table(
            'noticia',
            sa.column('titulo', sa.String), sa.column('texto', sa.Text),
            sa.column('criada_em', sa.DateTime), sa.column('atualizada_em', sa.DateTime),
        )
        op.bulk_insert(noticia, [
            {'titulo': RASCUNHO_TITULO, 'texto': RASCUNHO_TEXTO, 'criada_em': agora, 'atualizada_em': agora},
        ])


def downgrade() -> None:
    op.execute("ALTER TABLE usuario DROP COLUMN noticias_vistas_em")
    op.drop_index(op.f('ix_noticia_publicada_em'), table_name='noticia')
    op.drop_table('noticia')
