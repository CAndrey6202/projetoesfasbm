"""add_data_inicio_campanha_avaliacao

Revision ID: f42285721447
Revises: 7fe2da43c113
Create Date: 2026-08-25 12:13:53.007681

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f42285721447'
down_revision = '7fe2da43c113'
branch_labels = None
depends_on = None


def upgrade():
    # Adicionando data_inicio à tabela campanhas_avaliacao
    with op.batch_alter_table('campanhas_avaliacao') as batch_op:
        batch_op.add_column(sa.Column('data_inicio', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False))

def downgrade():
    with op.batch_alter_table('campanhas_avaliacao') as batch_op:
        batch_op.drop_column('data_inicio')
