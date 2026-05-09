"""Tests de conciliación — invariantes facturado vs ingreso real."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.kpis.conciliacion import conciliacion
from app.models.caja import Caja
from app.models.categoria_caja import CategoriaCaja
from app.models.movimiento_caja import MovimientoCaja
from app.models.venta import Venta


def _setup_basico(db):
    db.add(Caja(nombre_normalizado="cajalocal", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.add(CategoriaCaja(
        tipo_operacion="Ingreso", familia="Operaciones especiales",
        es_ingreso_operativo=True,
    ))
    db.add(CategoriaCaja(
        tipo_operacion="Devolucion FC", familia="Operaciones especiales",
        es_ingreso_operativo=False,
    ))


def test_facturado_igual_a_total_ventas(db):
    _setup_basico(db)
    db.add_all([
        Venta(id_pedido="p1", id_venta="v1", fecha=datetime(2026, 4, 1),
              id_cliente=1, cliente="A", total=Decimal("100"),
              monto_pago1=Decimal("100"), caja1="cajalocal"),
        Venta(id_pedido="p2", id_venta="v2", fecha=datetime(2026, 4, 2),
              id_cliente=2, cliente="B", total=Decimal("200"),
              monto_pago1=Decimal("200"), caja1="cajalocal"),
    ])
    db.commit()
    r = conciliacion(db)
    assert r["facturado"] == 300.0
    assert r["cobrado_en_caja"] == 300.0
    assert r["cobertura_pct"] == 100.0


def test_cobranza_cta_cte_se_separa_de_otros_ingresos(db):
    _setup_basico(db)
    # Venta cobrada normalmente
    db.add(Venta(id_pedido="p1", id_venta="v1", fecha=datetime(2026, 4, 1),
                 id_cliente=1, cliente="A", total=Decimal("100"),
                 monto_pago1=Decimal("100"), caja1="cajalocal"))
    # Cobranza posterior de cta cte
    db.add(MovimientoCaja(fecha=date(2026, 4, 10), tipo_operacion="Ingreso",
                          monto=Decimal("50"), caja_destino="cajalocal",
                          hash_dedupe="h1"))
    # Devolución de adelanto a empleado (NO operativo)
    db.add(MovimientoCaja(fecha=date(2026, 4, 12), tipo_operacion="Devolucion FC",
                          monto=Decimal("30"), caja_destino="cajalocal",
                          hash_dedupe="h2"))
    db.commit()

    r = conciliacion(db)
    assert r["cobrado_en_caja"] == 100.0
    assert r["cobranzas_cta_cte"] == 50.0       # solo el "Ingreso"
    assert r["otros_ingresos_movimientos"] == 30.0  # devolución FC va aparte
    assert r["ingreso_operativo"] == 150.0
    assert r["ingreso_real_total"] == 180.0


def test_ventas_sin_cobro_se_detectan(db):
    _setup_basico(db)
    db.add(Venta(id_pedido="p1", id_venta="v1", fecha=datetime(2026, 4, 1),
                 id_cliente=1, cliente="X", total=Decimal("500"),
                 es_cuenta_corriente=False))  # sin cobro y NO marcada cta cte
    db.commit()
    r = conciliacion(db)
    assert r["ventas_sin_cobro"]["cantidad"] == 1
    assert r["ventas_sin_cobro"]["monto_total"] == 500.0


def test_ventas_cta_cte_se_separan_de_sin_cobro(db):
    _setup_basico(db)
    db.add(Venta(id_pedido="p1", id_venta="v1", fecha=datetime(2026, 4, 1),
                 id_cliente=1, cliente="X", total=Decimal("100"),
                 es_cuenta_corriente=True))
    db.commit()
    r = conciliacion(db)
    assert r["ventas_cta_cte"]["cantidad"] == 1
    assert r["ventas_sin_cobro"]["cantidad"] == 0  # marcada cta cte = NO cuenta como sin cobro


def test_cobertura_baja_cuando_hay_ventas_sin_cobro(db):
    _setup_basico(db)
    db.add(Venta(id_pedido="p1", id_venta="v1", fecha=datetime(2026, 4, 1),
                 id_cliente=1, cliente="A", total=Decimal("100"),
                 monto_pago1=Decimal("100"), caja1="cajalocal"))
    db.add(Venta(id_pedido="p2", id_venta="v2", fecha=datetime(2026, 4, 2),
                 id_cliente=2, cliente="B", total=Decimal("100")))  # sin cobro
    db.commit()
    r = conciliacion(db)
    assert r["facturado"] == 200.0
    assert r["ingreso_operativo"] == 100.0
    assert r["cobertura_pct"] == 50.0
    assert r["diferencia_facturado_vs_operativo"] == 100.0
