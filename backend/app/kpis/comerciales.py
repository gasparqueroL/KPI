"""KPIs comerciales: ventas, margen, clientes, productos, vendedores."""

import os
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import case, distinct, func
from sqlalchemy.orm import Session


def _umbrales_concentracion() -> dict[str, float]:
    """Single source of truth — delega al helper central de
    `core.config` para evitar drift entre módulos."""
    from app.core.config import umbrales_concentracion_clientes
    return umbrales_concentracion_clientes()

from app.kpis._fechas import filtro_fecha as _filtro_fecha, hasta_fin_dia as _hasta_fin_dia, hoy_ar
from app.models.venta import DetalleVenta, Venta

CATEGORIAS_MARGEN = ["mercaderia", "bonificacion"]


def _to_float(v) -> float:
    return float(v) if v is not None else 0.0


def _filtro_vendedor(query, vendedor):
    if vendedor:
        return query.filter(Venta.vendedor == vendedor)
    return query


def resumen(
    db: Session,
    desde: date | None = None,
    hasta: date | None = None,
    vendedor: str | None = None,
) -> dict[str, Any]:
    """KPIs principales del bloque comercial."""

    q = db.query(
        func.count(Venta.id_pedido).label("pedidos"),
        func.coalesce(func.sum(Venta.total), 0).label("ventas"),
        func.count(distinct(Venta.id_cliente)).label("clientes"),
        func.sum(case((Venta.es_cuenta_corriente == True, 1), else_=0)).label("cta_cte"),
        func.sum(case((Venta.discrepancia_pago == True, 1), else_=0)).label("discrepancia"),
    )
    q = _filtro_fecha(q, Venta.fecha, desde, hasta)
    q = _filtro_vendedor(q, vendedor)
    row = q.one()

    pedidos = row.pedidos or 0
    ventas = Decimal(str(row.ventas or 0))
    clientes = row.clientes or 0
    ticket = ventas / pedidos if pedidos else Decimal(0)

    margen_q = db.query(
        func.coalesce(func.sum(DetalleVenta.subtotal), 0).label("ing"),
        func.coalesce(func.sum(DetalleVenta.cst), 0).label("cst"),
    ).filter(DetalleVenta.categoria_linea.in_(CATEGORIAS_MARGEN))
    margen_q = _filtro_fecha(margen_q, DetalleVenta.fecha, desde, hasta)
    if vendedor:
        margen_q = margen_q.join(Venta, Venta.id_venta == DetalleVenta.id_venta).filter(
            Venta.vendedor == vendedor
        )
    mrow = margen_q.one()
    ing_merc = Decimal(str(mrow.ing or 0))
    cst_total = Decimal(str(mrow.cst or 0))
    margen = ing_merc - cst_total
    margen_pct = (margen / ing_merc * 100) if ing_merc else Decimal(0)

    # "clientes_nuevos" = clientes cuya PRIMERA venta cae dentro del período.
    # Si hay filtro de vendedor, "primera venta" se calcula sobre las ventas de
    # ese vendedor (clientes nuevos PARA ese vendedor), no para la empresa.
    primer_pedido_q = db.query(
        Venta.id_cliente,
        func.min(Venta.fecha).label("primera"),
    ).filter(Venta.id_cliente.isnot(None))
    primer_pedido_q = _filtro_vendedor(primer_pedido_q, vendedor)
    primer_pedido = primer_pedido_q.group_by(Venta.id_cliente).subquery()

    nq = db.query(func.count()).select_from(primer_pedido)
    if desde:
        nq = nq.filter(primer_pedido.c.primera >= desde)
    h = _hasta_fin_dia(hasta)
    if h:
        nq = nq.filter(primer_pedido.c.primera <= h)
    nuevos = nq.scalar() or 0

    return {
        "desde": desde.isoformat() if desde else None,
        "hasta": hasta.isoformat() if hasta else None,
        "pedidos": pedidos,
        "ventas_totales": _to_float(ventas),
        "clientes_unicos": clientes,
        "clientes_nuevos": nuevos,
        "ticket_promedio": _to_float(ticket),
        "ingresos_mercaderia": _to_float(ing_merc),
        "costo_mercaderia": _to_float(cst_total),
        "margen_bruto": _to_float(margen),
        "margen_pct": _to_float(margen_pct),
        "ventas_cuenta_corriente": row.cta_cte or 0,
        "ventas_con_discrepancia": row.discrepancia or 0,
    }


