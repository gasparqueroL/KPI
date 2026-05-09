"""KPIs financieros computables desde los datos existentes (N1).

- Margen neto del período: ingresos por ventas - todos los egresos
  operativos (excluyendo retiros, transferencias internas, ajustes).
- Margen operativo: variante con definición ligeramente distinta —
  acá lo igualamos al neto (ya excluimos no-operativos), pero se
  expone con disclaimer.
- EBITDA aproximado: igual al margen operativo en ausencia de
  amortizaciones cargadas. Documentado en la respuesta.
- DPO (Days Payable Outstanding): días promedio que tarda en pagar
  facturas de proveedor desde la emisión.
- Dependencia de proveedores: % del costo total acumulado por cada
  proveedor (top N + concentración).
"""
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.kpis._fechas import filtro_fecha as _filtro_fecha, hoy_ar
from app.models.categoria_caja import CategoriaCaja
from app.models.movimiento_caja import MovimientoCaja
from app.models.proveedor import FacturaProveedor, Proveedor
from app.models.venta import Venta


def _to_float(v) -> float:
    return float(v) if v is not None else 0.0


def margen_operativo(
    db: Session,
    desde: date | None = None,
    hasta: date | None = None,
) -> dict[str, Any]:
    """Margen operativo del período = ingresos (ventas + cobranzas) -
    egresos puros operativos.

    Egresos operativos = `caja_origen IS NOT NULL AND caja_destino IS NULL`
    excluyendo categorías marcadas como `excluir_flujo`, `es_transferencia`
    o `es_retiro` (ajustes apertura, transferencias entre cajas, retiros
    del dueño no son gastos operativos del negocio).
    """
    # Ingresos por ventas
    qv = db.query(
        func.coalesce(
            func.sum(func.coalesce(Venta.monto_pago1, 0) + func.coalesce(Venta.monto_pago2, 0)),
            0,
        )
    )
    qv = _filtro_fecha(qv, Venta.fecha, desde, hasta)
    ingresos_ventas = Decimal(str(qv.scalar() or 0))

    # Ingresos puros de movimientos (cobranzas — caja_destino sin origen,
    # excluyendo categorías especiales).
    cats_excluidas = {
        c.tipo_operacion for c in db.query(CategoriaCaja).filter(
            (CategoriaCaja.excluir_flujo == True)  # noqa: E712
            | (CategoriaCaja.es_transferencia == True)  # noqa: E712
            | (CategoriaCaja.es_retiro == True)  # noqa: E712
        ).all()
    }

    qi = db.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)).filter(
        MovimientoCaja.caja_destino.isnot(None),
        MovimientoCaja.caja_origen.is_(None),
    )
    if cats_excluidas:
        qi = qi.filter(~MovimientoCaja.tipo_operacion.in_(cats_excluidas))
    qi = _filtro_fecha(qi, MovimientoCaja.fecha, desde, hasta)
    ingresos_mov = Decimal(str(qi.scalar() or 0))

    # Egresos puros operativos
    qe = db.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)).filter(
        MovimientoCaja.caja_origen.isnot(None),
        MovimientoCaja.caja_destino.is_(None),
    )
    if cats_excluidas:
        qe = qe.filter(~MovimientoCaja.tipo_operacion.in_(cats_excluidas))
    qe = _filtro_fecha(qe, MovimientoCaja.fecha, desde, hasta)
    egresos = Decimal(str(qe.scalar() or 0))

    ingresos_total = ingresos_ventas + ingresos_mov
    margen = ingresos_total - egresos
    pct = float(margen / ingresos_total * 100) if ingresos_total > 0 else None

    return {
        "ingresos_ventas": _to_float(ingresos_ventas),
        "ingresos_movimientos": _to_float(ingresos_mov),
        "ingresos_total": _to_float(ingresos_total),
        "egresos_operativos": _to_float(egresos),
        "margen_operativo": _to_float(margen),
        "margen_operativo_pct": pct,
    }


