from __future__ import annotations
import typing as t
from datetime import datetime
from .database import db
from sqlalchemy.orm import Mapped, mapped_column, relationship

if t.TYPE_CHECKING:
    from .disciplina import Disciplina
    from .aluno import Aluno

class HistoricoDisciplina(db.Model):
    __tablename__ = 'historico_disciplinas'

    id: Mapped[int] = mapped_column(primary_key=True)
    nota: Mapped[t.Optional[float]] = mapped_column(db.Float) # Armazenará a média final (MPD ou MFD)
    data_conclusao: Mapped[t.Optional[datetime]] = mapped_column()
    status: Mapped[str] = mapped_column(db.String(50), default='cursando')

    # NOVOS CAMPOS PARA AS NOTAS
    nota_p1: Mapped[t.Optional[float]] = mapped_column(db.Float)
    nota_p2: Mapped[t.Optional[float]] = mapped_column(db.Float)
    nota_rec: Mapped[t.Optional[float]] = mapped_column(db.Float)

    disciplina_id: Mapped[int] = mapped_column(db.ForeignKey('disciplinas.id'))
    disciplina: Mapped["Disciplina"] = relationship(back_populates="historico_disciplinas")

    aluno_id: Mapped[int] = mapped_column(db.ForeignKey('alunos.id'))
    aluno: Mapped["Aluno"] = relationship(back_populates="historico_disciplinas")

    def __init__(self, aluno_id: int, disciplina_id: int, 
                 nota: t.Optional[float] = None, data_conclusao: t.Optional[datetime] = None, 
                 status: str = 'cursando', **kw: t.Any) -> None:
        if 'nota_final' in kw and nota is None:
            nota = kw.pop('nota_final')
        super().__init__(aluno_id=aluno_id, disciplina_id=disciplina_id, 
                         nota=nota, data_conclusao=data_conclusao, 
                         status=status, **kw)

    @property
    def nota_final(self) -> t.Optional[float]:
        return self.nota

    @nota_final.setter
    def nota_final(self, value: t.Optional[float]) -> None:
        self.nota = value

    def __repr__(self):
        return (f"<HistoricoDisciplina id={self.id} disciplina_id={self.disciplina_id} "
                f"aluno_id={self.aluno_id} status='{self.status}'>")