_PERIODOS_FMT = {
    "dia": "%Y-%m-%d",
    # SQLite `%W` = semana del año con LUNES como primer día (00-53), NO
    # ISO 8601. La primera semana del año puede aparecer como `YYYY-W00`
    # cuando enero no contiene lunes todavía. Para una PyME es aceptable
    # (consistente y sortable). Si en el futuro se necesita ISO real,
    # habría que post-procesar en Python o usar julianday.
    "semana": "%Y-W%W",
    "mes": "%Y-%m",
    "anio": "%Y",
}


def serie_temporal(
    db: Session,
    periodo: str = "mes",
    desde: date | None = None,
    hasta: date | None = None,
    vendedor: str | None = None,
) -> list[dict[str, Any]]:
    fmt = _PERIODOS_FMT.get(periodo)
    if fmt is None:
        raise ValueError(f"Periodo inválido: {periodo}. Válidos: {list(_PERIODOS_FMT)}")

    bucket = func.strftime(fmt, Venta.fecha).label("periodo")
    q = db.query(
        bucket,
        func.count(Venta.id_pedido).label("pedidos"),
        func.coalesce(func.sum(Venta.total), 0).label("ventas"),
        func.count(distinct(Venta.id_cliente)).label("clientes"),
    )
    q = _filtro_fecha(q, Venta.fecha, desde, hasta)
    q = _filtro_vendedor(q, vendedor)
    q = q.group_by(bucket).order_by(bucket)

    return [
        {
            "periodo": r.periodo,
            "pedidos": r.pedidos,
            "ventas": _to_float(r.ventas),
            "clientes": r.clientes,
            "ticket_promedio": _to_float(Decimal(str(r.ventas or 0)) / r.pedidos)
                if r.pedidos else 0.0,
        }
        for r in q.all()
    ]


def top_productos(
    db: Session,
    por: str = "margen",
    desde: date | None = None,
    hasta: date | None = None,
    limite: int = 10,
    vendedor: str | None = None,
) -> list[dict[str, Any]]:
    if por not in ("margen", "ingresos", "cantidad"):
        raise ValueError(f"'por' inválido: {por}. Válidos: margen, ingresos, cantidad")

    margen_expr = func.sum(DetalleVenta.subtotal - DetalleVenta.cst)
    ingresos_expr = func.sum(DetalleVenta.subtotal)
    cantidad_expr = func.sum(DetalleVenta.cantidad)
    costo_expr = func.sum(DetalleVenta.cst)

    q = db.query(
        DetalleVenta.producto,
        ingresos_expr.label("ingresos"),
        costo_expr.label("costo"),
        margen_expr.label("margen"),
        cantidad_expr.label("cantidad"),
        func.count(distinct(DetalleVenta.id_venta)).label("ventas"),
    ).filter(DetalleVenta.categoria_linea == "mercaderia",
             DetalleVenta.cst.isnot(None))
    q = _filtro_fecha(q, DetalleVenta.fecha, desde, hasta)
    if vendedor:
        q = q.join(Venta, Venta.id_venta == DetalleVenta.id_venta).filter(
            Venta.vendedor == vendedor
        )
    q = q.group_by(DetalleVenta.producto)

    orden = {"margen": margen_expr, "ingresos": ingresos_expr, "cantidad": cantidad_expr}[por]
    q = q.order_by(orden.desc()).limit(limite)

    out = []
    for r in q.all():
        ing = Decimal(str(r.ingresos or 0))
        mar = Decimal(str(r.margen or 0))
        out.append({
            "producto": r.producto,
            "ingresos": _to_float(ing),
            "costo": _to_float(r.costo),
            "margen": _to_float(mar),
            "margen_pct": _to_float((mar / ing * 100) if ing else 0),
            "cantidad": _to_float(r.cantidad),
            "ventas": r.ventas,
        })
    return out


def top_clientes(
    db: Session,
    desde: date | None = None,
    hasta: date | None = None,
    limite: int = 10,
    vendedor: str | None = None,
) -> list[dict[str, Any]]:
    q = db.query(
        Venta.id_cliente,
        Venta.cliente,
        func.count(Venta.id_pedido).label("pedidos"),
        func.coalesce(func.sum(Venta.total), 0).label("ventas"),
    ).filter(Venta.id_cliente.isnot(None))
    q = _filtro_fecha(q, Venta.fecha, desde, hasta)
    q = _filtro_vendedor(q, vendedor)
    q = q.group_by(Venta.id_cliente, Venta.cliente)
    q = q.order_by(func.sum(Venta.total).desc()).limit(limite)

    out = []
    for r in q.all():
        ventas = Decimal(str(r.ventas or 0))
        out.append({
            "id_cliente": r.id_cliente,
            "cliente": r.cliente,
            "pedidos": r.pedidos,
            "ventas": _to_float(ventas),
            "ticket_promedio": _to_float(ventas / r.pedidos) if r.pedidos else 0.0,
        })
    return out


