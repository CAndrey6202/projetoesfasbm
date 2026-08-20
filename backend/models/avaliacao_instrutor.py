from __future__ import annotations
import typing as t
from datetime import datetime
from .database import db
from sqlalchemy.orm import Mapped, mapped_column, relationship

if t.TYPE_CHECKING:
    from .user import User
    from .turma import Turma
    from .school import School
    from .instrutor import Instrutor
    from .aluno import Aluno
    from .edicao import Edicao

class CampanhaAvaliacao(db.Model):
    __tablename__ = 'campanhas_avaliacao'

    id: Mapped[int] = mapped_column(primary_key=True)
    titulo: Mapped[str] = mapped_column(db.String(200), nullable=False)
    is_ativa: Mapped[bool] = mapped_column(db.Boolean, default=True)
    is_obrigatoria: Mapped[bool] = mapped_column(db.Boolean, default=False)
    data_criacao: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow)
    school_id: Mapped[int] = mapped_column(db.ForeignKey('schools.id'), nullable=False)
    edicao_id: Mapped[t.Optional[int]] = mapped_column(db.ForeignKey('edicoes.id'), nullable=True)

    school: Mapped["School"] = relationship()
    edicao: Mapped[t.Optional["Edicao"]] = relationship()
    respostas_instrutor: Mapped[list["RespostaAvaliacao"]] = relationship(back_populates="campanha", cascade="all, delete-orphan")
    respostas_geral: Mapped[list["RespostaAvaliacaoGeral"]] = relationship(back_populates="campanha", cascade="all, delete-orphan")
    controles_preenchimento: Mapped[list["ControlePreenchimentoAvaliacao"]] = relationship(back_populates="campanha", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<CampanhaAvaliacao id={self.id} titulo='{self.titulo}' ativa={self.is_ativa}>"


class RespostaAvaliacaoGeral(db.Model):
    __tablename__ = 'respostas_avaliacao_geral'

    id: Mapped[int] = mapped_column(primary_key=True)
    campanha_id: Mapped[int] = mapped_column(db.ForeignKey('campanhas_avaliacao.id'), nullable=False)
    turma_id: Mapped[int] = mapped_column(db.ForeignKey('turmas.id'), nullable=False)
    token_sigilo: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)

    nota_organizacao: Mapped[int] = mapped_column(nullable=False)
    nota_tecnologia: Mapped[int] = mapped_column(nullable=False)
    nota_corpo_alunos: Mapped[int] = mapped_column(nullable=False)
    nota_direcao: Mapped[int] = mapped_column(nullable=False)
    nota_satisfacao_geral: Mapped[int] = mapped_column(nullable=False)
    
    comentarios_gerais: Mapped[t.Optional[str]] = mapped_column(db.Text, nullable=True)
    data_resposta: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow)

    campanha: Mapped["CampanhaAvaliacao"] = relationship(back_populates="respostas_geral")
    turma: Mapped["Turma"] = relationship()


class RespostaAvaliacao(db.Model):
    __tablename__ = 'respostas_avaliacao'

    id: Mapped[int] = mapped_column(primary_key=True)
    campanha_id: Mapped[int] = mapped_column(db.ForeignKey('campanhas_avaliacao.id'), nullable=False)
    instrutor_id: Mapped[int] = mapped_column(db.ForeignKey('instrutores.id'), nullable=False)
    turma_id: Mapped[int] = mapped_column(db.ForeignKey('turmas.id'), nullable=False)
    
    token_sigilo: Mapped[t.Optional[str]] = mapped_column(db.String(100), nullable=True, index=True)
    
    # Manter campos antigos por seguranca (nullable para migracao limpa, mas podemos ignorar no frontend)
    aluno_id: Mapped[t.Optional[int]] = mapped_column(db.ForeignKey('alunos.id'), nullable=True)
    nota: Mapped[t.Optional[int]] = mapped_column(nullable=True)
    
    # Novas Notas Específicas
    nota_relacionamento: Mapped[int] = mapped_column(nullable=False, server_default='3')
    nota_dominio: Mapped[int] = mapped_column(nullable=False, server_default='3')
    nota_relevancia: Mapped[int] = mapped_column(nullable=False, server_default='3')

    comentario: Mapped[t.Optional[str]] = mapped_column(db.Text, nullable=True)
    data_resposta: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow)

    campanha: Mapped["CampanhaAvaliacao"] = relationship(back_populates="respostas_instrutor")
    instrutor: Mapped["Instrutor"] = relationship()
    turma: Mapped["Turma"] = relationship()
    aluno: Mapped[t.Optional["Aluno"]] = relationship()

    def __repr__(self):
        return f"<RespostaAvaliacao instrutor_id={self.instrutor_id} token={self.token_sigilo}>"


class ControlePreenchimentoAvaliacao(db.Model):
    __tablename__ = 'controle_preenchimento_avaliacao'

    id: Mapped[int] = mapped_column(primary_key=True)
    campanha_id: Mapped[int] = mapped_column(db.ForeignKey('campanhas_avaliacao.id'), nullable=False)
    aluno_id: Mapped[int] = mapped_column(db.ForeignKey('alunos.id'), nullable=False)
    data_preenchimento: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow)

    campanha: Mapped["CampanhaAvaliacao"] = relationship(back_populates="controles_preenchimento")
    aluno: Mapped["Aluno"] = relationship()

