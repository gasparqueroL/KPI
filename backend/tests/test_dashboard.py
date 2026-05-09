"""Tests del endpoint /api/dashboard/direccion.

Foco: la asimetría cold-open (chart 12m mensual) vs filtrado (adaptive)
es decisión de jurado adversarial. Sin tests, un refactor podría romper
la asimetría sin que nadie lo note.

Llamamos al handler directo (sin TestClient HTTP) — más rápido y permite
acceso al `db` fixture en memoria sin override de dependencies.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.models.caja import Caja
from app.models.venta import Venta
from app.routers.dashboard import direccion


def _setup_data_minima(db):
    """Setup mínimo para que el endpoint no falle: 1 caja + algunas ventas
    distribuidas en distintos meses para que el chart tenga datos."""
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA", tipo="operativa"))
    # Ventas en los últimos 14 meses para cubrir cold-open chart.
    for i in range(14):
        f = date.today() - timedelta(days=i * 30)
        db.add(Venta(
            id_pedido=f"P-{i}", id_venta=f"V-{i}",
            id_cliente=1, cliente="X",
            fecha=datetime.combine(f, datetime.min.time()),
            total=Decimal("1000"),
            monto_pago1=Decimal("1000"), caja1="cl",
            vendedor="V1",
        ))
    db.commit()


def test_dashboard_cold_open_chart_panoramico_mensual(db):
    """Sin filtro (cold-open) → chart 12+ meses bucket mensual.
    Decisión de jurado: la dueña al abrir sin filtro quiere vista panorámica.
    KPIs siguen siendo 30d, chart cubre 12m → asimetría deliberada."""
    _setup_data_minima(db)

    out = direccion(desde=None, hasta=None, db=db)

    # KPIs son del default 30 días (los `dias` lo confirman).
    assert out["rango"]["dias"] == 30
    # Chart es panorámico mensual.
    assert out["periodo_serie"] == "mes"
    # Y al menos 12 puntos (puede ser 13 o 14 según fecha de hoy).
    assert len(out["evolucion"]) >= 12
    # `rango_serie` distinto de `rango`: chart cubre rango mayor.
    assert out["rango_serie"]["desde"] != out["rango"]["desde"]
    # Chart desde está al menos 12 meses antes que KPIs desde.
    desde_chart = date.fromisoformat(out["rango_serie"]["desde"])
    desde_kpi = date.fromisoformat(out["rango"]["desde"])
    assert (desde_kpi - desde_chart).days >= 365


def test_dashboard_filtrado_corto_chart_diario(db):
    """Filtro de rango chico (≤ 60 días) → bucket diario.
    Caso real: dueña clickea "Mes pasado" o "Últimos 30 días"."""
    _setup_data_minima(db)
    hoy = date.today()
    desde = hoy - timedelta(days=29)

    out = direccion(desde=desde, hasta=hoy, db=db)

    assert out["rango"]["dias"] == 30
    assert out["periodo_serie"] == "dia"
    # `rango_serie` coincide con `rango` (no panorámico).
    assert out["rango_serie"]["desde"] == out["rango"]["desde"]
    assert out["rango_serie"]["hasta"] == out["rango"]["hasta"]


def test_dashboard_filtrado_medio_chart_semanal(db):
    """Filtro 60 < dias ≤ 180 → bucket semanal.
    Caso real: "Últimos 3 meses" da ~90 días."""
    _setup_data_minima(db)
    hoy = date.today()
    desde = hoy - timedelta(days=89)  # 90 días

    out = direccion(desde=desde, hasta=hoy, db=db)

    assert out["rango"]["dias"] == 90
    assert out["periodo_serie"] == "semana"


def test_dashboard_filtrado_largo_chart_mensual(db):
    """Filtro > 180 días → bucket mensual.
    Caso real: "YTD" o "Año pasado" da 365 días."""
    _setup_data_minima(db)
    hoy = date.today()
    desde = hoy - timedelta(days=364)  # 365 días

    out = direccion(desde=desde, hasta=hoy, db=db)

    assert out["rango"]["dias"] == 365
    assert out["periodo_serie"] == "mes"


def test_dashboard_threshold_60_dias_es_diario(db):
    """Boundary: rango exactamente 60 días → bucket diario (≤ 60)."""
    _setup_data_minima(db)
    hoy = date.today()
    desde = hoy - timedelta(days=59)  # 60 días inclusivo

    out = direccion(desde=desde, hasta=hoy, db=db)

    assert out["rango"]["dias"] == 60
    assert out["periodo_serie"] == "dia"


def test_dashboard_threshold_61_dias_es_semanal(db):
    """Boundary: rango exactamente 61 días → bucket semanal (> 60)."""
    _setup_data_minima(db)
    hoy = date.today()
    desde = hoy - timedelta(days=60)  # 61 días inclusivo

    out = direccion(desde=desde, hasta=hoy, db=db)

    assert out["rango"]["dias"] == 61
    assert out["periodo_serie"] == "semana"


def test_dashboard_threshold_180_dias_es_semanal(db):
    """Boundary: 180 días exactos → semanal (≤ 180)."""
    _setup_data_minima(db)
    hoy = date.today()
    desde = hoy - timedelta(days=179)

    out = direccion(desde=desde, hasta=hoy, db=db)

    assert out["rango"]["dias"] == 180
    assert out["periodo_serie"] == "semana"


def test_dashboard_threshold_181_dias_es_mensual(db):
    """Boundary: 181 días → mensual (> 180)."""
    _setup_data_minima(db)
    hoy = date.today()
    desde = hoy - timedelta(days=180)

    out = direccion(desde=desde, hasta=hoy, db=db)

    assert out["rango"]["dias"] == 181
    assert out["periodo_serie"] == "mes"
