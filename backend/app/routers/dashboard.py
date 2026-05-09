"""Dashboard ejecutivo: resumen consolidado para Dirección/Gerencia."""

import calendar
import re
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

import logging

from app.db import get_db
from app.kpis import caja, comerciales

logger = logging.getLogger("kpi")
from app.kpis._fechas import filtro_fecha, hoy_ar
from app.models.venta import Venta
from app.routers._pdf_reporte_mensual import render_reporte_mensual_pdf
from app.routers.alertas_router import obtener_alertas_cacheadas

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _delta_pct(actual, anterior):
    if anterior is None or anterior == 0:
        return None
    return ((actual - anterior) / abs(anterior)) * 100


@router.get("/direccion")
def direccion(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    db: Session = Depends(get_db),
):
    """Snapshot ejecutivo. Si no hay rango, usa últimos 30 días.

    NOTA sobre cold-open vs sessionStorage del frontend: este endpoint
    detecta cold-open por `desde is None and hasta is None`. El frontend
    (Direccion.jsx) usa useStoredState para persistir filtros entre F5,
    así que solo cae en cold-open al abrir pestaña nueva o tras "Limpiar
    todo" (que setea desde/hasta a "" y el frontend no los manda).
    Refresh con filtro previo NO es cold-open — usará la rama filtrada.
    """
    # Trackeamos si la dueña realmente especificó filtro o estamos en
    # cold-open default. Afecta cómo se construye el chart (ver más abajo).
    sin_filtro = desde is None and hasta is None
    if hasta is None:
        hasta = hoy_ar()
    if desde is None:
        desde = hasta - timedelta(days=29)

    dias = (hasta - desde).days + 1
    hasta_prev = desde - timedelta(days=1)
    desde_prev = hasta_prev - timedelta(days=dias - 1)

    actual = comerciales.resumen(db, desde=desde, hasta=hasta)
    anterior = comerciales.resumen(db, desde=desde_prev, hasta=hasta_prev)

    # Serie temporal: lógica diferenciada cold-open vs filtrado.
    # Decisión de jurado adversarial:
    # - Cold-open (sin filtro): chart panorámico 12 meses MENSUAL —
    #   la dueña abre la página para "ver cómo va el negocio", no para
    #   ver detalle del día. KPIs cubren la vista operacional 30d con
    #   delta vs período previo; el chart aporta contexto macro y
    #   estacionalidad (verano, vuelta al cole, fin de año).
    # - Filtrado: chart adapta granularidad al rango (dia/semana/mes)
    #   según los thresholds, así "Últimos 30 días" muestra 30 puntos
    #   diarios coherentes con el filtro elegido.
    # Asimetría KPIs 30d + chart 12m en cold-open es deliberada: cada
    # componente responde una pregunta distinta. El frontend usa
    # `rango_serie` (devuelto abajo) para comunicar el rango del chart
    # cuando difiere del de los KPIs.
    if sin_filtro:
        # 370 = 365 días + 5 de margen para garantizar que tras
        # `.replace(day=1)` caiga al menos 12 meses atrás, sin importar
        # la fecha en que se ejecute (caso límite: 1 de mes).
        desde_chart = (hasta.replace(day=1) - timedelta(days=370)).replace(day=1)
        periodo_serie = "mes"
        serie = comerciales.serie_temporal(
            db, periodo="mes", desde=desde_chart, hasta=hasta,
        )
    else:
        desde_chart = desde
        if dias <= 60:
            periodo_serie = "dia"
        elif dias <= 180:
            periodo_serie = "semana"
        else:
            periodo_serie = "mes"
        serie = comerciales.serie_temporal(
            db, periodo=periodo_serie, desde=desde, hasta=hasta,
        )
    saldos = caja.saldos_por_caja(db)
    composicion = caja.composicion_gastos(db, desde=desde, hasta=hasta, agrupar_por="familia")

    saldo_total = sum(s["saldo"] for s in saldos)

    top_productos = comerciales.top_productos(db, por="margen", desde=desde, hasta=hasta, limite=5)
    top_vendedores = comerciales.top_vendedores(db, desde=desde, hasta=hasta, limite=5)

    q_vend = db.query(func.count(distinct(Venta.vendedor))).filter(Venta.vendedor.isnot(None))
    q_vend = filtro_fecha(q_vend, Venta.fecha, desde, hasta)
    vendedores_activos = q_vend.scalar() or 0

    return {
        "rango": {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "dias": dias},
        "rango_anterior": {"desde": desde_prev.isoformat(), "hasta": hasta_prev.isoformat()},
        "kpis": {
            "ventas": {
                "actual": actual["ventas_totales"],
                "anterior": anterior["ventas_totales"],
                "delta_pct": _delta_pct(actual["ventas_totales"], anterior["ventas_totales"]),
            },
            "margen_bruto": {
                "actual": actual["margen_bruto"],
                "anterior": anterior["margen_bruto"],
                "delta_pct": _delta_pct(actual["margen_bruto"], anterior["margen_bruto"]),
                "margen_pct_actual": actual["margen_pct"],
                "margen_pct_anterior": anterior["margen_pct"],
            },
            "pedidos": {
                "actual": actual["pedidos"],
                "anterior": anterior["pedidos"],
                "delta_pct": _delta_pct(actual["pedidos"], anterior["pedidos"]),
            },
            "ticket_promedio": {
                "actual": actual["ticket_promedio"],
                "anterior": anterior["ticket_promedio"],
                "delta_pct": _delta_pct(actual["ticket_promedio"], anterior["ticket_promedio"]),
            },
            "clientes_unicos": {
                "actual": actual["clientes_unicos"],
                "anterior": anterior["clientes_unicos"],
                "delta_pct": _delta_pct(actual["clientes_unicos"], anterior["clientes_unicos"]),
            },
            "clientes_nuevos": {
                "actual": actual["clientes_nuevos"],
                "anterior": anterior["clientes_nuevos"],
                "delta_pct": _delta_pct(actual["clientes_nuevos"], anterior["clientes_nuevos"]),
            },
            "vendedores_activos": vendedores_activos,
            "saldo_total_caja": saldo_total,
        },
        # `evolucion` (antes `evolucion_mensual`): renombrado porque ahora
        # la granularidad es adaptive (dia/semana/mes) según el rango filtrado.
        # `periodo_serie` informa al frontend qué granularidad recibió para
        # ajustar el título. Sin truncar a [-6:] — la serie ya viene acotada
        # por el filtro de fecha del usuario.
        "evolucion": serie,
        "periodo_serie": periodo_serie,
        # `rango_serie` permite al frontend comunicar el rango real del chart
        # cuando difiere del de los KPIs (cold-open: KPIs 30d, chart 12m).
        # Sin esto, el frontend muestra el rango del filtro arriba y la dueña
        # ve un chart que no coincide → asimetría parece bug.
        "rango_serie": {
            "desde": desde_chart.isoformat(),
            "hasta": hasta.isoformat(),
        },
        "top_productos": top_productos,
        "top_vendedores": top_vendedores,
        "top_cajas": saldos[:5],
        "composicion_gastos": composicion,
    }


