# backend/models/semana.py
from __future__ import annotations
import typing as t
from datetime import date
from .database import db
from sqlalchemy.orm import Mapped, mapped_column, relationship

if t.TYPE_CHECKING:
    from .ciclo import Ciclo


class Semana(db.Model):
    __tablename__ = 'semanas'

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(db.String(100), nullable=False)
    data_inicio: Mapped[date] = mapped_column(db.Date, nullable=False)
    data_fim: Mapped[date] = mapped_column(db.Date, nullable=False)

    # Relação com Ciclo (O Ciclo contém o school_id)
    ciclo_id: Mapped[int] = mapped_column(db.ForeignKey('ciclos.id'), nullable=False)
    ciclo: Mapped["Ciclo"] = relationship(back_populates="semanas")

    # Configurações de exibição de períodos
    mostrar_periodo_13: Mapped[bool] = mapped_column(default=False, server_default='0')
    mostrar_periodo_14: Mapped[bool] = mapped_column(default=False, server_default='0')
    mostrar_periodo_15: Mapped[bool] = mapped_column(default=False, server_default='0')
    mostrar_periodo_16: Mapped[bool] = mapped_column(default=False, server_default='0')
    mostrar_periodo_17: Mapped[bool] = mapped_column(default=False, server_default='0')
    mostrar_periodo_18: Mapped[bool] = mapped_column(default=False, server_default='0')
    
    # Configurações de fim de semana
    mostrar_sabado: Mapped[bool] = mapped_column(default=False, server_default='0')
    periodos_sabado: Mapped[int] = mapped_column(default=0, server_default='0')
    mostrar_domingo: Mapped[bool] = mapped_column(default=False, server_default='0')
    periodos_domingo: Mapped[int] = mapped_column(default=0, server_default='0')

    # =========================
    # Configurações de Prioridade
    # =========================
    priority_active: Mapped[bool] = mapped_column(default=False, server_default='0')
    priority_disciplines: Mapped[str | None] = mapped_column(db.Text, nullable=True)

    # Armazena JSON com bloqueios de prioridade por:
    # { "T1": { "segunda": ["P1","P2"], "quarta": ["P3"] }, ... }
    priority_blocks: Mapped[str | None] = mapped_column(db.Text, nullable=True)

    # =========================
    # Configurações de Bloqueio (NOVO)
    # =========================
    # Armazena JSON com bloqueios totais (ninguém pode marcar) por:
    # { "T1": { "segunda": ["P1","P2"], "quarta": ["P3"] }, ... }
    blocked_blocks: Mapped[str | None] = mapped_column(db.Text, nullable=True)

    def __init__(
        self,
        nome: str,
        data_inicio: date,
        data_fim: date,
        ciclo_id: int,
        **kw: t.Any
    ) -> None:
        super().__init__(
            nome=nome,
            data_inicio=data_inicio,
            data_fim=data_fim,
            ciclo_id=ciclo_id,
            **kw
        )

    def __repr__(self):
        return f"<Semana id={self.id} nome='{self.nome}'>"