def clientes_de_producto(
    db: Session,
    producto: str,
    desde: date | None = None,
    hasta: date | None = None,
    limite: int = 50,
) -> list[dict[str, Any]]:
    """Lista los clientes que compraron `producto`, ordenados por monto.

    Drill-down del top productos: la dueña ve el producto con mejor margen
    y quiere saber a quién se lo está vendiendo (concentrar atención
    comercial, evaluar pricing, detectar caída de un cliente clave).

    Devuelve por cliente: cantidad total, monto total, pedidos, última fecha.
    """
    q = db.query(
        Venta.id_cliente,
        func.max(Venta.cliente).label("cliente"),
        func.sum(DetalleVenta.cantidad).label("cantidad_total"),
        func.sum(DetalleVenta.subtotal).label("monto_total"),
        # Consistente con el join key (id_venta). En Venta tanto id_pedido
        # como id_venta son únicos por fila, así que dan el mismo número,
        # pero `id_venta` no depende de la garantía de PK de id_pedido.
        func.count(func.distinct(Venta.id_venta)).label("pedidos"),
        func.max(Venta.fecha).label("ultima_compra"),
    ).join(DetalleVenta, DetalleVenta.id_venta == Venta.id_venta).filter(
        DetalleVenta.producto == producto,
        Venta.id_cliente.isnot(None),
    )
    q = _filtro_fecha(q, Venta.fecha, desde, hasta)
    q = q.group_by(Venta.id_cliente)
    q = q.order_by(func.sum(DetalleVenta.subtotal).desc()).limit(limite)

    out = []
    for r in q.all():
        ult = r.ultima_compra
        out.append({
            "id_cliente": r.id_cliente,
            "cliente": r.cliente,
            "cantidad_total": _to_float(r.cantidad_total or 0),
            "monto_total": _to_float(r.monto_total or 0),
            "pedidos": r.pedidos,
            "ultima_compra": ult.isoformat() if ult else None,
        })
    return out


def clientes_perdidos(
    db: Session,
    dias_inactividad: int = 90,
    ventana_historica_dias: int = 365,
    pedidos_minimos: int = 3,
) -> list[dict[str, Any]]:
    """Clientes "perdidos": antes compraban, ahora hace mucho que no.

    Definición operativa para una PyME:
    - En los últimos `ventana_historica_dias` (default 365) tuvieron al
      menos `pedidos_minimos` (default 3) pedidos → fueron clientes reales,
      no compras puntuales de pasada.
    - En los últimos `dias_inactividad` (default 90) no hicieron NINGÚN
      pedido → probable baja, vale alertar a comercial para recontacto.

    Devuelve por cliente: pedidos en ventana, monto total, última compra,
    días desde la última. Ordenado por monto desc — los más impactantes
    primero. Excluye `id_cliente IS NULL` (mostrador no es atribuible)."""
    hoy = hoy_ar()
    fecha_corte_inactividad = hoy - timedelta(days=dias_inactividad)
    fecha_corte_historica = hoy - timedelta(days=ventana_historica_dias)

    # Subquery: clientes activos (con pedido en los últimos `dias_inactividad`).
    # Usamos .scalar_subquery() porque .subquery() emite warning en notin_.
    activos_recientes = db.query(Venta.id_cliente).filter(
        Venta.id_cliente.isnot(None),
        Venta.fecha >= fecha_corte_inactividad,
    ).distinct()

    # Query principal: clientes con N+ pedidos en ventana histórica que NO
    # están en `activos_recientes`. El subquery con NOT IN escala bien para
    # 250 ventas; con 50k+ podría ser un LEFT JOIN + IS NULL.
    rows = (
        db.query(
            Venta.id_cliente,
            func.max(Venta.cliente).label("cliente"),
            func.count(Venta.id_pedido).label("pedidos"),
            func.coalesce(func.sum(Venta.total), 0).label("monto_total"),
            func.max(Venta.fecha).label("ultima_compra"),
        )
        .filter(
            Venta.id_cliente.isnot(None),
            Venta.fecha >= fecha_corte_historica,
            Venta.id_cliente.notin_(activos_recientes),
        )
        .group_by(Venta.id_cliente)
        .having(func.count(Venta.id_pedido) >= pedidos_minimos)
        .order_by(func.coalesce(func.sum(Venta.total), 0).desc())
        .all()
    )

    out = []
    for r in rows:
        ult = r.ultima_compra
        ult_date = ult.date() if hasattr(ult, "date") else ult
        out.append({
            "id_cliente": r.id_cliente,
            "cliente": r.cliente,
            "pedidos_en_ventana": r.pedidos,
            "monto_total": _to_float(r.monto_total or 0),
            "ultima_compra": ult.isoformat() if ult else None,
            "dias_sin_comprar": (hoy - ult_date).days if ult_date else None,
        })
    return out