def margen_operativo_serie(
    db: Session,
    desde: date | None = None,
    hasta: date | None = None,
) -> list[dict[str, Any]]:
    """Serie temporal mensual de margen operativo y % sobre ingresos.

    Útil para ver tendencia: si el margen mensual está mejorando o
    empeorando vs el período anterior. Reusa la lógica de
    `margen_operativo` mes por mes.
    """
    # Determinamos meses del rango. Si no hay desde/hasta, últimos 12.
    if hasta is None:
        hasta = hoy_ar()
    if desde is None:
        anio = hasta.year
        mes = hasta.month - 11
        while mes <= 0:
            anio -= 1
            mes += 12
        desde = date(anio, mes, 1)

    out = []
    cur = date(desde.year, desde.month, 1)
    while cur <= hasta:
        # Fin del mes
        if cur.month == 12:
            fin = date(cur.year + 1, 1, 1)
        else:
            fin = date(cur.year, cur.month + 1, 1)
        from datetime import timedelta as _td
        fin_mes = fin - _td(days=1)
        # Acotar al hasta del rango si aplica
        fin_efectivo = min(fin_mes, hasta)
        m = margen_operativo(db, desde=cur, hasta=fin_efectivo)
        out.append({
            "periodo": f"{cur.year:04d}-{cur.month:02d}",
            "ingresos": m["ingresos_total"],
            "egresos": m["egresos_operativos"],
            "margen": m["margen_operativo"],
            "margen_pct": m["margen_operativo_pct"],
        })
        cur = fin
    return out


def ebitda_aproximado(
    db: Session,
    desde: date | None = None,
    hasta: date | None = None,
) -> dict[str, Any]:
    """EBITDA aproximado = margen operativo + amortizaciones (si están).

    Como el sistema no tiene amortizaciones cargadas explícitamente
    (no hay un activo fijo trackeado), EBITDA ≈ margen operativo. Se
    expone con `nota` para que la dueña sepa la limitación. Si en el
    futuro se carga `amortizacion` como categoría, sumarlas acá.
    """
    base = margen_operativo(db, desde=desde, hasta=hasta)
    # Si hay categoría marcada como amortización (heurística por nombre),
    # sumarla. Por ahora 0.
    amortizacion = Decimal("0")
    return {
        **base,
        "amortizaciones": _to_float(amortizacion),
        "ebitda": base["margen_operativo"] + _to_float(amortizacion),
        "nota": "EBITDA aproximado: sin amortizaciones cargadas, equivale al margen operativo.",
    }


def dpo_promedio(
    db: Session,
    desde: date | None = None,
    hasta: date | None = None,
) -> dict[str, Any]:
    """Days Payable Outstanding: días promedio entre emisión de factura
    y pago efectivo. Solo facturas saldadas dentro del rango.

    Vinculo factura → pagos vía `MovimientoCaja.id_factura_proveedor`.
    Una factura puede recibir múltiples pagos parciales: tomamos la
    fecha del ÚLTIMO pago (cuando quedó saldada) y la suma total
    pagada (debe >= total para considerar saldada).
    """
    # Subquery: por factura, sumar pagos y tomar fecha del ultimo.
    sub = db.query(
        MovimientoCaja.id_factura_proveedor.label("id_factura"),
        func.max(MovimientoCaja.fecha).label("fecha_pago_final"),
        func.sum(MovimientoCaja.monto).label("pagado"),
    ).filter(
        MovimientoCaja.id_factura_proveedor.isnot(None),
        MovimientoCaja.caja_origen.isnot(None),
        MovimientoCaja.caja_destino.is_(None),  # egreso puro, no transfer
        MovimientoCaja.monto > 0,  # excluye notas de crédito / reversiones
    ).group_by(MovimientoCaja.id_factura_proveedor).subquery()

    q = db.query(
        FacturaProveedor.id,
        FacturaProveedor.fecha_emision,
        FacturaProveedor.total,
        sub.c.fecha_pago_final,
        sub.c.pagado,
    ).join(sub, sub.c.id_factura == FacturaProveedor.id).filter(
        FacturaProveedor.anulada == False,  # noqa: E712
    )
    if desde:
        q = q.filter(sub.c.fecha_pago_final >= desde)
    if hasta:
        q = q.filter(sub.c.fecha_pago_final <= hasta)

    dias_total = 0
    facturas_consideradas = 0
    for r in q.all():
        if r.pagado is None or r.fecha_pago_final is None:
            continue
        if Decimal(str(r.pagado)) + Decimal("0.01") < Decimal(str(r.total)):
            continue
        if r.fecha_emision is None:
            continue
        dias = (r.fecha_pago_final - r.fecha_emision).days
        if dias < 0:
            continue
        dias_total += dias
        facturas_consideradas += 1

    promedio = dias_total / facturas_consideradas if facturas_consideradas else None
    return {
        "facturas_consideradas": facturas_consideradas,
        "dias_total": dias_total,
        "dpo_dias": round(promedio, 1) if promedio is not None else None,
    }


