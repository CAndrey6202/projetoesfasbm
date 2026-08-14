"""add edicao to campanha

Revision ID: 33dc3e14f405
Revises: 22dc3e14f405
Create Date: 2026-08-14 09:42:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '33dc3e14f405'
down_revision = '22dc3e14f405'
branch_labels = None
depends_on = None

def upgrade():
    # Adicionar a coluna edicao_id na tabela campanhas_avaliacao
    with op.batch_alter_table('campanhas_avaliacao', schema=None) as batch_op:
        batch_op.add_column(sa.Column('edicao_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_campanhas_avaliacao_edicoes', 'edicoes', ['edicao_id'], ['id'])

def downgrade():
    with op.batch_alter_table('campanhas_avaliacao', schema=None) as batch_op:
        batch_op.drop_constraint('fk_campanhas_avaliacao_edicoes', type_='foreignkey')
        batch_op.drop_column('edicao_id')
