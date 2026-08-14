from __future__ import annotations
import typing as t
from .database import db
from sqlalchemy.orm import Mapped, mapped_column, relationship

if t.TYPE_CHECKING:
    from .pergunta import Pergunta

class Questionario(db.Model):
    __tablename__ = 'questionarios'

    id: Mapped[int] = mapped_column(primary_key=True)
    titulo: Mapped[str] = mapped_column(db.String(200), nullable=False)
    publico_alvo: Mapped[str] = mapped_column(db.String(50), nullable=False, default='todos')
    ativo: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)
    
    perguntas: Mapped[list[Pergunta]] = relationship(back_populates="questionario", cascade="all, delete-orphan")

    def __init__(self, titulo: str, **kw: t.Any) -> None:
        super().__init__(titulo=titulo, **kw)

    def __repr__(self):
        return f"<Questionario id={self.id} titulo='{self.titulo}'>"