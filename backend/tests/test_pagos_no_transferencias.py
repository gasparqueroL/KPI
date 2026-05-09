"""Tests que cubren el fix C2: transferencias NO se pueden aplicar como pagos."""
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.kpis.pagos_aplicados import aplicar_pago, disponible_movimiento
from app.models.caja import Caja
from app.models.movimiento_caja import MovimientoCaja
from app.models.venta import Venta


def test_no_se_puede_aplicar_una_transferencia_como_pago(db):
    db.add(Caja(nombre_normalizado="c1", nombre_display="C1", tipo="operativa"))
    db.add(Caja(nombre_normalizado="c2", nombre_display="C2", tipo="operativa"))
    db.add(Venta(
        id_pedido="p1", id_venta="v1", fecha=datetime(2026, 4, 1),
        id_cliente=1, cliente="A", total=Decimal("1000"),
        es_cuenta_corriente=True,
    ))
    # Transferencia: tiene origen Y destino
    db.add(MovimientoCaja(
        id=1, fecha=date(2026, 4, 5), tipo_operacion="Balance",
        monto=Decimal("500"),
        caja_origen="c1", caja_destino="c2",
        hash_dedupe="ht1",
    ))
    db.commit()

    assert disponible_movimiento(db, 1) is None, (
        "Una transferencia NO es aplicable como pago: contrato cambió a None"
    )

    with pytest.raises(ValueError, match="ingreso puro"):
        aplicar_pago(db, "p1", 1, Decimal("500"))


def test_aplicar_funciona_con_ingreso_puro(db):
    """Sanity: ingreso puro (solo destino) sí permite aplicar."""
    db.add(Caja(nombre_normalizado="c1", nombre_display="C1", tipo="operativa"))
    db.add(Venta(
        id_pedido="p1", id_venta="v1", fecha=datetime(2026, 4, 1),
        id_cliente=1, cliente="A", total=Decimal("1000"),
        es_cuenta_corriente=True,
    ))
    db.add(MovimientoCaja(
        id=1, fecha=date(2026, 4, 5), tipo_operacion="Ingreso",
        monto=Decimal("500"),
        caja_destino="c1",  # solo destino
        hash_dedupe="ht2",
    ))
    db.commit()

    assert disponible_movimiento(db, 1) == Decimal("500")
    p = aplicar_pago(db, "p1", 1, Decimal("500"))
    assert p.monto == Decimal("500")
