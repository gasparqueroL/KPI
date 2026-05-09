"""Objetivos/targets por KPI: la dueña fija una meta y el dashboard
señaliza si la cumple o no.

Una fila por código de KPI. Sin período: los objetivos son rolling
("rotación siempre debajo de 10%"). Para metas anuales por mes
distintas se podría extender con `(codigo, periodo)` PK, pero ese
caso de uso requiere planificación que no tenemos hoy.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Numeric, String

from app.db import Base


class KpiObjetivo(Base):
    __tablename__ = "kpis_objetivos"

    codigo = Column(String, primary_key=True)
    valor_objetivo = Column(Numeric(18, 4), nullable=False)
    nota = Column(String, nullable=True)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
    )