def analisis_abc_productos(
    db: Session,
    desde: date | None = None,
    hasta: date | None = None,
    umbral_a_pct: float = 80.0,
    umbral_b_pct: float = 95.0,
) -> dict[str, Any]:
    """Clasificación ABC (Pareto) de productos por margen acumulado.

    - **A**: productos que generan hasta `umbral_a_pct` (80%) del margen total.
      Foco comercial — el 20% que mueve la aguja.
    - **B**: entre A y `umbral_b_pct` (95%). Importantes pero secundarios.
    - **C**: el resto (cola larga, 5%).

    Devuelve `{totales, productos: [{producto, margen, margen_pct,
    margen_acumulado_pct, categoria_abc, ...}]}` ordenado por margen desc.
    Solo considera líneas de mercadería con CST cargado (consistente con
    `top_productos`)."""
    rows = (
        db.query(
            DetalleVenta.producto,
            func.sum(DetalleVenta.subtotal).label("ingresos"),
            func.sum(DetalleVenta.cst).label("costo"),
            func.sum(DetalleVenta.subtotal - DetalleVenta.cst).label("margen"),
            func.count(distinct(DetalleVenta.id_venta)).label("ventas"),
        )
        .filter(
            DetalleVenta.categoria_linea == "mercaderia",
            DetalleVenta.cst.isnot(None),
        )
    )
    rows = _filtro_fecha(rows, DetalleVenta.fecha, desde, hasta)
    rows = (
        rows.group_by(DetalleVenta.producto)
        # Tiebreaker `producto.asc()`: dos productos con margen idéntico
        # podían flipar A/B entre runs porque el acumulado depende del orden.
        # Con tiebreaker estable, la clasificación es reproducible.
        .order_by(
            func.sum(DetalleVenta.subtotal - DetalleVenta.cst).desc(),
            DetalleVenta.producto.asc(),
        )
        .all()
    )

    if not rows:
        return {
            "totales": {"productos": 0, "margen_total": 0.0, "a": 0, "b": 0, "c": 0},
            "productos": [],
        }

    margen_total = sum(_to_float(r.margen or 0) for r in rows)
    # Si el margen total es ≤ 0 (productos a costo o sin CST cargado), la
    # clasificación ABC no tiene sentido matemático: no hay 80% que repartir.
    # Devolvemos productos sin clasificar (categoria_abc = None) en lugar de
    # mentir con un Pareto inexistente. El front decide cómo mostrarlo.
    if margen_total <= 0:
        productos = [
            {
                "producto": r.producto,
                "ingresos": _to_float(r.ingresos or 0),
                "costo": _to_float(r.costo or 0),
                "margen": _to_float(r.margen or 0),
                "ventas": r.ventas,
                "margen_pct": 0.0,
                "margen_acumulado_pct": 0.0,
                "categoria_abc": None,
            }
            for r in rows
        ]
        return {
            "totales": {
                "productos": len(productos),
                "margen_total": round(margen_total, 2),
                "a": 0, "b": 0, "c": 0,
            },
            "productos": productos,
        }

    productos = []
    acum = 0.0
    for i, r in enumerate(rows):
        margen_v = _to_float(r.margen or 0)
        margen_pct = margen_v / margen_total * 100
        acum += margen_pct
        # Garantía: el primer producto siempre es A (incluso si por sí solo
        # supera 80%). Sin esto, un catálogo con 1 producto único cae en C
        # — absurdo: ese producto ES el negocio.
        if i == 0:
            cat = "A"
        elif acum <= umbral_a_pct:
            cat = "A"
        elif acum <= umbral_b_pct:
            cat = "B"
        else:
            cat = "C"
        productos.append({
            "producto": r.producto,
            "ingresos": _to_float(r.ingresos or 0),
            "costo": _to_float(r.costo or 0),
            "margen": margen_v,
            "ventas": r.ventas,
            "margen_pct": round(margen_pct, 2),
            "margen_acumulado_pct": round(acum, 2),
            "categoria_abc": cat,
        })

    return {
        "totales": {
            "productos": len(productos),
            "margen_total": round(margen_total, 2),
            "a": sum(1 for p in productos if p["categoria_abc"] == "A"),
            "b": sum(1 for p in productos if p["categoria_abc"] == "B"),
            "c": sum(1 for p in productos if p["categoria_abc"] == "C"),
        },
        "productos": productos,
    }


