"""Tests de cuentas corrientes — invariantes contables del ledger.

Cubre los Critical fixes del code review:
- Solo movimientos operativos pueden asignarse (C1)
- Saldo running coherente
- Orden cronológico estable cuando hay venta y pago el mismo día (I1)
"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.kpis.cuentas_corrientes import clientes_con_cuenta, ledger_cliente
from app.models.caja import Caja
from app.models.categoria_caja import CategoriaCaja
from app.models.movimiento_caja import MovimientoCaja
from app.models.venta import Venta


@pytest.fixture
def setup_cliente_simple(db):
    """Cliente Ariel con 1 venta de $10000 marcada cta cte."""
    db.add(Caja(nombre_normalizado="cajalocal", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.add(CategoriaCaja(
        tipo_operacion="Ingreso",
        familia="Operaciones especiales",
        es_ingreso_operativo=True,
    ))
    db.add(Venta(
        id_pedido="ped-1",
        id_venta="v-1",
        fecha=datetime(2026, 4, 1, 10, 0),
        id_cliente=280,
        cliente="Ariel",
        total=Decimal("10000"),
        es_cuenta_corriente=True,
    ))
    db.commit()
    return {"id_cliente": 280}


def test_cliente_con_solo_cargo(setup_cliente_simple, db):
    clientes = clientes_con_cuenta(db)
    ariel = next(c for c in clientes if c["id_cliente"] == 280)
    assert ariel["monto_cargado"] == 10000.0
    assert ariel["monto_pagado"] == 0.0
    assert ariel["saldo"] == 10000.0


def test_pago_reduce_saldo(setup_cliente_simple, db):
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 15),
        tipo_operacion="Ingreso",
        monto=Decimal("3000"),
        caja_destino="cajalocal",
        id_cliente_relacionado=280,
        hash_dedupe="h1",
    ))
    db.commit()

    clientes = clientes_con_cuenta(db)
    ariel = next(c for c in clientes if c["id_cliente"] == 280)
    assert ariel["monto_pagado"] == 3000.0
    assert ariel["saldo"] == 7000.0


def test_ledger_orden_mismo_dia_venta_antes_que_pago(db):
    """Si hay venta y pago el mismo día, la venta va PRIMERO en el extracto."""
    db.add(Caja(nombre_normalizado="cajalocal", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.add(CategoriaCaja(
        tipo_operacion="Ingreso", familia="Operaciones especiales",
        es_ingreso_operativo=True,
    ))
    db.add(Venta(
        id_pedido="p1", id_venta="v1",
        fecha=datetime(2026, 4, 1, 18, 30),
        id_cliente=100, cliente="X", total=Decimal("5000"),
        es_cuenta_corriente=True,
    ))
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 1),
        tipo_operacion="Ingreso", monto=Decimal("5000"),
        caja_destino="cajalocal", id_cliente_relacionado=100,
        hash_dedupe="h1",
    ))
    db.commit()

    led = ledger_cliente(db, 100)
    assert led["eventos"][0]["tipo"] == "venta", "venta debe ir primero el mismo día"
    assert led["eventos"][1]["tipo"] == "pago"
    assert led["eventos"][0]["saldo"] == 5000.0   # tras la venta
    assert led["eventos"][1]["saldo"] == 0.0      # tras el pago
    assert led["saldo_actual"] == 0.0


def test_ledger_excluye_movimientos_no_operativos(db):
    """Movimientos asignados al cliente que NO son ingreso operativo
    (ej. transferencia o egreso) deben excluirse del ledger."""
    db.add(Caja(nombre_normalizado="caja1", nombre_display="C1", tipo="operativa"))
    db.add(Caja(nombre_normalizado="caja2", nombre_display="C2", tipo="operativa"))
    db.add(CategoriaCaja(
        tipo_operacion="Balance", familia="Operaciones especiales",
        es_ingreso_operativo=False, es_transferencia=True,
    ))
    db.add(Venta(
        id_pedido="p1", id_venta="v1",
        fecha=datetime(2026, 4, 1),
        id_cliente=200, cliente="Y", total=Decimal("1000"),
        es_cuenta_corriente=True,
    ))
    # Transferencia entre cajas asignada al cliente (NO debería contar)
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 5), tipo_operacion="Balance", monto=Decimal("500"),
        caja_origen="caja1", caja_destino="caja2",
        id_cliente_relacionado=200, hash_dedupe="h1",
    ))
    db.commit()

    led = ledger_cliente(db, 200)
    assert len(led["eventos"]) == 1, "transferencia no debe aparecer en el ledger"
    assert led["eventos"][0]["tipo"] == "venta"
    assert led["saldo_actual"] == 1000.0


def test_invariante_saldo(db):
    """saldo = total_debe - total_haber para todo cliente."""
    db.add(Caja(nombre_normalizado="cajalocal", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.add(CategoriaCaja(
        tipo_operacion="Ingreso", familia="X", es_ingreso_operativo=True,
    ))
    db.add(Venta(
        id_pedido="p1", id_venta="v1", fecha=datetime(2026, 4, 1),
        id_cliente=999, cliente="Z", total=Decimal("8000"),
        es_cuenta_corriente=True,
    ))
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 10), tipo_operacion="Ingreso", monto=Decimal("3000"),
        caja_destino="cajalocal", id_cliente_relacionado=999, hash_dedupe="h1",
    ))
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 20), tipo_operacion="Ingreso", monto=Decimal("2000"),
        caja_destino="cajalocal", id_cliente_relacionado=999, hash_dedupe="h2",
    ))
    db.commit()

    led = ledger_cliente(db, 999)
    assert led["total_debe"] == 8000.0
    assert led["total_haber"] == 5000.0
    assert led["saldo_actual"] == led["total_debe"] - led["total_haber"]


def test_cliente_con_typo_en_nombre_aparece_una_sola_vez(db):
    """id_cliente igual con nombre escrito distinto (typo) -> una sola fila."""
    db.add(Caja(nombre_normalizado="c1", nombre_display="C1", tipo="operativa"))
    db.add(Venta(
        id_pedido="p1", id_venta="v1", fecha=datetime(2026, 4, 1),
        id_cliente=500, cliente="Ariel Gonzales",
        total=Decimal("1000"), es_cuenta_corriente=True,
    ))
    db.add(Venta(
        id_pedido="p2", id_venta="v2", fecha=datetime(2026, 4, 5),
        id_cliente=500, cliente="ariel gonzales",  # typo (lower)
        total=Decimal("500"), es_cuenta_corriente=True,
    ))
    db.commit()

    clientes = clientes_con_cuenta(db)
    arieles = [c for c in clientes if c["id_cliente"] == 500]
    assert len(arieles) == 1, (
        f"id_cliente=500 debe aparecer una sola vez, salieron {len(arieles)}"
    )
    assert arieles[0]["monto_cargado"] == 1500.0


from app.kpis.cuentas_corrientes import aging_cobros, dso


def test_aging_distribuye_ventas_en_buckets(db):
    from datetime import date, timedelta
    hoy = date.today()
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.add(Venta(
        id_pedido="p1", id_venta="v1",
        fecha=datetime.combine(hoy - timedelta(days=10), datetime.min.time()),
        id_cliente=1, cliente="A", total=Decimal("1000"),
        es_cuenta_corriente=True,
    ))
    db.add(Venta(
        id_pedido="p2", id_venta="v2",
        fecha=datetime.combine(hoy - timedelta(days=45), datetime.min.time()),
        id_cliente=1, cliente="A", total=Decimal("2000"),
        es_cuenta_corriente=True,
    ))
    db.add(Venta(
        id_pedido="p3", id_venta="v3",
        fecha=datetime.combine(hoy - timedelta(days=100), datetime.min.time()),
        id_cliente=1, cliente="A", total=Decimal("3000"),
        es_cuenta_corriente=True,
    ))
    db.commit()

    out = aging_cobros(db)
    item = next(i for i in out["items"] if i["id_cliente"] == 1)
    assert item["bucket_0_30"] == 1000.0
    assert item["bucket_31_60"] == 2000.0
    assert item["bucket_61_90"] == 0.0
    assert item["bucket_90_mas"] == 3000.0
    assert item["total"] == 6000.0


def test_aging_aplica_pagos_a_buckets_mas_viejos_primero(db):
    from datetime import date, timedelta
    hoy = date.today()
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.add(CategoriaCaja(
        tipo_operacion="Ingreso", familia="Operaciones especiales",
        es_ingreso_operativo=True,
    ))
    db.add(Venta(
        id_pedido="p1", id_venta="v1",
        fecha=datetime.combine(hoy - timedelta(days=10), datetime.min.time()),
        id_cliente=1, cliente="A", total=Decimal("1000"),
        es_cuenta_corriente=True,
    ))
    db.add(Venta(
        id_pedido="p2", id_venta="v2",
        fecha=datetime.combine(hoy - timedelta(days=100), datetime.min.time()),
        id_cliente=1, cliente="A", total=Decimal("3000"),
        es_cuenta_corriente=True,
    ))
    db.add(MovimientoCaja(
        fecha=hoy, tipo_operacion="Ingreso", monto=Decimal("2500"),
        caja_destino="cl", id_cliente_relacionado=1, hash_dedupe="hag1",
    ))
    db.commit()

    out = aging_cobros(db)
    item = next(i for i in out["items"] if i["id_cliente"] == 1)
    assert item["bucket_90_mas"] == 500.0
    assert item["bucket_0_30"] == 1000.0
    assert item["total"] == 1500.0


def test_dso_calcula_dias_promedio(db):
    from datetime import date, timedelta
    hoy = date.today()
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.add(Venta(
        id_pedido="p1", id_venta="v1",
        fecha=datetime.combine(hoy - timedelta(days=20), datetime.min.time()),
        id_cliente=1, cliente="A", total=Decimal("1000"),
        monto_pago1=Decimal("1000"), caja1="cl",
    ))
    db.add(Venta(
        id_pedido="p2", id_venta="v2",
        fecha=datetime.combine(hoy - timedelta(days=15), datetime.min.time()),
        id_cliente=2, cliente="B", total=Decimal("1000"),
        es_cuenta_corriente=True,
    ))
    db.commit()

    out = dso(db, dias_ventana=90)
    assert out["ventas_periodo"] == 2000.0
    assert out["saldo_pendiente_periodo"] == 1000.0
    assert out["dso_aprox_dias"] == 45.0


def test_dso_sin_ventas_devuelve_null(db):
    """Sin ventas en el periodo, dso_aprox_dias debe ser None (no 0 engañoso)."""
    out = dso(db, dias_ventana=90)
    assert out["ventas_periodo"] == 0.0
    assert out["dso_aprox_dias"] is None


def test_aging_clientes_con_credito_a_favor(db):
    """Sobrepago: cliente con pago > deuda aparece en con_credito, no items."""
    from datetime import date, timedelta
    hoy = date.today()
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.add(Venta(
        id_pedido="pcr", id_venta="vcr",
        fecha=datetime.combine(hoy - timedelta(days=5), datetime.min.time()),
        id_cliente=99, cliente="ANTICIPO", total=Decimal("1000"),
        es_cuenta_corriente=True,
    ))
    db.add(MovimientoCaja(
        fecha=hoy, tipo_operacion="Ingreso", monto=Decimal("1500"),
        caja_destino="cl", id_cliente_relacionado=99, hash_dedupe="hcr",
    ))
    db.commit()

    out = aging_cobros(db)
    # No aparece en deudores
    assert all(i["id_cliente"] != 99 for i in out["items"])
    # Aparece en con_credito con $500 a favor
    cred = next(c for c in out["con_credito"] if c["id_cliente"] == 99)
    assert cred["credito_a_favor"] == 500.0


def test_aging_resta_pagos_aplicados_explicitos(db):
    """Si una venta tiene pagos_aplicados, su saldo neto cuenta en el bucket
    (no su total bruto)."""
    from datetime import date, timedelta
    from app.models.pago_aplicado import PagoAplicado
    hoy = date.today()
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.add(Venta(
        id_pedido="pap", id_venta="vap",
        fecha=datetime.combine(hoy - timedelta(days=5), datetime.min.time()),
        id_cliente=42, cliente="MIX", total=Decimal("10000"),
        es_cuenta_corriente=True,
    ))
    mov = MovimientoCaja(
        fecha=hoy, tipo_operacion="Ingreso", monto=Decimal("3000"),
        caja_destino="cl", hash_dedupe="hap",
    )
    db.add(mov)
    db.commit()
    db.refresh(mov)
    db.add(PagoAplicado(id_venta="pap", id_movimiento=mov.id, monto=Decimal("3000")))
    db.commit()

    out = aging_cobros(db)
    item = next(i for i in out["items"] if i["id_cliente"] == 42)
    # Total bruto era 10000, aplicado 3000 → saldo neto 7000 en bucket 0-30
    assert item["bucket_0_30"] == 7000.0
    assert item["total"] == 7000.0


def test_aging_con_pagos_aplicados_no_double_count(db):
    """Si el movimiento tiene id_cliente_relacionado Y pagos_aplicados,
    el aplicado se descuenta del cliente-nivel para no contar dos veces."""
    from datetime import date, timedelta
    from app.models.pago_aplicado import PagoAplicado
    hoy = date.today()
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    # Venta de 10000, va al bucket 0-30
    db.add(Venta(
        id_pedido="pdc", id_venta="vdc",
        fecha=datetime.combine(hoy - timedelta(days=5), datetime.min.time()),
        id_cliente=77, cliente="DC", total=Decimal("10000"),
        es_cuenta_corriente=True,
    ))
    # Movimiento de 3000 que tiene cliente Y se aplica explícitamente
    mov = MovimientoCaja(
        fecha=hoy, tipo_operacion="Ingreso", monto=Decimal("3000"),
        caja_destino="cl", id_cliente_relacionado=77, hash_dedupe="hdc",
    )
    db.add(mov)
    db.commit()
    db.refresh(mov)
    db.add(PagoAplicado(id_venta="pdc", id_movimiento=mov.id, monto=Decimal("3000")))
    db.commit()

    out = aging_cobros(db)
    item = next(i for i in out["items"] if i["id_cliente"] == 77)
    # NO debe ser 4000 (10000 - 3000 venta-nivel - 3000 cliente-nivel = 4000).
    # Debe ser 7000 (sólo se cuenta una vez la cobertura).
    assert item["total"] == 7000.0
