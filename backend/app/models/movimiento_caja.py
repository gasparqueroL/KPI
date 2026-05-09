from datetime import datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)

from app.db import Base


class MovimientoCaja(Base):
    """Movimiento de caja. caja_origen=salida, caja_destino=entrada.

    - solo origen → gasto (caja origen pierde monto)
    - solo destino → ingreso (caja destino suma monto)
    - ambos → transferencia (origen pierde, destino suma; saldo total no cambia)
    """

    __tablename__ = "movimientos_caja"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fecha = Column(Date, nullable=False, index=True)
    tipo_operacion = Column(
        String,
        ForeignKey("categorias_caja.tipo_operacion"),
        nullable=False,
        index=True,
    )
    detalle = Column(String, nullable=True)
    monto = Column(Numeric(14, 2), nullable=False)

    caja_origen = Column(
        String, ForeignKey("cajas.nombre_normalizado"), nullable=True
    )
    caja_destino = Column(
        String, ForeignKey("cajas.nombre_normalizado"), nullable=True
    )

    # Para cobranzas de cta cte: cliente al que se imputa el cobro.
    # Permite armar el extracto del cliente vinculando ventas con pagos.
    id_cliente_relacionado = Column(Integer, nullable=True, index=True)

    # Para egresos: factura del proveedor que se está pagando.
    id_factura_proveedor = Column(
        Integer, ForeignKey("facturas_proveedor.id"), nullable=True, index=True
    )

    hash_dedupe = Column(String, unique=True, nullable=False, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