def punto_equilibrio(
    db: Session,
    desde: date | None = None,
    hasta: date | None = None,
) -> dict[str, Any]:
    """Punto de equilibrio: ingresos a partir de los cuales el negocio
    cubre todos sus costos.

    PE_ingresos = costos_fijos / margen_contribucion_pct
      donde margen_contribucion_pct = (ingresos - costos_variables) / ingresos

    Costos fijos = egresos con `es_costo_fijo=True` (sueldos, alquiler,
    servicios) + categorías sin clasificar fijo/variable se asumen
    variables por default.

    Devuelve también `cobertura_pct` = ingresos_actuales / PE_ingresos × 100
    (>100% = el negocio está rentable, <100% = bajo PE).
    """
    cats_excluidas = {
        c.tipo_operacion for c in db.query(CategoriaCaja).filter(
            (CategoriaCaja.excluir_flujo == True)  # noqa: E712
            | (CategoriaCaja.es_transferencia == True)  # noqa: E712
            | (CategoriaCaja.es_retiro == True)  # noqa: E712
        ).all()
    }
    cats_fijas = {
        c.tipo_operacion for c in db.query(CategoriaCaja).filter(
            CategoriaCaja.es_costo_fijo == True,  # noqa: E712
        ).all()
    }

    # Ingresos
    qv = db.query(
        func.coalesce(
            func.sum(func.coalesce(Venta.monto_pago1, 0) + func.coalesce(Venta.monto_pago2, 0)),
            0,
        )
    )
    qv = _filtro_fecha(qv, Venta.fecha, desde, hasta)
    ingresos = Decimal(str(qv.scalar() or 0))

    # Egresos operativos totales (excluyendo categorías especiales).
    # Siempre los computamos, así el caller distingue "sin config de
    # fijos" (nota presente) vs "ingresos=0" vs "negocio en rojo".
    egresos_q = db.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)).filter(
        MovimientoCaja.caja_origen.isnot(None),
        MovimientoCaja.caja_destino.is_(None),
    )
    if cats_excluidas:
        egresos_q = egresos_q.filter(~MovimientoCaja.tipo_operacion.in_(cats_excluidas))
    egresos_q = _filtro_fecha(egresos_q, MovimientoCaja.fecha, desde, hasta)
    egresos_total = Decimal(str(egresos_q.scalar() or 0))

    # Costos fijos: subset que matcha cats_fijas. Si no hay cats_fijas,
    # costos_fijos=0 y la nota del response avisa que falta config.
    if cats_fijas:
        qf = db.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)).filter(
            MovimientoCaja.caja_origen.isnot(None),
            MovimientoCaja.caja_destino.is_(None),
            MovimientoCaja.tipo_operacion.in_(cats_fijas),
        )
        qf = _filtro_fecha(qf, MovimientoCaja.fecha, desde, hasta)
        costos_fijos = Decimal(str(qf.scalar() or 0))
    else:
        costos_fijos = Decimal(0)

    costos_variables = egresos_total - costos_fijos

    # Computar PE solo si hay configuración suficiente.
    nota = None
    margen_pct = None
    pe = None
    cobertura = None
    if not cats_fijas:
        nota = "Marcá al menos una categoría como `es_costo_fijo` en /config para computar punto de equilibrio."
    elif ingresos == 0:
        nota = "Sin ingresos en el período — no se puede computar PE."
    else:
        margen_contrib = ingresos - costos_variables
        margen_pct = float(margen_contrib / ingresos * 100)
        if margen_contrib <= 0:
            nota = (
                "Margen de contribución <= 0: los costos variables superan "
                "los ingresos. Punto de equilibrio inalcanzable con la "
                "estructura actual de costos."
            )
        else:
            pe = float(costos_fijos / (margen_contrib / ingresos))
            cobertura = float(ingresos / Decimal(str(pe)) * 100) if pe > 0 else None

    return {
        "costos_fijos": _to_float(costos_fijos),
        "costos_variables": _to_float(costos_variables),
        "ingresos": _to_float(ingresos),
        "margen_contribucion_pct": margen_pct,
        "punto_equilibrio_ingresos": pe,
        "cobertura_pct": cobertura,
        "nota": nota,
    }


