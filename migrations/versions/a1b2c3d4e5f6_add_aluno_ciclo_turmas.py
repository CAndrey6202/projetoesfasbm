"""add_aluno_ciclo_turmas

Revision ID: a1b2c3d4e5f6
Revises: 55dc3e14f405
Create Date: 2026-10-21 17:25:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '55dc3e14f405'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('aluno_ciclo_turmas'):
        op.create_table(
            'aluno_ciclo_turmas',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('aluno_id', sa.Integer(), nullable=False),
            sa.Column('ciclo_id', sa.Integer(), nullable=False),
            sa.Column('turma_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['aluno_id'], ['alunos.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['ciclo_id'], ['ciclos.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['turma_id'], ['turmas.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('aluno_id', 'ciclo_id', name='uq_aluno_ciclo_turma')
        )
        op.create_index('ix_aluno_ciclo_turmas_aluno_id', 'aluno_ciclo_turmas', ['aluno_id'], unique=False)
        op.create_index('ix_aluno_ciclo_turmas_ciclo_id', 'aluno_ciclo_turmas', ['ciclo_id'], unique=False)
        op.create_index('ix_aluno_ciclo_turmas_turma_id', 'aluno_ciclo_turmas', ['turma_id'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table('aluno_ciclo_turmas'):
        op.drop_index('ix_aluno_ciclo_turmas_turma_id', table_name='aluno_ciclo_turmas')
        op.drop_index('ix_aluno_ciclo_turmas_ciclo_id', table_name='aluno_ciclo_turmas')
        op.drop_index('ix_aluno_ciclo_turmas_aluno_id', table_name='aluno_ciclo_turmas')
        op.drop_table('aluno_ciclo_turmas')
