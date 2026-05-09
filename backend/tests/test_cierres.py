"""Tests del módulo de cierre de caja."""
from datetime import date, datetime
from decimal import Decimal

from app.kpis.cierres import (
    auditar_cierres,
    caja_esta_bloqueada,
    fecha_ultimo_cierre,
    saldo_caja_al,
)
from app.models.caja import Caja
from app.models.cierre_caja import CierreCaja
from app.models.movimiento_caja import MovimientoCaja
from app.models.venta import Venta


def _setup(db):
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.commit()


def test_saldo_caja_al_suma_ventas_y_movimientos(db):
    _setup(db)
    db.add(Venta(
        id_pedido="p1", id_venta="v1",
        fecha=datetime(2026, 4, 10, 12, 0),
        id_cliente=1, cliente="X", total=Decimal("1000"),
        monto_pago1=Decimal("1000"), caja1="cl",
    ))
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 12), tipo_operacion="Sueldo",
        monto=Decimal("300"), caja_origen="cl", hash_dedupe="h1",
    ))
    db.commit()

    assert saldo_caja_al(db, "cl", date(2026, 4, 15)) == Decimal("700")
    # Antes del egreso del 12: saldo es solo 1000
    assert saldo_caja_al(db, "cl", date(2026, 4, 11)) == Decimal("1000")


def test_caja_bloqueada_si_hay_cierre(db):
    _setup(db)
    db.add(CierreCaja(fecha=date(2026, 4, 30), caja="cl", saldo_cierre=Decimal("0")))
    db.commit()
    assert caja_esta_bloqueada(db, "cl", date(2026, 4, 15)) is True
    assert caja_esta_bloqueada(db, "cl", date(2026, 4, 30)) is True
    assert caja_esta_bloqueada(db, "cl", date(2026, 5, 1)) is False
    assert fecha_ultimo_cierre(db, "cl") == date(2026, 4, 30)
    assert fecha_ultimo_cierre(db, "otra") is None


def test_reabrir_cierre_intermedio_no_desbloquea_meses_anteriores(db):
    """Antes el bug: caja_esta_bloqueada usaba MAX(fecha). Reabrir el último
    desbloqueaba todo. Ahora usa EXISTS, los anteriores siguen bloqueando."""
    _setup(db)
    db.add(CierreCaja(fecha=date(2026, 3, 31), caja="cl", saldo_cierre=Decimal("0")))
    db.add(CierreCaja(fecha=date(2026, 4, 30), caja="cl", saldo_cierre=Decimal("0")))
    db.commit()
    # Borrar el cierre de abril (simula reabrir el último).
    cierre_abril = db.query(CierreCaja).filter(CierreCaja.fecha == date(2026, 4, 30)).first()
    db.delete(cierre_abril)
    db.commit()
    # Marzo SIGUE bloqueando cualquier fecha <= 31/3.
    assert caja_esta_bloqueada(db, "cl", date(2026, 3, 15)) is True
    assert caja_esta_bloqueada(db, "cl", date(2026, 3, 31)) is True
    # Abril ya no está bloqueado.
    assert caja_esta_bloqueada(db, "cl", date(2026, 4, 10)) is False


def test_saldo_caja_incluye_movimiento_del_dia_de_cierre(db):
    """Borde: un movimiento con fecha == fecha_cierre debe contar en el saldo."""
    _setup(db)
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 30), tipo_operacion="Ingreso",
        monto=Decimal("500"), caja_destino="cl", hash_dedupe="hb1",
    ))
    db.commit()
    assert saldo_caja_al(db, "cl", date(2026, 4, 30)) == Decimal("500")


def test_auditar_cierres_detecta_diff(db):
    """Cierre declarado $1000 pero saldo real calculado $1500 → diff $500."""
    _setup(db)
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 30), tipo_operacion="Ingreso",
        monto=Decimal("1500"), caja_destino="cl", hash_dedupe="ha1",
    ))
    db.add(CierreCaja(
        fecha=date(2026, 4, 30), caja="cl", saldo_cierre=Decimal("1000"),
    ))
    db.commit()

    out = auditar_cierres(db, tolerancia=Decimal("100"))
    assert len(out) == 1
    assert out[0]["caja"] == "cl"
    assert out[0]["saldo_declarado"] == 1000.0
    assert out[0]["saldo_calculado"] == 1500.0
    assert out[0]["diff"] == 500.0
    assert out[0]["tiene_diff"] is True


def test_auditar_cierres_ignora_diff_dentro_de_tolerancia(db):
    """Diff de $50 con tolerancia $100 → no se reporta."""
    _setup(db)
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 30), tipo_operacion="Ingreso",
        monto=Decimal("1050"), caja_destino="cl", hash_dedupe="ha2",
    ))
    db.add(CierreCaja(
        fecha=date(2026, 4, 30), caja="cl", saldo_cierre=Decimal("1000"),
    ))
    db.commit()

    out = auditar_cierres(db, tolerancia=Decimal("100"))
    assert out == []


def test_auditar_cierres_solo_con_diff_false_devuelve_todos(db):
    """Cuando solo_con_diff=False, debe devolver todos aunque coincidan."""
    _setup(db)
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 30), tipo_operacion="Ingreso",
        monto=Decimal("1000"), caja_destino="cl", hash_dedupe="ha3",
    ))
    db.add(CierreCaja(
        fecha=date(2026, 4, 30), caja="cl", saldo_cierre=Decimal("1000"),
    ))
    db.commit()

    out = auditar_cierres(db, solo_con_diff=False)
    assert len(out) == 1
    assert out[0]["tiene_diff"] is False
    assert out[0]["diff"] == 0.0

