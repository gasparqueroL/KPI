"""Tests del módulo proveedores."""
from datetime import date, timedelta
from decimal import Decimal

from app.kpis.proveedores import (
    aging_proveedores,
    ledger_proveedor,
    proveedores_con_saldo,
    vencimientos_proximos,
)
from app.models.caja import Caja
from app.models.movimiento_caja import MovimientoCaja
from app.models.proveedor import FacturaProveedor, Proveedor


def _setup(db):
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    p = Proveedor(nombre="Insumos SA", cuit="30-12345678-9")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_proveedor_sin_facturas_tiene_saldo_cero(db):
    p = _setup(db)
    out = proveedores_con_saldo(db)
    assert len(out) == 1
    assert out[0]["nombre"] == "Insumos SA"
    assert out[0]["saldo"] == 0.0


def test_factura_genera_saldo_pendiente(db):
    p = _setup(db)
    db.add(FacturaProveedor(
        id_proveedor=p.id, numero="A-001",
        fecha_emision=date(2026, 4, 1),
        total=Decimal("10000"),
    ))
    db.commit()

    out = proveedores_con_saldo(db)
    assert out[0]["saldo"] == 10000.0
    assert out[0]["facturado_total"] == 10000.0
    assert out[0]["pagado_total"] == 0.0


def test_pago_vinculado_reduce_saldo(db):
    p = _setup(db)
    f = FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date(2026, 4, 1),
        total=Decimal("10000"),
    )
    db.add(f)
    db.commit()
    db.refresh(f)

    db.add(MovimientoCaja(
        fecha=date(2026, 4, 15),
        tipo_operacion="Materia Prima",
        monto=Decimal("3000"),
        caja_origen="cl",
        id_factura_proveedor=f.id,
        hash_dedupe="hp1",
    ))
    db.commit()

    out = proveedores_con_saldo(db)
    assert out[0]["pagado_total"] == 3000.0
    assert out[0]["saldo"] == 7000.0

    led = ledger_proveedor(db, p.id)
    assert led["saldo_actual"] == 7000.0
    assert led["total_debe"] == 10000.0
    assert led["total_haber"] == 3000.0
    assert len(led["eventos"]) == 2
    assert led["eventos"][0]["tipo"] == "factura"
    assert led["eventos"][1]["tipo"] == "pago"


def test_vencimientos_proximos_filtra_pagadas(db):
    p = _setup(db)
    hoy = date.today()
    db.add(FacturaProveedor(
        id_proveedor=p.id, fecha_emision=hoy,
        fecha_vencimiento=hoy + timedelta(days=10),
        total=Decimal("5000"),
    ))
    f_pagada = FacturaProveedor(
        id_proveedor=p.id, fecha_emision=hoy,
        fecha_vencimiento=hoy + timedelta(days=5),
        total=Decimal("2000"),
    )
    db.add(f_pagada)
    db.commit()
    db.refresh(f_pagada)
    db.add(MovimientoCaja(
        fecha=hoy, tipo_operacion="Materia Prima", monto=Decimal("2000"),
        caja_origen="cl", id_factura_proveedor=f_pagada.id, hash_dedupe="hp2",
    ))
    db.commit()

    out = vencimientos_proximos(db, dias_ventana=30)
    assert len(out) == 1, "la factura pagada no debe aparecer"
    assert out[0]["pendiente"] == 5000.0


def test_factura_anulada_se_excluye_de_saldo_y_vencimientos(db):
    """Soft-delete: anulada=True excluye de proveedores_con_saldo,
    vencimientos_proximos y aging_proveedores."""
    p = _setup(db)
    f = FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date(2026, 4, 1),
        fecha_vencimiento=date(2026, 5, 1),
        total=Decimal("5000"),
        anulada=True,
    )
    db.add(f)
    db.commit()

    # No aparece en saldo
    out = proveedores_con_saldo(db)
    assert out[0]["facturado_total"] == 0.0
    assert out[0]["saldo"] == 0.0

    # No aparece en vencimientos
    venc = vencimientos_proximos(db, dias_ventana=365)
    assert venc == []

    # No aparece en aging
    ag = aging_proveedores(db)
    assert ag["items"] == []
    assert ag["totales"]["total"] == 0.0


def test_proveedor_inactivo_se_oculta_por_default(db):
    """activo=False oculta el proveedor del listado salvo incluir_inactivos."""
    p = _setup(db)
    p.activo = False
    db.commit()

    out_default = proveedores_con_saldo(db)
    assert out_default == [], "proveedor inactivo debe ocultarse por default"

    out_all = proveedores_con_saldo(db, incluir_inactivos=True)
    assert len(out_all) == 1
    assert out_all[0]["activo"] is False


def test_ledger_expone_pendiente_y_observaciones(db):
    """ledger devuelve pendiente por factura para que el front filtre."""
    p = _setup(db)
    f = FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date(2026, 4, 1),
        total=Decimal("10000"),
        observaciones="Compra de prueba",
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 15), tipo_operacion="Materia Prima",
        monto=Decimal("3000"), caja_origen="cl",
        id_factura_proveedor=f.id, hash_dedupe="hp_pend",
    ))
    db.commit()

    led = ledger_proveedor(db, p.id)
    factura_evt = next(e for e in led["eventos"] if e["tipo"] == "factura")
    assert factura_evt["pendiente"] == 7000.0
    assert factura_evt["observaciones"] == "Compra de prueba"
    assert factura_evt["anulada"] is False


def test_aging_proveedores_buckets_por_vencimiento(db):
    """Aging por vencimiento ubica facturas en el bucket correcto."""
    p = _setup(db)
    hoy = date.today()
    db.add_all([
        # 0-30: vence en 5 días
        FacturaProveedor(id_proveedor=p.id, fecha_emision=hoy,
                         fecha_vencimiento=hoy - timedelta(days=10), total=Decimal("1000")),
        # 31-60: vencida hace 45 días
        FacturaProveedor(id_proveedor=p.id, fecha_emision=hoy - timedelta(days=60),
                         fecha_vencimiento=hoy - timedelta(days=45), total=Decimal("2000")),
        # 90+: vencida hace 120 días
        FacturaProveedor(id_proveedor=p.id, fecha_emision=hoy - timedelta(days=150),
                         fecha_vencimiento=hoy - timedelta(days=120), total=Decimal("3000")),
    ])
    db.commit()

    ag = aging_proveedores(db, base="vencimiento")
    assert len(ag["items"]) == 1
    item = ag["items"][0]
    assert item["bucket_0_30"] == 1000.0
    assert item["bucket_31_60"] == 2000.0
    assert item["bucket_90_mas"] == 3000.0
    assert item["total"] == 6000.0


def test_aging_proveedores_factura_saldada_se_excluye(db):
    """Si una factura está totalmente pagada, NO entra en aging."""
    p = _setup(db)
    f = FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date(2026, 4, 1),
        fecha_vencimiento=date(2026, 4, 15),
        total=Decimal("5000"),
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 20), tipo_operacion="Materia Prima",
        monto=Decimal("5000"), caja_origen="cl",
        id_factura_proveedor=f.id, hash_dedupe="hps",
    ))
    db.commit()

    ag = aging_proveedores(db)
    assert ag["items"] == []
