"""Tests de KPIs de caja."""
from datetime import date, datetime
from decimal import Decimal

from datetime import timedelta

from app.kpis.caja import (
    actividad_dia,
    flujo_caja,
    movimientos_atipicos,
    movimientos_por_familia,
)
from app.models.caja import Caja
from app.models.categoria_caja import CategoriaCaja
from app.models.movimiento_caja import MovimientoCaja
from app.models.venta import Venta


def test_flujo_incluye_ventas_del_dia_tope(db):
    """Una venta del 30/4 a las 18:00 debe contar en el flujo cuando
    el filtro es hasta=2026-04-30."""
    db.add(Caja(nombre_normalizado="c1", nombre_display="C1", tipo="operativa"))
    db.add(Venta(
        id_pedido="p1", id_venta="v1",
        fecha=datetime(2026, 4, 30, 18, 0),  # tarde del último día
        id_cliente=1, cliente="X", total=Decimal("1000"),
        monto_pago1=Decimal("1000"), caja1="c1",
    ))
    db.commit()

    serie = flujo_caja(db, periodo="mes",
                       desde=date(2026, 4, 1), hasta=date(2026, 4, 30))
    abr = next((s for s in serie if s["periodo"] == "2026-04"), None)
    assert abr is not None, "Abril 2026 debe aparecer en la serie"
    assert abr["ingresos_ventas"] == 1000.0, (
        f"La venta del 30/4 18:00 no aparece (got {abr['ingresos_ventas']})"
    )


# ===== Tests de movimientos_por_familia (drill-down) =====

def _setup_familia(db):
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.add(CategoriaCaja(tipo_operacion="Materia Prima", familia="Materia Prima"))
    db.add(CategoriaCaja(tipo_operacion="Sueldo", familia="Sueldos"))
    # Categoría sin familia para testear "Sin clasificar"
    db.add(CategoriaCaja(tipo_operacion="Algo Raro", familia=None))
    db.commit()


def test_movs_por_familia_filtra_por_familia(db):
    _setup_familia(db)
    db.add_all([
        MovimientoCaja(fecha=date(2026, 4, 1), tipo_operacion="Materia Prima",
                       monto=Decimal("1000"), caja_origen="cl",
                       detalle="Botellas", hash_dedupe="hf1"),
        MovimientoCaja(fecha=date(2026, 4, 2), tipo_operacion="Sueldo",
                       monto=Decimal("50000"), caja_origen="cl",
                       detalle="Juan", hash_dedupe="hf2"),
        MovimientoCaja(fecha=date(2026, 4, 3), tipo_operacion="Materia Prima",
                       monto=Decimal("2000"), caja_origen="cl",
                       detalle="Detergente", hash_dedupe="hf3"),
    ])
    db.commit()

    out = movimientos_por_familia(db, familia="Materia Prima")
    assert len(out) == 2
    # Ordenado por fecha desc — el del 3/4 primero
    assert out[0]["detalle"] == "Detergente"
    assert out[1]["detalle"] == "Botellas"
    assert all(m["familia"] == "Materia Prima" for m in out)


def test_movs_por_familia_sin_clasificar(db):
    """Familia 'Sin clasificar' agrupa los tipos sin familia asignada."""
    _setup_familia(db)
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 1), tipo_operacion="Algo Raro",
        monto=Decimal("500"), caja_origen="cl", hash_dedupe="hsc1",
    ))
    db.commit()

    out = movimientos_por_familia(db, familia="Sin clasificar")
    assert len(out) == 1
    assert out[0]["familia"] == "Sin clasificar"


def test_movs_por_familia_excluye_transferencias(db):
    """Solo egresos puros (origen sin destino) — coherente con composicion_gastos."""
    _setup_familia(db)
    db.add(Caja(nombre_normalizado="cl2", nombre_display="CAJA 2", tipo="operativa"))
    db.commit()
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 1), tipo_operacion="Materia Prima",
        monto=Decimal("1000"), caja_origen="cl", caja_destino="cl2",  # transferencia
        hash_dedupe="hft1",
    ))
    db.commit()

    out = movimientos_por_familia(db, familia="Materia Prima")
    assert out == []


def test_movs_por_familia_filtra_por_fecha(db):
    _setup_familia(db)
    db.add_all([
        MovimientoCaja(fecha=date(2026, 3, 20), tipo_operacion="Materia Prima",
                       monto=Decimal("100"), caja_origen="cl", hash_dedupe="hfd1"),
        MovimientoCaja(fecha=date(2026, 4, 15), tipo_operacion="Materia Prima",
                       monto=Decimal("200"), caja_origen="cl", hash_dedupe="hfd2"),
    ])
    db.commit()

    out = movimientos_por_familia(
        db, familia="Materia Prima",
        desde=date(2026, 4, 1), hasta=date(2026, 4, 30),
    )
    assert len(out) == 1
    assert out[0]["monto"] == 200.0


