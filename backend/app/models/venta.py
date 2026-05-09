from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import relationship

from app.db import Base


class Venta(Base):
    """Cabecera de venta. Una fila por pedido."""

    __tablename__ = "ventas"

    id_pedido = Column(String, primary_key=True)
    id_venta = Column(String, unique=True, nullable=False, index=True)
    fecha = Column(DateTime, nullable=False, index=True)

    id_cliente = Column(Integer, nullable=True, index=True)
    cliente = Column(String, nullable=True)
    vendedor = Column(String, nullable=True, index=True)

    caja1 = Column(String, ForeignKey("cajas.nombre_normalizado"), nullable=True)
    monto_pago1 = Column(Numeric(14, 2), nullable=True)
    pago_v1 = Column(Boolean, nullable=False, default=False)

    caja2 = Column(String, ForeignKey("cajas.nombre_normalizado"), nullable=True)
    monto_pago2 = Column(Numeric(14, 2), nullable=True)
    pago_v2 = Column(Boolean, nullable=False, default=False)

    total = Column(Numeric(14, 2), nullable=False)
    comprobante = Column(String, nullable=True)
    helper_v = Column(Boolean, nullable=False, default=False)

    es_cuenta_corriente = Column(Boolean, nullable=False, default=False)
    discrepancia_pago = Column(Boolean, nullable=False, default=False, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    detalle = relationship(
        "DetalleVenta", back_populates="venta", cascade="all, delete-orphan"
    )


class DetalleVenta(Base):
    """Una fila por producto dentro de un pedido."""

    __tablename__ = "detalle_ventas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    id_venta = Column(
        String, ForeignKey("ventas.id_venta"), nullable=False, index=True
    )
    fecha = Column(DateTime, nullable=False, index=True)

    producto = Column(String, nullable=False, index=True)
    lista_precios = Column(String, nullable=True)
    cantidad = Column(Numeric(14, 4), nullable=False)
    precio_unitario = Column(Numeric(14, 2), nullable=False)
    subtotal = Column(Numeric(14, 2), nullable=False)
    descuento_unitario = Column(Numeric(14, 2), nullable=True)

    # CST = Costo Standard Total de la línea (cantidad * costo_unitario)
    # Habilita cálculo de margen bruto.
    cst = Column(Numeric(16, 6), nullable=True, index=True)

    # Posición de línea dentro del idVenta. Se asigna en el primer import
    # y NO cambia en re-imports (lo cual estabiliza el hash de dedup).
    linea_num = Column(Integer, nullable=False, default=0)

    # Clasificación de línea para que cada KPI filtre correctamente:
    #   'mercaderia' (default) | 'envio' | 'bonificacion'
    categoria_linea = Column(
        String, nullable=False, default="mercaderia", index=True
    )

    venta = relationship("Venta", back_populates="detalle")
