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
    respostas: Mapped[list["RespostaAvaliacao"]] = relationship(back_populates="campanha", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<CampanhaAvaliacao id={self.id} titulo='{self.titulo}' ativa={self.is_ativa}>"

class RespostaAvaliacao(db.Model):
    __tablename__ = 'respostas_avaliacao'

    id: Mapped[int] = mapped_column(primary_key=True)
    campanha_id: Mapped[int] = mapped_column(db.ForeignKey('campanhas_avaliacao.id'), nullable=False)
    aluno_id: Mapped[int] = mapped_column(db.ForeignKey('alunos.id'), nullable=False)
    instrutor_id: Mapped[int] = mapped_column(db.ForeignKey('instrutores.id'), nullable=False)
    turma_id: Mapped[int] = mapped_column(db.ForeignKey('turmas.id'), nullable=False)
    
    nota: Mapped[int] = mapped_column(nullable=False)  # 1 a 5
    comentario: Mapped[t.Optional[str]] = mapped_column(db.Text, nullable=True)
    data_resposta: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow)

    campanha: Mapped["CampanhaAvaliacao"] = relationship(back_populates="respostas")
    aluno: Mapped["Aluno"] = relationship()
    instrutor: Mapped["Instrutor"] = relationship()
    turma: Mapped["Turma"] = relationship()

    def __repr__(self):
        return f"<RespostaAvaliacao aluno_id={self.aluno_id} instrutor_id={self.instrutor_id} nota={self.nota}>"
