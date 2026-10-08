"""add_periods_16_17_18

Revision ID: 999999999999
Revises: f42285721447
Create Date: 2026-09-24 17:35:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '999999999999'
down_revision = 'f42285721447'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('semanas', sa.Column('mostrar_periodo_16', sa.Boolean(), server_default='0', nullable=False))
    op.add_column('semanas', sa.Column('mostrar_periodo_17', sa.Boolean(), server_default='0', nullable=False))
    op.add_column('semanas', sa.Column('mostrar_periodo_18', sa.Boolean(), server_default='0', nullable=False))

def downgrade():
    op.drop_column('semanas', 'mostrar_periodo_16')
    op.drop_column('semanas', 'mostrar_periodo_17')
    op.drop_column('semanas', 'mostrar_periodo_18')
