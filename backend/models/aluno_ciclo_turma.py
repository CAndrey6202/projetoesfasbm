from __future__ import annotations
import typing as t
from datetime import datetime
from .database import db
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, DateTime

if t.TYPE_CHECKING:
    from .aluno import Aluno
    from .ciclo import Ciclo
    from .turma import Turma


class AlunoCicloTurma(db.Model):
    """
    Registra a qual Turma o Aluno pertenceu em cada Ciclo.
    Permite remanejar alunos entre turmas na virada de um ciclo para outro
    preservando 100% do histórico de diários, frequências, notas e relatórios dos ciclos anteriores.
    """
    __tablename__ = 'aluno_ciclo_turmas'
    __table_args__ = (
        db.UniqueConstraint('aluno_id', 'ciclo_id', name='uq_aluno_ciclo_turma'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    aluno_id: Mapped[int] = mapped_column(ForeignKey('alunos.id', ondelete='CASCADE'), nullable=False, index=True)
    ciclo_id: Mapped[int] = mapped_column(ForeignKey('ciclos.id', ondelete='CASCADE'), nullable=False, index=True)
    turma_id: Mapped[int] = mapped_column(ForeignKey('turmas.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at: Mapped[t.Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)

    aluno: Mapped["Aluno"] = relationship("Aluno", back_populates="ciclo_turmas")
    ciclo: Mapped["Ciclo"] = relationship("Ciclo", backref="alunos_ciclo")
    turma: Mapped["Turma"] = relationship("Turma", backref="alunos_por_ciclo")

    def __init__(self, aluno_id: int, ciclo_id: int, turma_id: int, **kw: t.Any) -> None:
        super().__init__(aluno_id=aluno_id, ciclo_id=ciclo_id, turma_id=turma_id, **kw)

    def __repr__(self) -> str:
        return f"<AlunoCicloTurma aluno_id={self.aluno_id} ciclo_id={self.ciclo_id} turma_id={self.turma_id}>"
