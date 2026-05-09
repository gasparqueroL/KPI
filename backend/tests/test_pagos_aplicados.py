"""Tests del módulo pagos_aplicados (refactor sesión 4)."""
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.kpis.pagos_aplicados import (
    aplicar_pago,
    aplicaciones_de_movimiento,
    aplicaciones_de_venta,
    desaplicar_pago,
    disponible_movimiento,
    saldo_venta,
)
from app.models.caja import Caja
from app.models.categoria_caja import CategoriaCaja
from app.models.movimiento_caja import MovimientoCaja
from app.models.pago_aplicado import PagoAplicado
from app.models.venta import Venta


def _setup(db):
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.add(CategoriaCaja(
        tipo_operacion="Ingreso", familia="Operaciones especiales",
        es_ingreso_operativo=True,
    ))
    db.add(Venta(
        id_pedido="p1", id_venta="v1",
        fecha=datetime(2026, 4, 1),
        id_cliente=10, cliente="A", total=Decimal("10000"),
        es_cuenta_corriente=True,
    ))
    db.add(MovimientoCaja(
        id=1, fecha=date(2026, 4, 15), tipo_operacion="Ingreso",
        monto=Decimal("3000"), caja_destino="cl", hash_dedupe="hpa1",
    ))
    db.commit()


def test_saldo_y_disponible_iniciales(db):
    _setup(db)
    assert saldo_venta(db, "p1") == Decimal("10000")
    assert disponible_movimiento(db, 1) == Decimal("3000")


def test_aplicar_parcial_reduce_ambos(db):
    _setup(db)
    p = aplicar_pago(db, "p1", 1, Decimal("3000"))
    assert p.monto == Decimal("3000")
    assert saldo_venta(db, "p1") == Decimal("7000")
    assert disponible_movimiento(db, 1) == Decimal("0")


def test_aplicar_sin_monto_aplica_el_minimo_disponible(db):
    _setup(db)
    # mov tiene 3000, venta tiene 10000 -> aplica 3000
    p = aplicar_pago(db, "p1", 1)
    assert p.monto == Decimal("3000")


def test_no_se_puede_aplicar_mas_que_disponible(db):
    _setup(db)
    with pytest.raises(ValueError, match="excede"):
        aplicar_pago(db, "p1", 1, Decimal("5000"))


def test_re_aplicar_suma_al_existente(db):
    _setup(db)
    aplicar_pago(db, "p1", 1, Decimal("1000"))
    aplicar_pago(db, "p1", 1, Decimal("500"))
    # Total aplicado: 1500
    assert saldo_venta(db, "p1") == Decimal("8500")
    assert disponible_movimiento(db, 1) == Decimal("1500")
    # Una sola fila, no dos
    assert db.query(PagoAplicado).filter(PagoAplicado.id_venta == "p1").count() == 1


def test_un_movimiento_cubre_dos_ventas(db):
    _setup(db)
    db.add(Venta(
        id_pedido="p2", id_venta="v2",
        fecha=datetime(2026, 4, 5),
        id_cliente=10, cliente="A", total=Decimal("2000"),
        es_cuenta_corriente=True,
    ))
    db.commit()

    aplicar_pago(db, "p1", 1, Decimal("1000"))
    aplicar_pago(db, "p2", 1, Decimal("2000"))

    assert disponible_movimiento(db, 1) == Decimal("0")
    assert saldo_venta(db, "p1") == Decimal("9000")
    assert saldo_venta(db, "p2") == Decimal("0")


def test_desaplicar_libera_disponibilidad(db):
    _setup(db)
    p = aplicar_pago(db, "p1", 1, Decimal("3000"))
    desaplicar_pago(db, p.id)
    assert saldo_venta(db, "p1") == Decimal("10000")
    assert disponible_movimiento(db, 1) == Decimal("3000")


def test_aplicaciones_de_venta(db):
    _setup(db)
    aplicar_pago(db, "p1", 1, Decimal("1500"))
    apls = aplicaciones_de_venta(db, "p1")
    assert len(apls) == 1
    assert apls[0]["monto_aplicado"] == 1500.0
    assert apls[0]["id_movimiento"] == 1
