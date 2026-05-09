from datetime import date, datetime, timezone

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint

from app.db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class CierreCaja(Base):
    """Cierre diario por caja: snapshot del saldo y bloqueo de movimientos.

    Una vez cerrada una fecha+caja, los movimientos de esa caja con
    fecha <= cierre.fecha NO se pueden editar ni borrar (a menos que
    se reabra el cierre).
    """

    __tablename__ = "cierres_caja"
    __table_args__ = (
        UniqueConstraint("fecha", "caja", name="uq_cierre_fecha_caja"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    fecha = Column(Date, nullable=False, index=True)
    caja = Column(
        String, ForeignKey("cajas.nombre_normalizado"), nullable=False, index=True
    )
    saldo_cierre = Column(Numeric(14, 2), nullable=False)
    observaciones = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
