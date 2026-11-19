"""add data_prova to recursos

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-19 12:51:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table('recursos'):
        cols = [c['name'] for c in insp.get_columns('recursos')]
        if 'data_prova' not in cols:
            op.add_column('recursos', sa.Column('data_prova', sa.String(length=50), nullable=True))


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table('recursos'):
        cols = [c['name'] for c in insp.get_columns('recursos')]
        if 'data_prova' in cols:
            op.drop_column('recursos', 'data_prova')
