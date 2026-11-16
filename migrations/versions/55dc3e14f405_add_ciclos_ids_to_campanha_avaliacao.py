"""add_ciclos_ids_to_campanha_avaliacao

Revision ID: 55dc3e14f405
Revises: 999999999999
Create Date: 2026-10-14 13:20:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '55dc3e14f405'
down_revision = '999999999999'
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table('campanhas_avaliacao'):
        cols = [c['name'] for c in inspector.get_columns('campanhas_avaliacao')]
        if 'ciclos_ids' not in cols:
            op.add_column('campanhas_avaliacao', sa.Column('ciclos_ids', sa.String(length=255), nullable=True))

def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table('campanhas_avaliacao'):
        cols = [c['name'] for c in inspector.get_columns('campanhas_avaliacao')]
        if 'ciclos_ids' in cols:
            op.drop_column('campanhas_avaliacao', 'ciclos_ids')
