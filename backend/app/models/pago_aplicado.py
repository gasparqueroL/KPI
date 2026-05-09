"""Aplicación explícita de un pago (movimiento de cobranza) a una venta.

Habilita:
- Pagos parciales (un movimiento cubre N facturas)
- Sobrepagos (anticipo a cuenta)
- Aging real por venta
- Auditoría: ¿qué movimiento canceló qué venta?

NO reemplaza `MovimientoCaja.id_cliente_relacionado` por compatibilidad.
El campo viejo sigue funcionando para vínculos cliente-nivel.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)

from app.db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class PagoAplicado(Base):
    __tablename__ = "pagos_aplicados"
    __table_args__ = (
        UniqueConstraint("id_venta", "id_movimiento", name="uq_pago_aplicado"),
        # Defensa en profundidad: la app valida en aplicar_pago, la DB
        # también — un INSERT directo o un futuro endpoint admin no puede
        # meter saldos negativos.
        CheckConstraint("monto > 0", name="ck_pago_aplicado_monto_pos"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    # ondelete CASCADE: si una venta o un movimiento se borra, las
    # aplicaciones huérfanas se borran solas (evita filas que apuntan a
    # entidades inexistentes y descuentan saldo silenciosamente).
    id_venta = Column(
        String,
        ForeignKey("ventas.id_pedido", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    id_movimiento = Column(
        Integer,
        ForeignKey("movimientos_caja.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    monto = Column(Numeric(14, 2), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