def proyeccion_mes_actual(db: Session) -> dict[str, Any]:
    """Proyección lineal de ventas del mes en curso.

    Pensado para que la dueña vea "vamos por X y proyectamos cerrar en Y"
    a mitad del mes y decida si empuja comercialmente.

    Algoritmo simple y honesto:
    - Ventas reales del mes a hoy.
    - Tasa observada = ventas_actuales / días_transcurridos.
    - Proyección = tasa × días_totales_del_mes (extrapolación lineal).
    - Comparativa: mismo mes del año anterior (si hay datos).

    Limitación documentada: no modela estacionalidad intra-mes (la dueña
    sabe si la última semana suele ser fuerte o floja). Es proyección
    base-line, no predicción afinada.

    Devuelve `None` para `proyectado` si el mes recién empezó (1-2 días)
    o si ya terminó (sería extrapolar 0)."""
    import calendar as _cal
    hoy = hoy_ar()
    primer_dia = hoy.replace(day=1)
    dias_total_mes = _cal.monthrange(hoy.year, hoy.month)[1]
    dias_transcurridos = hoy.day  # incluye hoy

    # Ventas del mes en curso
    res_actual = resumen(db, desde=primer_dia, hasta=hoy)

    # Mismo mes año anterior (completo)
    primer_anio_pasado = primer_dia.replace(year=primer_dia.year - 1)
    ult_anio_pasado = primer_anio_pasado.replace(
        day=_cal.monthrange(primer_anio_pasado.year, primer_anio_pasado.month)[1]
    )
    res_anterior = resumen(db, desde=primer_anio_pasado, hasta=ult_anio_pasado)

    # Proyección: extrapolación lineal con días observados.
    # Saltamos cuando hay muy pocos datos (1-2 días) — proyectar con esa
    # base es ruido, no señal. El último día del mes (`<= dias_total_mes`)
    # SÍ entra: la "proyección" termina siendo igual a las ventas reales
    # (matemáticamente sano, evita que el día 31 muestre `null` justo
    # cuando es el dato más completo).
    proyectado = None
    delta_pct_vs_anio_anterior = None
    if dias_transcurridos >= 3 and dias_transcurridos <= dias_total_mes:
        ventas_actuales = res_actual["ventas_totales"] or 0
        tasa_diaria = ventas_actuales / dias_transcurridos
        proyectado = round(tasa_diaria * dias_total_mes, 2)
        if res_anterior["ventas_totales"]:
            delta_pct_vs_anio_anterior = round(
                (proyectado - res_anterior["ventas_totales"])
                / res_anterior["ventas_totales"] * 100,
                1,
            )

    return {
        "mes": primer_dia.isoformat()[:7],  # "2026-05"
        "dias_transcurridos": dias_transcurridos,
        "dias_totales": dias_total_mes,
        "ventas_a_la_fecha": res_actual["ventas_totales"],
        "pedidos_a_la_fecha": res_actual["pedidos"],
        "proyectado_cierre": proyectado,
        "anio_anterior_mismo_mes": res_anterior["ventas_totales"] or 0,
        "delta_pct_vs_anio_anterior": delta_pct_vs_anio_anterior,
    }


