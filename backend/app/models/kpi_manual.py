"""KPIs cargados manualmente por la dueña: snapshots mensuales de datos
externos al CSV (balance contable, RRHH, marketing, encuestas, IT).

PK compuesta: (periodo, codigo). Una fila por mes/KPI.

`codigo` es el identificador estable del dato (ej. 'activos_totales',
'empleados_promedio', 'gasto_marketing'). El catálogo vive en código,
no en BD — agregar nuevos códigos requiere actualizar el frontend
form. Esto evita la complejidad de un sistema EAV genérico.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Numeric, String

from app.db import Base


class KpiManual(Base):
    __tablename__ = "kpis_manuales"

    # Período en formato YYYY-MM (alineado a `strftime('%Y-%m', fecha)`
    # que ya usamos en flujo_caja). String simple para evitar mezclar
    # tipos al hacer merge con queries de movimientos / ventas.
    periodo = Column(String, primary_key=True)
    codigo = Column(String, primary_key=True)
    valor = Column(Numeric(18, 4), nullable=False)
    nota = Column(String, nullable=True)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
    )
