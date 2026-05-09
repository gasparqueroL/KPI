from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship

from app.db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Proveedor(Base):
    """Catálogo de proveedores (espejo de clientes para deuda comercial)."""

    __tablename__ = "proveedores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String, nullable=False, index=True)
    cuit = Column(String, nullable=True, index=True)
    contacto = Column(String, nullable=True)
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=_utcnow)

    # Sin delete-orphan: borrar un proveedor NO borra sus facturas en cascada
    # — la regla "no borrar facturas con pagos vinculados" vive en el endpoint
    # eliminar_factura y debe respetarse incluso si se intenta borrar al
    # proveedor. Para baja, usar `activo=False` (soft-delete).
    facturas = relationship("FacturaProveedor", back_populates="proveedor", cascade="save-update, merge")


class FacturaProveedor(Base):
    """Factura emitida por un proveedor a la empresa. Pendiente o pagada."""

    __tablename__ = "facturas_proveedor"

    id = Column(Integer, primary_key=True, autoincrement=True)
    id_proveedor = Column(Integer, ForeignKey("proveedores.id"), nullable=False, index=True)
    numero = Column(String, nullable=True)
    fecha_emision = Column(Date, nullable=False, index=True)
    fecha_vencimiento = Column(Date, nullable=True, index=True)
    total = Column(Numeric(14, 2), nullable=False)
    descripcion = Column(String, nullable=True)
    observaciones = Column(String, nullable=True)
    # Anulación lógica: una factura cargada por error que ya tiene pagos
    # vinculados no se puede borrar (FK), pero sí anular para excluirla
    # de saldo y vencimientos sin perder histórico.
    anulada = Column(Boolean, nullable=False, default=False, server_default="0")
    created_at = Column(DateTime, default=_utcnow)

    proveedor = relationship("Proveedor", back_populates="facturas")
