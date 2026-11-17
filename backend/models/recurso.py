# backend/models/recurso.py

from .database import db
from datetime import datetime, timezone, timedelta

class DisciplinaHabilitada(db.Model):
    """
    Tabela para registrar quais disciplinas o administrador marcou 
    como tendo provas habilitadas para recursos.
    """
    __tablename__ = 'recurso_disciplinas_habilitadas'
    id = db.Column(db.Integer, primary_key=True)
    disciplina_id = db.Column(db.Integer, db.ForeignKey('disciplinas.id'), unique=True, nullable=False)
    
    # Relacionamento para acessar os dados da disciplina original
    disciplina = db.relationship('Disciplina', backref=db.backref('habilitacao_recurso', uselist=False, cascade='all, delete-orphan'))

class ProvaRecurso(db.Model):
    """
    Tabela para armazenar as Provas criadas pelo Administrador 
    dentro de uma Disciplina para recebimento de Recursos.
    """
    __tablename__ = 'provas_recurso'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    disciplina_id = db.Column(db.Integer, db.ForeignKey('disciplinas.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = db.Column(db.Boolean, default=True)

    # Relacionamentos
    disciplina = db.relationship('Disciplina', backref=db.backref('provas_recurso', lazy=True))
    recursos = db.relationship('Recurso', backref='prova', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<ProvaRecurso {self.nome} - Disciplina ID {self.disciplina_id}>'


class Recurso(db.Model):
    """
    Tabela para armazenar os recursos enviados pelos Alunos 
    vinculados a uma Prova e a uma Questão.
    """
    __tablename__ = 'recursos'

    id = db.Column(db.Integer, primary_key=True)
    prova_id = db.Column(db.Integer, db.ForeignKey('provas_recurso.id'), nullable=False)
    aluno_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Dados preenchidos pelo aluno
    questao_texto = db.Column(db.Text, nullable=False)
    argumentacao_texto = db.Column(db.Text, nullable=True)
    arquivo_anexo = db.Column(db.String(255), nullable=True) # Armazena o nome/caminho do PDF ou Word
    
    # Dados de controle da administração
    status = db.Column(db.String(50), default='Pendente') # Valores sugeridos: Pendente, Em Análise, Deferido, Indeferido
    resposta_admin = db.Column(db.Text, nullable=True)
    
    # Assinaturas e Workflow de aprovação
    instrutor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    instrutor2_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    parecer_instrutor = db.Column(db.Text, nullable=True)
    parecer_instrutor2 = db.Column(db.Text, nullable=True)
    decisao_comandante = db.Column(db.Text, nullable=True)
    
    assinatura_aluno = db.Column(db.Text, nullable=True)
    assinatura_instrutor = db.Column(db.Text, nullable=True)
    assinatura_comandante = db.Column(db.Text, nullable=True)
    
    aluno_ciente = db.Column(db.Boolean, default=False)
    aluno_ciente_data = db.Column(db.DateTime, nullable=True)
    aluno_ciente_ip = db.Column(db.String(50), nullable=True)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relacionamentos (a relação 'prova' já vem do backref de ProvaRecurso)
    aluno = db.relationship('User', foreign_keys=[aluno_id], backref=db.backref('meus_recursos', lazy=True))
    instrutor = db.relationship('User', foreign_keys=[instrutor_id], backref=db.backref('recursos_encaminhados', lazy=True))
    instrutor2 = db.relationship('User', foreign_keys=[instrutor2_id], backref=db.backref('recursos_encaminhados2', lazy=True))

    @property
    def instrutor_em_posse_nome(self) -> str:
        def _fmt(u):
            if not u:
                return ""
            posto = (u.posto_graduacao or "").strip()
            nome = (u.nome_completo or u.nome_de_guerra or "").strip()
            return f"{posto} {nome}".strip()

        nomes = []
        falta_1 = self.instrutor is not None and not self.parecer_instrutor
        falta_2 = self.instrutor2 is not None and not self.parecer_instrutor2

        if falta_1:
            nomes.append(_fmt(self.instrutor))
        if falta_2:
            nomes.append(_fmt(self.instrutor2))

        if not nomes:
            if self.instrutor:
                nomes.append(_fmt(self.instrutor))
            elif self.instrutor2:
                nomes.append(_fmt(self.instrutor2))

        return " / ".join([n for n in nomes if n])

    @property
    def prazo_atual(self):
        """
        Calcula o prazo limite da etapa atual do recurso:
        - Pendente / Em Análise (enviado pelo aluno): 24h
        - Com Instrutor (enviado para parecer do instrutor): 48h
        - Retornado ao Admin (Parecer) / Com Comandante (voltou do instrutor): 24h
        """
        if self.status in ['Deferido', 'Indeferido', 'Anulado']:
            return None

        base_dt = self.updated_at or self.created_at
        if not base_dt:
            return None

        if base_dt.tzinfo is None:
            base_dt = base_dt.replace(tzinfo=timezone.utc)

        if self.status in ['Pendente', 'Em Análise']:
            return base_dt + timedelta(hours=24)
        elif self.status == 'Com Instrutor':
            return base_dt + timedelta(hours=48)
        elif self.status in ['Retornado ao Admin (Parecer)', 'Com Comandante']:
            return base_dt + timedelta(hours=24)
        return None

    @property
    def prazo_atual_iso(self) -> str:
        dt = self.prazo_atual
        return dt.isoformat() if dt else ""

    def __repr__(self):
        return f'<Recurso {self.id} - Prova ID {self.prova_id} - Aluno ID {self.aluno_id}>'