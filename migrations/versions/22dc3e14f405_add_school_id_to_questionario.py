"""add school_id to questionario

Revision ID: 22dc3e14f405
Revises: 11dc3e14f405
Create Date: 2026-08-14 08:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '22dc3e14f405'
down_revision = '11dc3e14f405'
branch_labels = None
depends_on = None


def upgrade():
    # Adicionar coluna school_id na tabela questionarios
    with op.batch_alter_table('questionarios', schema=None) as batch_op:
        batch_op.add_column(sa.Column('school_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_questionario_school', 'schools', ['school_id'], ['id'])


def downgrade():
    with op.batch_alter_table('questionarios', schema=None) as batch_op:
        batch_op.drop_constraint('fk_questionario_school', type_='foreignkey')
        batch_op.drop_column('school_id')