def _mes_a_rango(mes: str | None) -> tuple[date, date]:
    """Resuelve un parámetro `mes=YYYY-MM` a (primer día, último día).
    Si no se pasa, devuelve el mes pasado completo (default razonable
    para "reporte de cierre del mes anterior")."""
    if mes is None:
        hoy = hoy_ar()
        # Primer día del mes actual menos 1 → último día del mes anterior
        ultimo_mes_pasado = hoy.replace(day=1) - timedelta(days=1)
        primero = ultimo_mes_pasado.replace(day=1)
        return primero, ultimo_mes_pasado
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", mes):
        raise HTTPException(400, "mes debe tener formato YYYY-MM")
    anio, m = int(mes[:4]), int(mes[5:])
    primero = date(anio, m, 1)
    # Mes íntegramente futuro no tiene reporte posible. Sin esta guarda,
    # `hasta` se cape a hoy y `dias` queda negativo (rango invertido) →
    # delta_pct y queries de período comparativo dan resultados absurdos.
    if primero > hoy_ar():
        raise HTTPException(400, "mes futuro: no hay datos posibles para reportar")
    ult_dia = calendar.monthrange(anio, m)[1]
    ultimo = date(anio, m, ult_dia)
    if ultimo > hoy_ar():
        # Mes en curso → cap a hoy. El caller marca "(parcial)" en el título.
        ultimo = hoy_ar()
    return primero, ultimo