def productos_sin_venta_reciente(
    db: Session,
    dias_inactividad: int = 60,
    ventana_historica_dias: int = 365,
    ventas_minimas: int = 5,
) -> list[dict[str, Any]]:
    """Productos "dormidos": tenían rotación y se enfriaron.

    Definición:
    - En `ventana_historica_dias` (default 365) tuvieron `>= ventas_minimas`
      apariciones en pedidos (productos con demanda real, no venta puntual).
    - En `dias_inactividad` (default 60) tuvieron 0 ventas → señal de que
      el inventario potencialmente se está acumulando.

    Útil para que la dueña revise stock e identifique candidatos a:
    descuento, descontinuación, o re-promoción comercial.

    Devuelve: producto, ventas_en_ventana, monto_total, última_venta,
    días_sin_vender. Orden: monto desc (mayor inventario impactado primero).
    Excluye productos con `producto IS NULL` o vacío."""
    hoy = hoy_ar()
    fecha_corte_inactividad = hoy - timedelta(days=dias_inactividad)
    fecha_corte_historica = hoy - timedelta(days=ventana_historica_dias)

    # Subquery: productos con venta reciente (sin importar cuánta).
    activos_recientes = db.query(DetalleVenta.producto).filter(
        DetalleVenta.producto.isnot(None),
        DetalleVenta.fecha >= fecha_corte_inactividad,
    ).distinct()

    # Contamos pedidos distintos (id_venta), no líneas: si una factura tiene
    # el producto repetido en 5 líneas (re-cargado, splits) NO debe pasar
    # el umbral con un solo pedido. Mismo criterio que `clientes_de_producto`
    # y `top_productos`.
    rows = (
        db.query(
            DetalleVenta.producto,
            func.count(func.distinct(DetalleVenta.id_venta)).label("ventas"),
            func.coalesce(func.sum(DetalleVenta.subtotal), 0).label("monto_total"),
            func.max(DetalleVenta.fecha).label("ultima_venta"),
        )
        .filter(
            DetalleVenta.producto.isnot(None),
            func.trim(DetalleVenta.producto) != "",
            DetalleVenta.fecha >= fecha_corte_historica,
            DetalleVenta.producto.notin_(activos_recientes),
        )
        .group_by(DetalleVenta.producto)
        .having(func.count(func.distinct(DetalleVenta.id_venta)) >= ventas_minimas)
        .order_by(func.coalesce(func.sum(DetalleVenta.subtotal), 0).desc())
        .all()
    )

    out = []
    for r in rows:
        ult = r.ultima_venta
        ult_date = ult.date() if hasattr(ult, "date") else ult
        out.append({
            "producto": r.producto,
            "ventas_en_ventana": r.ventas,
            "monto_total": _to_float(r.monto_total or 0),
            "ultima_venta": ult.isoformat() if ult else None,
            "dias_sin_vender": (hoy - ult_date).days if ult_date else None,
        })
    return out


def concentracion_clientes(
    db: Session,
    desde: date | None = None,
    hasta: date | None = None,
) -> dict[str, Any]:
    """Mide concentración de ventas en pocos clientes (riesgo comercial).

    Devuelve % que representa el top 1 / 3 / 5 / 10 sobre el total del
    período, más la lista del top 10 y los umbrales que usan las alertas.
    Si una PyME factura 80% a 1 solo cliente, perderlo significa cierre
    técnico — vale alertarlo.

    Período default: lo que pase el caller (desde/hasta). Las alertas
    automáticas usan ventana 90d. Excluye ventas sin id_cliente
    (genéricas, mostrador) — no son atribuibles a una cuenta.

    `umbrales` viene del mismo lugar (env vars) que la regla de alerta
    en `kpis/alertas.py`, para que el frontend pueda colorear las KPI
    cards con los mismos cortes que disparan la alerta. Sin esto el
    frontend hardcodea umbrales y desincroniza si alguien cambia las env."""
    # Group by SOLO id_cliente con MAX(cliente) — si el mismo id aparece
    # con typos distintos en `cliente` (renombrado, espacios extra), no
    # queremos que se separen en filas distintas y subestimar el top 1.
    # Mismo patrón que `clientes_con_cuenta` en cuentas_corrientes.py.
    q = db.query(
        Venta.id_cliente,
        func.max(Venta.cliente).label("cliente"),
        func.coalesce(func.sum(Venta.total), 0).label("ventas"),
    ).filter(Venta.id_cliente.isnot(None))
    q = _filtro_fecha(q, Venta.fecha, desde, hasta)
    q = q.group_by(Venta.id_cliente)
    q = q.order_by(func.sum(Venta.total).desc())

    rows = q.all()
    if not rows:
        return {
            "total_periodo": 0.0,
            "cantidad_clientes": 0,
            "top_1_pct": 0.0,
            "top_3_pct": 0.0,
            "top_5_pct": 0.0,
            "top_10_pct": 0.0,
            "top_clientes": [],
            "umbrales": _umbrales_concentracion(),
        }

    ventas = [Decimal(str(r.ventas or 0)) for r in rows]
    total = sum(ventas, Decimal(0))

    def _acum_pct(n: int) -> float:
        if total == 0:
            return 0.0
        acum = sum(ventas[:n], Decimal(0))
        return _to_float(acum / total * 100)

    top10 = []
    for r, v in zip(rows[:10], ventas[:10]):
        top10.append({
            "id_cliente": r.id_cliente,
            "cliente": r.cliente,
            "ventas": _to_float(v),
            "pct": _to_float(v / total * 100) if total > 0 else 0.0,
        })

    return {
        "total_periodo": _to_float(total),
        "cantidad_clientes": len(rows),
        "top_1_pct": _acum_pct(1),
        "top_3_pct": _acum_pct(3),
        "top_5_pct": _acum_pct(5),
        "top_10_pct": _acum_pct(10),
        "top_clientes": top10,
        "umbrales": _umbrales_concentracion(),
    }