# ===== Tests de movimientos_atipicos =====

def _setup_atipicos(db):
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.commit()


def _mov_dias_atras(dias, monto, tipo_op="Compra", detalle=None, hd=None):
    return MovimientoCaja(
        fecha=date.today() - timedelta(days=dias),
        tipo_operacion=tipo_op,
        monto=Decimal(str(monto)),
        caja_origen="cl",
        detalle=detalle,
        hash_dedupe=hd or f"h{dias}_{monto}",
    )


def test_atipicos_detecta_typo_obvio(db):
    """Histórico de Compra ~$1000, aparece $50.000 → atípico (50× promedio)."""
    _setup_atipicos(db)
    # 5 movs históricos de ~$1000 (40-90 días atrás)
    db.add_all([_mov_dias_atras(d, 1000, hd=f"hh{d}") for d in [40, 50, 60, 70, 80]])
    # Mov reciente atípico: $50000
    db.add(_mov_dias_atras(5, 50000, detalle="TYPO probable", hd="hatipico"))
    db.commit()

    out = movimientos_atipicos(db, factor=5.0)
    assert len(out) == 1
    assert out[0]["monto"] == 50000.0
    assert out[0]["ratio"] >= 5.0
    assert out[0]["promedio_historico"] == 1000.0


def test_atipicos_excluye_si_pocos_historicos(db):
    """Categoría con menos de minimo_historico movs no califica para comparar."""
    _setup_atipicos(db)
    # Solo 2 movs históricos (umbral default 3)
    db.add_all([_mov_dias_atras(d, 1000, hd=f"hh{d}") for d in [40, 50]])
    db.add(_mov_dias_atras(5, 50000, hd="ha"))
    db.commit()

    out = movimientos_atipicos(db, factor=5.0, minimo_historico=3)
    assert out == []  # historia insuficiente, no podemos juzgar


def test_atipicos_no_dispara_si_dentro_del_factor(db):
    """Mov reciente 3× promedio con factor=5 NO es atípico."""
    _setup_atipicos(db)
    db.add_all([_mov_dias_atras(d, 1000, hd=f"hh{d}") for d in [40, 50, 60, 70]])
    db.add(_mov_dias_atras(5, 3000, hd="ha"))  # 3× promedio
    db.commit()

    out = movimientos_atipicos(db, factor=5.0)
    assert out == []


def test_atipicos_orden_por_monto_desc(db):
    """Múltiples atípicos: mayor monto primero."""
    _setup_atipicos(db)
    db.add_all([_mov_dias_atras(d, 1000, hd=f"hh{d}") for d in [40, 50, 60]])
    db.add(_mov_dias_atras(5, 20000, detalle="medio", hd="ha1"))
    db.add(_mov_dias_atras(3, 80000, detalle="grande", hd="ha2"))
    db.commit()

    out = movimientos_atipicos(db, factor=5.0)
    assert len(out) == 2
    assert out[0]["detalle"] == "grande"
    assert out[1]["detalle"] == "medio"


def test_atipicos_excluye_transferencias(db):
    """Solo egresos puros — coherente con composicion_gastos."""
    _setup_atipicos(db)
    db.add(Caja(nombre_normalizado="cl2", nombre_display="CAJA 2", tipo="operativa"))
    db.commit()
    db.add_all([_mov_dias_atras(d, 1000, hd=f"hh{d}") for d in [40, 50, 60]])
    # Transferencia con monto absurdo: NO debería disparar atípico
    db.add(MovimientoCaja(
        fecha=date.today() - timedelta(days=5), tipo_operacion="Compra",
        monto=Decimal("100000"), caja_origen="cl", caja_destino="cl2",  # transferencia
        hash_dedupe="hatr",
    ))
    db.commit()

    out = movimientos_atipicos(db, factor=5.0)
    assert out == []


def test_atipicos_dataset_frio_no_rompe(db):
    """Sistema nuevo con < 90 días de historia: no hay baseline para juzgar.
    Función debe devolver [] sin romper, no levantar excepción."""
    _setup_atipicos(db)
    # Solo movs en últimos 20 días (no llega al período histórico 30-90)
    db.add_all([
        _mov_dias_atras(d, 1000, hd=f"hf{d}")
        for d in [5, 10, 15, 20]
    ])
    db.commit()

    out = movimientos_atipicos(db, factor=5.0)
    assert out == []


# ===== Tests de actividad_dia =====