@router.get("/reporte-mensual.pdf")
def reporte_mensual_pdf(
    mes: str | None = Query(None, description="YYYY-MM. Default: mes pasado completo"),
    db: Session = Depends(get_db),
):
    """PDF de 1 página con KPIs del mes + top productos/clientes/vendedores
    + alertas activas. Pensado para mandar al contador o archivar."""
    desde, hasta = _mes_a_rango(mes)
    dias = (hasta - desde).days + 1
    hasta_prev = desde - timedelta(days=1)
    desde_prev = hasta_prev - timedelta(days=dias - 1)

    from app.kpis import financieros
    actual = comerciales.resumen(db, desde=desde, hasta=hasta)
    anterior = comerciales.resumen(db, desde=desde_prev, hasta=hasta_prev)
    top_prod = comerciales.top_productos(db, por="margen", desde=desde, hasta=hasta, limite=5)
    top_cli = comerciales.top_clientes(db, desde=desde, hasta=hasta, limite=5)
    top_vend = comerciales.top_vendedores(db, desde=desde, hasta=hasta, limite=5)
    # Indicadores financieros adicionales: opcionales en el PDF — si una
    # falla, el reporte se emite igual sin el bloque (mejor que 500).
    def _try(fn):
        try:
            return fn()
        except Exception as e:
            logger.warning("Cómputo financiero falló para PDF mensual: %r", e)
            return None
    margen_op = _try(lambda: financieros.margen_operativo(db, desde=desde, hasta=hasta))
    dpo = _try(lambda: financieros.dpo_promedio(db))
    dependencia = _try(lambda: financieros.dependencia_proveedores(db, desde=desde, hasta=hasta, top=1))
    # Cache TTL 30s (alertas_router): evita re-correr todas las queries
    # pesadas si el dueño descarga el reporte varias veces seguidas.
    alertas_activas = obtener_alertas_cacheadas(db)

    kpis = {
        "ventas": {
            "actual": actual["ventas_totales"],
            "delta_pct": _delta_pct(actual["ventas_totales"], anterior["ventas_totales"]),
        },
        "margen_bruto": {
            "actual": actual["margen_bruto"],
            "delta_pct": _delta_pct(actual["margen_bruto"], anterior["margen_bruto"]),
            "margen_pct_actual": actual["margen_pct"],
        },
        "ticket_promedio": {
            "actual": actual["ticket_promedio"],
            "delta_pct": _delta_pct(actual["ticket_promedio"], anterior["ticket_promedio"]),
        },
        "clientes_unicos": {
            "actual": actual["clientes_unicos"],
            "delta_pct": _delta_pct(actual["clientes_unicos"], anterior["clientes_unicos"]),
        },
    }

    # Marca de "parcial" si el reporte es del mes en curso (hasta < último
    # día real del mes). El dueño que ve solo el título grande no debería
    # confundir un reporte parcial con un cierre de mes.
    ult_dia_mes = calendar.monthrange(desde.year, desde.month)[1]
    es_parcial = hasta.day < ult_dia_mes
    titulo_base = f"Reporte mensual ejecutivo · {desde.strftime('%B %Y').capitalize()}"
    if es_parcial:
        titulo_base += f" (parcial al {hasta.strftime('%d/%m')})"

    pdf = render_reporte_mensual_pdf(
        titulo=titulo_base,
        rango={"desde": desde.isoformat(), "hasta": hasta.isoformat(), "dias": dias},
        rango_anterior={"desde": desde_prev.isoformat(), "hasta": hasta_prev.isoformat()},
        kpis=kpis,
        top_productos=top_prod,
        top_clientes=top_cli,
        top_vendedores=top_vend,
        alertas=alertas_activas,
        margen_op=margen_op,
        dpo=dpo,
        dependencia=dependencia,
    )
    nombre_mes = desde.strftime("%Y-%m")
    hoy = date.today().isoformat()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="reporte_mensual_{nombre_mes}_{hoy}.pdf"'},
    )
