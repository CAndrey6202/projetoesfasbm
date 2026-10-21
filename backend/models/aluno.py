from __future__ import annotations
import typing as t
from datetime import date
from .database import db
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey

if t.TYPE_CHECKING:
    from .user import User
    from .turma import Turma
    from .historico import HistoricoAluno
    from .historico_disciplina import HistoricoDisciplina
    from .processo_disciplina import ProcessoDisciplina
    from .avaliacao import AvaliacaoAtitudinal
    from .fada_avaliacao import FadaAvaliacao 
    from .frequencia import FrequenciaAluno
    from .elogio import Elogio
    from .edicao import Edicao # Adicionado para o type checking da edição

class Aluno(db.Model):
    __tablename__ = 'alunos'

    id: Mapped[int] = mapped_column(primary_key=True)
    id_aluno: Mapped[str] = mapped_column(db.String(20), unique=True, nullable=True)
    opm: Mapped[str] = mapped_column(db.String(50))
    num_aluno: Mapped[str] = mapped_column(db.String(20), nullable=True)
    funcao_atual: Mapped[t.Optional[str]] = mapped_column(db.String(50))
    foto_perfil: Mapped[str] = mapped_column(db.String(255), default='default.png')
    telefone: Mapped[t.Optional[str]] = mapped_column(db.String(20))
    data_nascimento: Mapped[t.Optional[date]] = mapped_column(db.Date)

    # --- NOVO: Status do Aluno para o Soft Delete ---
    status_matricula: Mapped[str] = mapped_column(db.String(20), default='Ativo')

    turma_id: Mapped[t.Optional[int]] = mapped_column(ForeignKey('turmas.id'))
    turma: Mapped[t.Optional["Turma"]] = relationship(back_populates="alunos")

    # Alterado para suportar múltiplos perfis (1 usuário pode fazer mais de 1 edição)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    user: Mapped["User"] = relationship(back_populates="alunos_profiles")

    # Vinculação direta com a Edição
    edicao_id: Mapped[t.Optional[int]] = mapped_column(ForeignKey('edicoes.id'))
    edicao: Mapped[t.Optional["Edicao"]] = relationship(back_populates="alunos")

    # Relacionamentos
    historico: Mapped[list["HistoricoAluno"]] = relationship(back_populates="aluno", cascade="all, delete-orphan")
    historico_disciplinas: Mapped[list["HistoricoDisciplina"]] = relationship(back_populates="aluno", cascade="all, delete-orphan")
    processos_disciplinares: Mapped[list["ProcessoDisciplina"]] = relationship(back_populates="aluno", cascade="all, delete-orphan")
    fada_avaliacoes: Mapped[list['FadaAvaliacao']] = relationship('FadaAvaliacao', back_populates='aluno', lazy='dynamic', cascade="all, delete-orphan")
    frequencias: Mapped[list["FrequenciaAluno"]] = relationship("FrequenciaAluno", back_populates="aluno", cascade="all, delete-orphan")
    
    # NOVO: Relacionamento com Elogios
    elogios: Mapped[list["Elogio"]] = relationship("Elogio", back_populates="aluno", cascade="all, delete-orphan")
    ciclo_turmas: Mapped[list["AlunoCicloTurma"]] = relationship("AlunoCicloTurma", back_populates="aluno", cascade="all, delete-orphan")

    def __init__(self, user_id: int, opm: str,
                 id_aluno: t.Optional[str] = None, num_aluno: t.Optional[str] = None,
                 funcao_atual: t.Optional[str] = None, foto_perfil: str = 'default.png',
                 telefone: t.Optional[str] = None, data_nascimento: t.Optional[date] = None,
                 turma_id: t.Optional[int] = None, edicao_id: t.Optional[int] = None, 
                 status_matricula: str = 'Ativo', **kw: t.Any) -> None:
        super().__init__(user_id=user_id, opm=opm,
                         id_aluno=id_aluno, num_aluno=num_aluno,
                         funcao_atual=funcao_atual, foto_perfil=foto_perfil,
                         telefone=telefone, data_nascimento=data_nascimento, turma_id=turma_id, 
                         edicao_id=edicao_id, status_matricula=status_matricula, **kw)

    def __repr__(self):
        matricula_repr = self.user.matricula if self.user else 'N/A'
        return f"<Aluno id={self.id} matricula='{matricula_repr}' status='{self.status_matricula}'>"
