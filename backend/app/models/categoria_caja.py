from sqlalchemy import Boolean, Column, String

from app.db import Base


class CategoriaCaja(Base):
    """Catálogo de `Tipo de Operación` con flags que rigen cómo se contabiliza."""

    __tablename__ = "categorias_caja"

    tipo_operacion = Column(String, primary_key=True)
    familia = Column(String, nullable=True)
    excluir_flujo = Column(Boolean, nullable=False, default=False)
    es_transferencia = Column(Boolean, nullable=False, default=False)
    es_retiro = Column(Boolean, nullable=False, default=False)
    # True para movimientos que representan cobranza posterior de cta cte
    # (suman al "ingreso operativo/comercial" de la conciliación). False
    # para ingresos NO comerciales (devolución de adelantos, etc.).
    es_ingreso_operativo = Column(Boolean, nullable=False, default=False)
    # True si es un gasto FIJO (sueldos, alquileres, servicios) que se
    # paga independiente del nivel de ventas. Default False = variable
    # (mercadería, comisiones, envíos). Habilita cálculo de punto de
    # equilibrio: PE = costos_fijos / margen_contribucion%.
    es_costo_fijo = Column(Boolean, nullable=False, default=False)
    descripcion = Column(String, nullable=True)