def top_vendedores(
    db: Session,
    desde: date | None = None,
    hasta: date | None = None,
    limite: int = 10,
) -> list[dict[str, Any]]:
    """Top N vendedores por ventas. Devuelve estructura por vendedor con
    pedidos, ventas, clientes únicos (distinct id_cliente — la convención
    es por ID, no por nombre: data sucia con duplicados de ID es
    responsabilidad del import), ticket_promedio, margen agregado.

    Margen excluye ventas con `vendedor IS NULL` (no atribuibles), líneas
    no-mercadería (servicios, descuentos), y líneas sin cst.
    """
    sub_margen = db.query(
        Venta.vendedor.label("vendedor"),
        func.sum(DetalleVenta.subtotal - DetalleVenta.cst).label("margen"),
    ).join(
        DetalleVenta, DetalleVenta.id_venta == Venta.id_venta
    ).filter(
        DetalleVenta.categoria_linea == "mercaderia",
        DetalleVenta.cst.isnot(None),
        Venta.vendedor.isnot(None),
    )
    sub_margen = _filtro_fecha(sub_margen, Venta.fecha, desde, hasta)
    sub_margen = sub_margen.group_by(Venta.vendedor).subquery()

    ventas_expr = func.coalesce(func.sum(Venta.total), 0)
    q = db.query(
        Venta.vendedor,
        func.count(Venta.id_pedido).label("pedidos"),
        ventas_expr.label("ventas"),
        func.count(distinct(Venta.id_cliente)).label("clientes"),
    ).filter(Venta.vendedor.isnot(None))
    q = _filtro_fecha(q, Venta.fecha, desde, hasta)
    q = q.group_by(Venta.vendedor)
    # Tiebreaker alfabético — sin esto, dos vendedores con ventas iguales
    # quedan en orden no determinístico (Ana arriba un día, Beto otro).
    # Mismo fix simétrico al de `productos_a_perdida` (línea 875).
    q = q.order_by(ventas_expr.desc(), Venta.vendedor.asc())

    margenes = {r.vendedor: r.margen for r in db.query(sub_margen).all()}

    rows = q.limit(limite).all()

    return [
        {
            "vendedor": r.vendedor,
            "pedidos": r.pedidos,
            "ventas": _to_float(r.ventas),
            "clientes": r.clientes,
            "ticket_promedio": _to_float(Decimal(str(r.ventas or 0)) / r.pedidos)
                if r.pedidos else 0.0,
            "margen": _to_float(margenes.get(r.vendedor, 0)),
        }
        for r in rows
    ]


def recompra(db: Session, desde: date | None = None, hasta: date | None = None) -> dict[str, Any]:
    """Tasa de recompra: % de clientes con 2+ pedidos en el período."""
    q = db.query(
        Venta.id_cliente,
        func.count(Venta.id_pedido).label("pedidos"),
    ).filter(Venta.id_cliente.isnot(None))
    q = _filtro_fecha(q, Venta.fecha, desde, hasta)
    q = q.group_by(Venta.id_cliente)

    total = 0
    recurrentes = 0
    suma_pedidos = 0
    for r in q.all():
        total += 1
        suma_pedidos += r.pedidos
        if r.pedidos >= 2:
            recurrentes += 1

    tasa = (recurrentes / total * 100) if total else 0
    frecuencia = (suma_pedidos / total) if total else 0

    return {
        "clientes_total": total,
        "clientes_recurrentes": recurrentes,
        "tasa_recompra_pct": round(tasa, 2),
        "frecuencia_promedio_pedidos": round(frecuencia, 2),
    }


def formas_pago(db: Session, desde: date | None = None, hasta: date | None = None) -> list[dict[str, Any]]:
    """Mix de cajas (formas de pago) usadas en ventas. Suma caja1 + caja2."""
    from sqlalchemy import literal_column, union_all

    q1 = db.query(
        Venta.caja1.label("caja"),
        func.coalesce(Venta.monto_pago1, 0).label("monto"),
    ).filter(Venta.caja1.isnot(None))
    q1 = _filtro_fecha(q1, Venta.fecha, desde, hasta)

    q2 = db.query(
        Venta.caja2.label("caja"),
        func.coalesce(Venta.monto_pago2, 0).label("monto"),
    ).filter(Venta.caja2.isnot(None))
    q2 = _filtro_fecha(q2, Venta.fecha, desde, hasta)

    sub = union_all(q1, q2).subquery()
    rows = db.query(
        sub.c.caja,
        func.count().label("pagos"),
        func.sum(sub.c.monto).label("monto"),
    ).group_by(sub.c.caja).order_by(func.sum(sub.c.monto).desc()).all()

    # `pagos` cuenta líneas de pago (caja1 + caja2 unidas), NO ventas.
    # Una venta con pago split (efectivo + transferencia) suma 2 pagos.
    total = sum(_to_float(r.monto) for r in rows) or 1
    return [
        {
            "caja": r.caja,
            "pagos": r.pagos,
            "monto": _to_float(r.monto),
            "pct": round(_to_float(r.monto) / total * 100, 2),
        }
        for r in rows
    ]


