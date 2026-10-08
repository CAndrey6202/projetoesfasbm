"""add assinaturas recurso

Revision ID: b04a281525f8
Revises: ff9f811e0c08
Create Date: 2026-07-30 13:38:39.268079

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = 'b04a281525f8'
down_revision = 'a04a281525f8'
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    cols = [c['name'] for c in inspector.get_columns('recursos')]
    if 'assinatura_aluno' not in cols:
        op.add_column('recursos', sa.Column('assinatura_aluno', sa.String(255)))
    if 'assinatura_instrutor' not in cols:
        op.add_column('recursos', sa.Column('assinatura_instrutor', sa.String(255)))
    if 'assinatura_comandante' not in cols:
        op.add_column('recursos', sa.Column('assinatura_comandante', sa.String(255)))
    if 'aluno_ciente' not in cols:
        op.add_column('recursos', sa.Column('aluno_ciente', sa.Boolean))
    if 'aluno_ciente_data' not in cols:
        op.add_column('recursos', sa.Column('aluno_ciente_data', sa.DateTime))
    if 'aluno_ciente_ip' not in cols:
        op.add_column('recursos', sa.Column('aluno_ciente_ip', sa.String(50)))
    
    users_cols = [c['name'] for c in inspector.get_columns('users')]
    if 'foto_perfil' not in users_cols:
        op.add_column('users', sa.Column('foto_perfil', sa.String(255), server_default='default.png', nullable=False))
    if 'assinatura_padrao_path' not in users_cols:
        op.add_column('users', sa.Column('assinatura_padrao_path', sa.String(255)))

def downgrade():
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('assinatura_padrao_path')
        batch_op.drop_column('foto_perfil')
    
    with op.batch_alter_table('recursos') as batch_op:
        batch_op.drop_column('aluno_ciente_ip')
        batch_op.drop_column('aluno_ciente_data')
        batch_op.drop_column('aluno_ciente')
        batch_op.drop_column('assinatura_comandante')
        batch_op.drop_column('assinatura_instrutor')
        batch_op.drop_column('assinatura_aluno')