def test_actividad_dia_compone_metricas(db):
    """Día con 1 venta + 1 ingreso + 2 egresos en distintas familias →
    todas las métricas computan correctamente."""
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.add(CategoriaCaja(tipo_operacion="Sueldo", familia="Sueldos"))
    db.add(CategoriaCaja(tipo_operacion="MP", familia="Materia Prima"))
    db.commit()
    f = date(2026, 4, 15)
    # Venta del día
    db.add(Venta(
        id_pedido="P1", id_venta="V1", id_cliente=1, cliente="X",
        fecha=datetime(2026, 4, 15, 14, 30), total=Decimal("5000"),
    ))
    # Ingreso operativo $3000
    db.add(MovimientoCaja(
        fecha=f, tipo_operacion="Cobro", monto=Decimal("3000"),
        caja_destino="cl", hash_dedupe="ha1",
    ))
    # 2 egresos (Sueldos $50000, Materia Prima $2000)
    db.add(MovimientoCaja(
        fecha=f, tipo_operacion="Sueldo", monto=Decimal("50000"),
        caja_origen="cl", hash_dedupe="ha2",
    ))
    db.add(MovimientoCaja(
        fecha=f, tipo_operacion="MP", monto=Decimal("2000"),
        caja_origen="cl", hash_dedupe="ha3",
    ))
    db.commit()

    out = actividad_dia(db, fecha=f)
    assert out["fecha"] == "2026-04-15"
    assert out["ventas_monto"] == 5000.0
    assert out["ventas_pedidos"] == 1
    assert out["ingresos_operativos"] == 3000.0
    assert out["egresos_operativos"] == 52000.0  # 50000 + 2000
    assert out["neto_operativo"] == -49000.0  # 3000 - 52000
    # Top familias: Sueldos primero ($50k), Materia Prima segundo ($2k)
    assert out["top_familias_gasto"][0]["familia"] == "Sueldos"
    assert out["top_familias_gasto"][0]["monto"] == 50000.0
    assert out["top_familias_gasto"][1]["familia"] == "Materia Prima"


def test_actividad_dia_sin_movimientos_devuelve_ceros(db):
    """Día sin actividad: estructura completa con todos los valores en 0."""
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.commit()
    out = actividad_dia(db, fecha=date(2026, 4, 15))
    assert out["ventas_monto"] == 0.0
    assert out["ingresos_operativos"] == 0.0
    assert out["egresos_operativos"] == 0.0
    assert out["neto_operativo"] == 0.0
    assert out["top_familias_gasto"] == []


def test_actividad_dia_endpoint_fecha_futura_400(db):
    """Endpoint REST rechaza fechas futuras (coherente con resumen-diario.pdf).
    El helper directo igual devuelve ceros — el guard está en el router."""
    from datetime import timedelta as _td
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app
    from app.db import get_db
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from sqlalchemy import create_engine
    from app.db import Base
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    def override_get_db():
        s = Session()
        try: yield s
        finally: s.close()
    fastapi_app.dependency_overrides[get_db] = override_get_db
    client = TestClient(fastapi_app)
    try:
        futuro = (date.today() + _td(days=10)).isoformat()
        r = client.get(f"/api/kpis/caja/actividad-dia?fecha={futuro}")
        assert r.status_code == 400
        assert "futura" in r.json()["detail"].lower()
    finally:
        fastapi_app.dependency_overrides.clear()


def test_actividad_dia_excluye_transferencias(db):
    """Transferencias entre cajas (ambos campos) NO cuentan como ingreso ni egreso."""
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.add(Caja(nombre_normalizado="cl2", nombre_display="CAJA 2", tipo="operativa"))
    db.commit()
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 15), tipo_operacion="Transferencia",
        monto=Decimal("10000"), caja_origen="cl", caja_destino="cl2",
        hash_dedupe="ht1",
    ))
    db.commit()

    out = actividad_dia(db, fecha=date(2026, 4, 15))
    assert out["ingresos_operativos"] == 0.0
    assert out["egresos_operativos"] == 0.0


def test_atipicos_promedio_cero_no_explota(db):
    """Si una categoría tiene todos los montos en 0 (promociones a costo
    cero), no debe dividir por 0 — descartamos la categoría como ruido."""
    _setup_atipicos(db)
    db.add_all([
        _mov_dias_atras(d, 0, tipo_op="Promo", hd=f"hp{d}")
        for d in [40, 50, 60, 70, 80]
    ])
    db.add(_mov_dias_atras(5, 1000, tipo_op="Promo", hd="ha"))
    db.commit()

    out = movimientos_atipicos(db, factor=5.0)
    assert out == []
