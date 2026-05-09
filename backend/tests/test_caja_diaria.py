"""Tests de operaciones diarias de caja."""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.importers.base import hash_row
from app.models.caja import Caja
from app.models.categoria_caja import CategoriaCaja
from app.models.movimiento_caja import MovimientoCaja
from app.routers.caja_diaria_router import EditarMovimiento, editar_movimiento, eliminar_movimiento


def _setup_basico(db):
    db.add(Caja(nombre_normalizado="cajalocal", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.add(CategoriaCaja(tipo_operacion="Sueldo", familia="Personal"))
    db.commit()


def test_editar_movimiento_a_uno_que_ya_existe_devuelve_409(db):
    _setup_basico(db)
    h1 = hash_row("2026-04-01", "Sueldo", "ana", "100.00", "cajalocal", "")
    h2 = hash_row("2026-04-01", "Sueldo", "bea", "100.00", "cajalocal", "")
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 1), tipo_operacion="Sueldo", detalle="ana",
        monto=Decimal("100.00"), caja_origen="cajalocal", hash_dedupe=h1,
    ))
    m2 = MovimientoCaja(
        fecha=date(2026, 4, 1), tipo_operacion="Sueldo", detalle="bea",
        monto=Decimal("100.00"), caja_origen="cajalocal", hash_dedupe=h2,
    )
    db.add(m2)
    db.commit()

    # Editar m2 para que tenga el mismo detalle que el primero -> hash colisiona
    data = EditarMovimiento(detalle="ana")
    with pytest.raises(HTTPException) as exc_info:
        editar_movimiento(m2.id, data, db)
    assert exc_info.value.status_code == 409
    assert "duplicado" in exc_info.value.detail.lower() or "ya existe" in exc_info.value.detail.lower()


from datetime import date as _date

from app.models.cierre_caja import CierreCaja


def test_editar_movimiento_en_caja_cerrada_devuelve_403(db):
    _setup_basico(db)
    db.add(MovimientoCaja(
        fecha=_date(2026, 4, 1), tipo_operacion="Sueldo", detalle="x",
        monto=Decimal("100"), caja_origen="cajalocal", hash_dedupe="hX",
    ))
    db.add(CierreCaja(fecha=_date(2026, 4, 30), caja="cajalocal", saldo_cierre=Decimal("0")))
    db.commit()
    m = db.query(MovimientoCaja).first()

    with pytest.raises(HTTPException) as exc_info:
        editar_movimiento(m.id, EditarMovimiento(detalle="otro"), db)
    assert exc_info.value.status_code == 403
    assert "cerrada" in exc_info.value.detail.lower()


def test_eliminar_movimiento_en_caja_cerrada_devuelve_403(db):
    _setup_basico(db)
    db.add(MovimientoCaja(
        fecha=_date(2026, 4, 1), tipo_operacion="Sueldo", detalle="x",
        monto=Decimal("100"), caja_origen="cajalocal", hash_dedupe="hY",
    ))
    db.add(CierreCaja(fecha=_date(2026, 4, 30), caja="cajalocal", saldo_cierre=Decimal("0")))
    db.commit()
    m = db.query(MovimientoCaja).first()

    with pytest.raises(HTTPException) as exc_info:
        eliminar_movimiento(m.id, db)
    assert exc_info.value.status_code == 403


def test_movimiento_posterior_al_cierre_se_puede_editar(db):
    _setup_basico(db)
    db.add(MovimientoCaja(
        fecha=_date(2026, 5, 5), tipo_operacion="Sueldo", detalle="ok",
        monto=Decimal("100"), caja_origen="cajalocal", hash_dedupe="hZ",
    ))
    db.add(CierreCaja(fecha=_date(2026, 4, 30), caja="cajalocal", saldo_cierre=Decimal("0")))
    db.commit()
    m = db.query(MovimientoCaja).first()

    res = editar_movimiento(m.id, EditarMovimiento(detalle="cambiado"), db)
    assert res["ok"] is True