def crecimiento_sostenido(db: Session, meses: int = 12) -> dict[str, Any]:
    """Tasa de crecimiento mensual de ingresos sobre los últimos N meses.

    Devuelve mediana + promedio + anualización compuesta sobre la
    mediana. La MEDIANA es la métrica principal porque es robusta a
    outliers (mes navideño 5x normal, una venta puntual gigante, etc.).
    El promedio simple sobre 12 deltas se distorsiona fuerte con un
    solo pico — engaña al "ritmo sostenible" que el indicador busca.
    """
    # Computar serie con el rango pedido. `margen_operativo_serie` por
    # default da 12 meses; para más, calculamos `desde` retrocediendo N-1
    # meses desde el primer día del mes actual. Cálculo correcto evita
    # off-by-one con floor div sobre meses negativos:
    #   mes_idx_total = año*12 + mes (1-12), retroceder = restar (N-1).
    hoy = hoy_ar()
    primer_dia_mes_actual = date(hoy.year, hoy.month, 1)
    idx_total = hoy.year * 12 + (hoy.month - 1) - (meses - 1)
    anio_desde = idx_total // 12
    mes_desde = (idx_total % 12) + 1
    desde = date(anio_desde, mes_desde, 1)
    serie = margen_operativo_serie(db, desde=desde, hasta=hoy)
    # Defensa: si por alguna razón vienen más puntos, recortar a N.
    serie = serie[-meses:] if len(serie) > meses else serie
    if len(serie) < 2:
        return {
            "tasa_mensual_pct": None,
            "tasa_mensual_promedio_pct": None,
            "tasa_anualizada_pct": None,
            "periodos_analizados": len(serie),
            "nota": "Necesita al menos 2 meses de historia para calcular crecimiento.",
        }
    deltas = []
    for i in range(1, len(serie)):
        prev = serie[i - 1]["ingresos"]
        curr = serie[i]["ingresos"]
        if prev > 0:
            deltas.append((curr - prev) / prev * 100)
    if not deltas:
        return {
            "tasa_mensual_pct": None,
            "tasa_mensual_promedio_pct": None,
            "tasa_anualizada_pct": None,
            "periodos_analizados": len(serie),
            "nota": "Sin períodos previos con ingresos > 0.",
        }
    deltas_ord = sorted(deltas)
    n = len(deltas_ord)
    # Mediana (robusta a outliers — métrica principal).
    if n % 2 == 1:
        tasa_mediana = deltas_ord[n // 2]
    else:
        tasa_mediana = (deltas_ord[n // 2 - 1] + deltas_ord[n // 2]) / 2
    # Promedio simple (informativo, sensible a outliers).
    tasa_promedio = sum(deltas) / n
    # Anualizada compuesta sobre la mediana.
    try:
        tasa_anual = ((1 + tasa_mediana / 100) ** 12 - 1) * 100
    except OverflowError:
        tasa_anual = None
    return {
        "tasa_mensual_pct": round(tasa_mediana, 2),  # principal: mediana
        "tasa_mensual_promedio_pct": round(tasa_promedio, 2),  # comparativa
        "tasa_anualizada_pct": round(tasa_anual, 2) if tasa_anual is not None else None,
        "periodos_analizados": len(serie),
        "serie": serie,
    }


def _umbrales_dependencia() -> dict[str, float]:
    """Umbrales de concentración top1 proveedor — delega al helper
    central de `core.config` para evitar drift."""
    from app.core.config import umbrales_concentracion_proveedores
    return umbrales_concentracion_proveedores()


def dependencia_proveedores(
    db: Session,
    desde: date | None = None,
    hasta: date | None = None,
    top: int = 10,
) -> dict[str, Any]:
    """% de compras totales por proveedor en el período. Útil para
    detectar concentración riesgosa en pocos proveedores."""
    q = db.query(
        FacturaProveedor.id_proveedor,
        Proveedor.nombre,
        func.coalesce(func.sum(FacturaProveedor.total), 0).label("monto"),
        func.count(FacturaProveedor.id).label("facturas"),
    ).join(Proveedor, Proveedor.id == FacturaProveedor.id_proveedor).filter(
        FacturaProveedor.anulada == False,  # noqa: E712
    )
    q = _filtro_fecha(q, FacturaProveedor.fecha_emision, desde, hasta)
    q = q.group_by(FacturaProveedor.id_proveedor, Proveedor.nombre)
    rows = q.all()
    total = sum(Decimal(str(r.monto or 0)) for r in rows)
    rows_d = []
    for r in rows:
        m = Decimal(str(r.monto or 0))
        rows_d.append({
            "id_proveedor": r.id_proveedor,
            "nombre": r.nombre,
            "monto": _to_float(m),
            "facturas": r.facturas,
            "pct": float(m / total * 100) if total > 0 else 0.0,
        })
    rows_d.sort(key=lambda r: r["monto"], reverse=True)

    top_n = rows_d[:top]
    pct_top = sum(r["pct"] for r in top_n)
    pct_top1 = top_n[0]["pct"] if top_n else 0.0
    pct_top3 = sum(r["pct"] for r in top_n[:3])
    return {
        "total_compras": _to_float(total),
        "cantidad_proveedores": len(rows_d),
        "concentracion": {
            "top_1_pct": round(pct_top1, 2),
            "top_3_pct": round(pct_top3, 2),
            "top_n_pct": round(pct_top, 2),
            "n": len(top_n),
        },
        "umbrales": _umbrales_dependencia(),
        "top": top_n,
    }