def cohortes_retencion(
    db: Session,
    meses_max: int = 12,
    minimo_cohorte: int = 5,
) -> dict[str, Any]:
    """Análisis de cohortes: por cada mes de primera compra, qué % de los
    clientes vuelven a comprar 1, 2, 3, ... N meses después.

    Cohortes con menos de `minimo_cohorte` clientes se excluyen para evitar
    ruido visual (porcentajes erráticos sobre n=2-3 clientes).
    """
    from collections import defaultdict

    rows = db.query(Venta.id_cliente, Venta.fecha).filter(
        Venta.id_cliente.isnot(None)
    ).all()

    cliente_meses: dict = defaultdict(set)
    for cliente, fecha in rows:
        cliente_meses[cliente].add((fecha.year, fecha.month))

    cohortes_data: dict = defaultdict(list)
    for cliente, meses in cliente_meses.items():
        mes_alta = min(meses)
        cohortes_data[mes_alta].append(cliente)

    hoy = hoy_ar()
    hoy_ym = (hoy.year, hoy.month)

    result = []
    for mes_alta in sorted(cohortes_data.keys()):
        clientes = cohortes_data[mes_alta]
        tam = len(clientes)
        if tam < minimo_cohorte:
            continue
        retencion: list = [None] * (meses_max + 1)
        retencion[0] = 100.0
        for offset in range(1, meses_max + 1):
            year = mes_alta[0] + (mes_alta[1] - 1 + offset) // 12
            month = (mes_alta[1] - 1 + offset) % 12 + 1
            target = (year, month)
            if target > hoy_ym:
                retencion[offset] = None
                continue
            n = sum(1 for c in clientes if target in cliente_meses[c])
            retencion[offset] = round(100 * n / tam, 1)
        result.append({
            "mes_alta": f"{mes_alta[0]}-{mes_alta[1]:02d}",
            "tamano": tam,
            "retencion": retencion,
        })

    return {
        "meses_max": meses_max,
        "minimo_cohorte": minimo_cohorte,
        "cohortes": result,
    }


def productos_a_perdida(db: Session, desde: date | None = None, hasta: date | None = None,
                        limite: int = 50) -> list[dict[str, Any]]:
    """Productos cuyo margen agregado es negativo (precio < costo en suma).

    Decisión de diseño (jurado adversarial): condición `margen < 0` ESTRICTA.
    Vender al costo (margen = 0) NO entra al listado. Razones:
    - "Pérdida" semánticamente = números rojos.
    - PyMEs hacen promos "combo al costo" deliberadamente (retención, liquidación)
      — incluirlos diluye señal de pérdida real.
    - Robustez ante redondeo de centavos en agregados.
    Si en el futuro se necesita señal temprana de "productos sin rentabilidad"
    (margen=0, prelude a negativo si sube costo), crear alert SEPARADO en
    vez de mezclar con éste.
    """
    margen_expr = func.sum(DetalleVenta.subtotal - DetalleVenta.cst)
    q = db.query(
        DetalleVenta.producto,
        func.sum(DetalleVenta.subtotal).label("ingresos"),
        func.sum(DetalleVenta.cst).label("costo"),
        margen_expr.label("margen"),
        func.sum(DetalleVenta.cantidad).label("cantidad"),
    ).filter(
        DetalleVenta.categoria_linea == "mercaderia",
        DetalleVenta.cst.isnot(None),
    )
    q = _filtro_fecha(q, DetalleVenta.fecha, desde, hasta)
    q = q.group_by(DetalleVenta.producto).having(margen_expr < 0)
    # Tiebreaker por nombre de producto: sin esto, dos productos con
    # margen exactamente igual quedan en orden no determinístico (depende
    # del optimizador SQLite). Resultado: la dueña veía "Pan" arriba un
    # día y "Leche" otro día con mismo margen — flicker confuso.
    q = q.order_by(margen_expr.asc(), DetalleVenta.producto.asc()).limit(limite)

    return [
        {
            "producto": r.producto,
            "ingresos": _to_float(r.ingresos),
            "costo": _to_float(r.costo),
            "margen": _to_float(r.margen),
            "cantidad": _to_float(r.cantidad),
        }
        for r in q.all()
    ]
