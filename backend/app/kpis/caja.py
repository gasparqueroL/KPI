"""KPIs de caja y finanzas."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, func, literal, or_, union_all
from sqlalchemy.orm import Session

from app.kpis._fechas import filtro_fecha as _filtro_fecha, hasta_fin_dia as _hasta_fin_dia, hoy_ar
from app.models.caja import Caja
from app.models.categoria_caja import CategoriaCaja
from app.models.movimiento_caja import MovimientoCaja
from app.models.venta import Venta


def _to_float(v) -> float:
    return float(v) if v is not None else 0.0


def saldos_por_caja(db: Session) -> list[dict[str, Any]]:
    """Calcula el saldo actual de cada caja sumando:
    - Ingresos por ventas (venta.total con caja1/caja2)
    - Movimientos de caja (caja_destino suma, caja_origen resta)

    Cajas con archivado_at NOT NULL se ocultan del listado. Sus
    movimientos siguen afectando OTRAS cajas (transferencias) — solo se
    oculta la fila de saldo de la caja archivada misma.
    """
    cajas = db.query(Caja).filter(
        Caja.archivado_at.is_(None)
    ).order_by(Caja.nombre_display).all()

    ventas_caja1 = dict(
        db.query(Venta.caja1, func.coalesce(func.sum(Venta.monto_pago1), 0))
        .filter(Venta.caja1.isnot(None))
        .group_by(Venta.caja1)
        .all()
    )
    ventas_caja2 = dict(
        db.query(Venta.caja2, func.coalesce(func.sum(Venta.monto_pago2), 0))
        .filter(Venta.caja2.isnot(None))
        .group_by(Venta.caja2)
        .all()
    )
    ingresos_mov = dict(
        db.query(MovimientoCaja.caja_destino, func.coalesce(func.sum(MovimientoCaja.monto), 0))
        .filter(MovimientoCaja.caja_destino.isnot(None))
        .group_by(MovimientoCaja.caja_destino)
        .all()
    )
    egresos_mov = dict(
        db.query(MovimientoCaja.caja_origen, func.coalesce(func.sum(MovimientoCaja.monto), 0))
        .filter(MovimientoCaja.caja_origen.isnot(None))
        .group_by(MovimientoCaja.caja_origen)
        .all()
    )

    out = []
    for c in cajas:
        n = c.nombre_normalizado
        v1 = Decimal(str(ventas_caja1.get(n, 0)))
        v2 = Decimal(str(ventas_caja2.get(n, 0)))
        ing = Decimal(str(ingresos_mov.get(n, 0)))
        egr = Decimal(str(egresos_mov.get(n, 0)))
        saldo = v1 + v2 + ing - egr
        out.append({
            "caja": c.nombre_display,
            "tipo": c.tipo,
            "ingresos_ventas": _to_float(v1 + v2),
            "ingresos_movimientos": _to_float(ing),
            "egresos_movimientos": _to_float(egr),
            "saldo": _to_float(saldo),
        })
    out.sort(key=lambda r: r["saldo"], reverse=True)
    return out


def saldos_por_caja_al(db: Session, fecha_corte: date) -> list[dict[str, Any]]:
    """Igual que `saldos_por_caja` pero al cierre de `fecha_corte` (inclusive).

    Necesario para reportes retroactivos honestos: si la dueña pide un PDF
    del martes el jueves, los saldos deben ser los del martes 23:59, no
    los del jueves al momento de imprimir. Sin esto, el PDF dice una cosa
    y muestra otra (bug semántico en reportes financieros).

    Implementación: misma lógica que `saldos_por_caja` agregando filtro
    por `fecha <= fecha_corte` en cada query agregada. Para 250 movs es
    trivial (~5ms); para 50k movs, ~30ms.

    Cajas archivadas se excluyen (igual que `saldos_por_caja`).
    """
    cajas = db.query(Caja).filter(
        Caja.archivado_at.is_(None)
    ).order_by(Caja.nombre_display).all()

    ventas_caja1 = dict(
        db.query(Venta.caja1, func.coalesce(func.sum(Venta.monto_pago1), 0))
        .filter(Venta.caja1.isnot(None), Venta.fecha <= _hasta_fin_dia(fecha_corte))
        .group_by(Venta.caja1)
        .all()
    )
    ventas_caja2 = dict(
        db.query(Venta.caja2, func.coalesce(func.sum(Venta.monto_pago2), 0))
        .filter(Venta.caja2.isnot(None), Venta.fecha <= _hasta_fin_dia(fecha_corte))
        .group_by(Venta.caja2)
        .all()
    )
    ingresos_mov = dict(
        db.query(MovimientoCaja.caja_destino, func.coalesce(func.sum(MovimientoCaja.monto), 0))
        .filter(MovimientoCaja.caja_destino.isnot(None), MovimientoCaja.fecha <= fecha_corte)
        .group_by(MovimientoCaja.caja_destino)
        .all()
    )
    egresos_mov = dict(
        db.query(MovimientoCaja.caja_origen, func.coalesce(func.sum(MovimientoCaja.monto), 0))
        .filter(MovimientoCaja.caja_origen.isnot(None), MovimientoCaja.fecha <= fecha_corte)
        .group_by(MovimientoCaja.caja_origen)
        .all()
    )

    out = []
    for c in cajas:
        n = c.nombre_normalizado
        v1 = Decimal(str(ventas_caja1.get(n, 0)))
        v2 = Decimal(str(ventas_caja2.get(n, 0)))
        ing = Decimal(str(ingresos_mov.get(n, 0)))
        egr = Decimal(str(egresos_mov.get(n, 0)))
        saldo = v1 + v2 + ing - egr
        out.append({
            "caja": c.nombre_display,
            "tipo": c.tipo,
            "ingresos_ventas": _to_float(v1 + v2),
            "ingresos_movimientos": _to_float(ing),
            "egresos_movimientos": _to_float(egr),
            "saldo": _to_float(saldo),
        })
    out.sort(key=lambda r: r["saldo"], reverse=True)
    return out


def saldo_total(db: Session) -> dict[str, Any]:
    """Saldo total agregado de toda la empresa, separado por tipo de caja."""
    saldos = saldos_por_caja(db)
    operativas = sum(r["saldo"] for r in saldos if r["tipo"] == "operativa")
    fc = sum(r["saldo"] for r in saldos if r["tipo"] == "fc_empleado")
    return {
        "saldo_total": operativas + fc,
        "saldo_cajas_operativas": operativas,
        "saldo_cajas_fc": fc,
        "cantidad_cajas": len(saldos),
    }


def flujo_caja(
    db: Session,
    periodo: str = "mes",
    desde: date | None = None,
    hasta: date | None = None,
) -> list[dict[str, Any]]:
    """Flujo de caja real: ingresos por ventas + ingresos de movimientos vs egresos.

    Excluye transferencias internas y categorías marcadas excluir_flujo.
    """
    fmt = {"dia": "%Y-%m-%d", "semana": "%Y-W%W", "mes": "%Y-%m", "anio": "%Y"}.get(periodo)
    if fmt is None:
        raise ValueError(f"Periodo inválido: {periodo}")

    # 1) Ingresos por ventas: monto_pago1 + monto_pago2 por período
    bucket_v = func.strftime(fmt, Venta.fecha).label("periodo")
    qv = db.query(
        bucket_v,
        func.coalesce(
            func.sum(func.coalesce(Venta.monto_pago1, 0) + func.coalesce(Venta.monto_pago2, 0)),
            0,
        ).label("ventas_caja"),
    )
    qv = _filtro_fecha(qv, Venta.fecha, desde, hasta)
    qv = qv.group_by(bucket_v)
    ventas_por_periodo = {r.periodo: Decimal(str(r.ventas_caja or 0)) for r in qv.all()}

    # 2) Movimientos: ingresos/egresos puros, excluyendo categorías especiales
    bucket = func.strftime(fmt, MovimientoCaja.fecha).label("periodo")

    cats_excluidas = {
        c.tipo_operacion for c in db.query(CategoriaCaja).filter(
            (CategoriaCaja.excluir_flujo == True) | (CategoriaCaja.es_transferencia == True)
        ).all()
    }

    q = db.query(
        bucket,
        func.coalesce(func.sum(case(
            (MovimientoCaja.caja_destino.isnot(None) & MovimientoCaja.caja_origen.is_(None),
             MovimientoCaja.monto), else_=0)), 0).label("ingresos_mov"),
        func.coalesce(func.sum(case(
            (MovimientoCaja.caja_origen.isnot(None) & MovimientoCaja.caja_destino.is_(None),
             MovimientoCaja.monto), else_=0)), 0).label("egresos_mov"),
    )
    if cats_excluidas:
        q = q.filter(~MovimientoCaja.tipo_operacion.in_(cats_excluidas))
    q = _filtro_fecha(q, MovimientoCaja.fecha, desde, hasta)
    q = q.group_by(bucket).order_by(bucket)
    mov_por_periodo = {
        r.periodo: (Decimal(str(r.ingresos_mov or 0)), Decimal(str(r.egresos_mov or 0)))
        for r in q.all()
    }

    # 3) Combinar
    todos = sorted(set(ventas_por_periodo.keys()) | set(mov_por_periodo.keys()))
    out = []
    for p in todos:
        v = ventas_por_periodo.get(p, Decimal(0))
        ing_mov, egr_mov = mov_por_periodo.get(p, (Decimal(0), Decimal(0)))
        ing_total = v + ing_mov
        out.append({
            "periodo": p,
            "ingresos_ventas": _to_float(v),
            "ingresos_movimientos": _to_float(ing_mov),
            "ingresos": _to_float(ing_total),
            "egresos": _to_float(egr_mov),
            "neto": _to_float(ing_total - egr_mov),
        })
    return out


def actividad_dia(db: Session, fecha: date | None = None) -> dict[str, Any]:
    """Resumen rápido de la actividad de un día específico (default hoy AR).

    Pensado para que la dueña abra la app y vea de un saque "qué pasó hoy"
    sin tener que abrir reportes. Compacta:
    - Ventas del día (monto + cantidad de pedidos).
    - Ingresos operativos (cobranzas con caja_destino y sin caja_origen).
    - Egresos operativos (gastos puros).
    - Top 3 familias de gasto del día.
    """
    if fecha is None:
        fecha = hoy_ar()
    fin_dia = datetime.combine(fecha, time.max)
    inicio_dia = datetime.combine(fecha, time.min)

    # Ventas del día (Venta.fecha es DateTime, hay que cubrir todo el día)
    v_row = db.query(
        func.coalesce(func.sum(Venta.total), 0).label("monto"),
        func.count(Venta.id_pedido).label("pedidos"),
    ).filter(
        Venta.fecha >= inicio_dia,
        Venta.fecha <= fin_dia,
    ).first()

    # Ingresos operativos: caja_destino isnot None Y caja_origen is None
    ingresos_op = db.query(
        func.coalesce(func.sum(MovimientoCaja.monto), 0)
    ).filter(
        MovimientoCaja.fecha == fecha,
        MovimientoCaja.caja_destino.isnot(None),
        MovimientoCaja.caja_origen.is_(None),
    ).scalar()

    # Egresos operativos: caja_origen isnot None Y caja_destino is None
    egresos_op = db.query(
        func.coalesce(func.sum(MovimientoCaja.monto), 0)
    ).filter(
        MovimientoCaja.fecha == fecha,
        MovimientoCaja.caja_origen.isnot(None),
        MovimientoCaja.caja_destino.is_(None),
    ).scalar()

    # Top 3 familias de gasto del día
    top_fam = db.query(
        func.coalesce(CategoriaCaja.familia, "Sin clasificar").label("familia"),
        func.coalesce(func.sum(MovimientoCaja.monto), 0).label("monto"),
    ).outerjoin(
        CategoriaCaja, CategoriaCaja.tipo_operacion == MovimientoCaja.tipo_operacion,
    ).filter(
        MovimientoCaja.fecha == fecha,
        MovimientoCaja.caja_origen.isnot(None),
        MovimientoCaja.caja_destino.is_(None),
    ).group_by("familia").order_by(func.sum(MovimientoCaja.monto).desc()).limit(3).all()

    return {
        "fecha": fecha.isoformat(),
        "ventas_monto": _to_float(v_row.monto if v_row else 0),
        "ventas_pedidos": v_row.pedidos if v_row else 0,
        "ingresos_operativos": _to_float(ingresos_op or 0),
        "egresos_operativos": _to_float(egresos_op or 0),
        "neto_operativo": _to_float((ingresos_op or 0) - (egresos_op or 0)),
        "top_familias_gasto": [
            {"familia": r.familia, "monto": _to_float(r.monto)}
            for r in top_fam
        ],
    }


def movimientos_atipicos(
    db: Session,
    factor: float = 5.0,
    dias_historia: int = 90,
    dias_recientes: int = 30,
    minimo_historico: int = 3,
) -> list[dict[str, Any]]:
    """Detecta movimientos cuyo monto es atípicamente grande respecto al
    patrón histórico de su `tipo_operacion`.

    Útil para detectar:
    - Errores de carga (typo en monto: $5.000.000 en lugar de $50.000).
    - Gastos anómalos a revisar (fraude, compra inusual).

    Algoritmo simple y robusto para PyME:
    1. Para cada `tipo_operacion`, calcular promedio de monto en los
       últimos `dias_historia` días, **excluyendo** los `dias_recientes`
       últimos (para no contaminar con el atípico mismo).
    2. Si tiene `>= minimo_historico` movs en ese período, es categoría
       comparable.
    3. Listar movs de los últimos `dias_recientes` cuyo monto > `factor` ×
       promedio histórico.

    Solo egresos puros (mismo criterio que composicion_gastos)."""
    hoy = hoy_ar()
    corte_recientes = hoy - timedelta(days=dias_recientes)
    corte_historia = hoy - timedelta(days=dias_historia)

    # Promedios históricos por tipo_operacion (excluyendo el período reciente).
    promedios_rows = db.query(
        MovimientoCaja.tipo_operacion,
        func.avg(MovimientoCaja.monto).label("promedio"),
        func.count().label("n"),
    ).filter(
        MovimientoCaja.caja_origen.isnot(None),
        MovimientoCaja.caja_destino.is_(None),
        MovimientoCaja.fecha >= corte_historia,
        MovimientoCaja.fecha < corte_recientes,
    ).group_by(MovimientoCaja.tipo_operacion).all()

    # Solo categorías con >= minimo_historico movs (sino el promedio es ruido).
    # Defensa adicional: descartamos promedios <= 0. Caso real: promociones
    # a costo cero o categorías mal cargadas con todos los montos en 0.
    # Sin este guard, la división `monto/promedio` explota.
    promedios = {
        r.tipo_operacion: float(r.promedio)
        for r in promedios_rows
        if r.n >= minimo_historico and r.promedio and float(r.promedio) > 0
    }
    if not promedios:
        return []

    # Movimientos recientes a chequear
    movs_recientes = db.query(MovimientoCaja).filter(
        MovimientoCaja.caja_origen.isnot(None),
        MovimientoCaja.caja_destino.is_(None),
        MovimientoCaja.fecha >= corte_recientes,
        MovimientoCaja.tipo_operacion.in_(promedios.keys()),
    ).order_by(MovimientoCaja.monto.desc()).all()

    out = []
    for m in movs_recientes:
        prom = promedios[m.tipo_operacion]
        ratio = float(m.monto) / prom
        if ratio < factor:
            continue
        out.append({
            "id": m.id,
            "fecha": m.fecha.isoformat(),
            "tipo_operacion": m.tipo_operacion,
            "detalle": m.detalle,
            "monto": _to_float(m.monto),
            "caja_origen": m.caja_origen,
            "promedio_historico": round(prom, 2),
            "ratio": round(ratio, 1),
        })
    return out


def movimientos_por_familia(
    db: Session,
    familia: str,
    desde: date | None = None,
    hasta: date | None = None,
    limite: int = 200,
) -> list[dict[str, Any]]:
    """Drill-down de gastos por familia: lista los movimientos individuales
    que componen un sector del pie chart de composición.

    `familia` matchea contra `CategoriaCaja.familia`. El valor especial
    `"Sin clasificar"` agrupa los tipos sin familia asignada (mismo criterio
    que `composicion_gastos` con `coalesce`).

    Solo egresos puros (caja_origen sin caja_destino) — coherente con el
    pie chart. Ordenado por fecha desc (recientes primero).
    """
    q = db.query(
        MovimientoCaja.id,
        MovimientoCaja.fecha,
        MovimientoCaja.tipo_operacion,
        MovimientoCaja.detalle,
        MovimientoCaja.monto,
        MovimientoCaja.caja_origen,
        func.coalesce(CategoriaCaja.familia, "Sin clasificar").label("familia"),
    ).outerjoin(
        CategoriaCaja, CategoriaCaja.tipo_operacion == MovimientoCaja.tipo_operacion,
    ).filter(
        MovimientoCaja.caja_origen.isnot(None),
        MovimientoCaja.caja_destino.is_(None),
    )

    if familia == "Sin clasificar":
        q = q.filter(CategoriaCaja.familia.is_(None))
    else:
        q = q.filter(CategoriaCaja.familia == familia)

    q = _filtro_fecha(q, MovimientoCaja.fecha, desde, hasta)
    q = q.order_by(MovimientoCaja.fecha.desc(), MovimientoCaja.id.desc())
    q = q.limit(limite)

    return [
        {
            "id": r.id,
            "fecha": r.fecha.isoformat(),
            "tipo_operacion": r.tipo_operacion,
            "detalle": r.detalle,
            "monto": _to_float(r.monto),
            "caja_origen": r.caja_origen,
            "familia": r.familia,
        }
        for r in q.all()
    ]


def composicion_gastos(
    db: Session,
    desde: date | None = None,
    hasta: date | None = None,
    agrupar_por: str = "familia",
    incluir_transferencias: bool = False,
    incluir_retiros: bool = False,
) -> list[dict[str, Any]]:
    """Distribución de egresos. Por defecto excluye transferencias, retiros y excluir_flujo."""
    if agrupar_por not in ("tipo_operacion", "familia"):
        raise ValueError(f"agrupar_por inválido: {agrupar_por}")

    clave_col = (
        MovimientoCaja.tipo_operacion
        if agrupar_por == "tipo_operacion"
        else func.coalesce(CategoriaCaja.familia, "Sin clasificar")
    )

    q = db.query(
        clave_col.label("clave"),
        func.coalesce(func.sum(MovimientoCaja.monto), 0).label("monto"),
        func.count().label("operaciones"),
    ).outerjoin(
        CategoriaCaja, CategoriaCaja.tipo_operacion == MovimientoCaja.tipo_operacion
    ).filter(
        MovimientoCaja.caja_origen.isnot(None),
        MovimientoCaja.caja_destino.is_(None),
    )

    # Excluir categorías marcadas como flujo-excluido, transferencias y retiros
    clauses = [CategoriaCaja.excluir_flujo == True]
    if not incluir_transferencias:
        clauses.append(CategoriaCaja.es_transferencia == True)
    if not incluir_retiros:
        clauses.append(CategoriaCaja.es_retiro == True)
    excluidas = {
        r[0] for r in db.query(CategoriaCaja.tipo_operacion).filter(or_(*clauses)).all()
    }
    if excluidas:
        q = q.filter(~MovimientoCaja.tipo_operacion.in_(excluidas))

    q = _filtro_fecha(q, MovimientoCaja.fecha, desde, hasta)
    q = q.group_by(clave_col).order_by(func.sum(MovimientoCaja.monto).desc())

    rows = q.all()
    total = sum(_to_float(r.monto) for r in rows) or 1
    return [
        {
            "categoria": r.clave,
            "monto": _to_float(r.monto),
            "operaciones": r.operaciones,
            "pct": round(_to_float(r.monto) / total * 100, 2),
        }
        for r in rows
    ]


def top_gastos(
    db: Session,
    desde: date | None = None,
    hasta: date | None = None,
    limite: int = 20,
) -> list[dict[str, Any]]:
    q = db.query(MovimientoCaja).filter(
        MovimientoCaja.caja_origen.isnot(None),
        MovimientoCaja.caja_destino.is_(None),
    )
    q = _filtro_fecha(q, MovimientoCaja.fecha, desde, hasta)
    q = q.order_by(MovimientoCaja.monto.desc()).limit(limite)
    return [
        {
            "fecha": m.fecha.isoformat(),
            "tipo_operacion": m.tipo_operacion,
            "detalle": m.detalle,
            "monto": _to_float(m.monto),
            "caja_origen": m.caja_origen,
        }
        for m in q.all()
    ]


def resumen_caja(
    db: Session,
    desde: date | None = None,
    hasta: date | None = None,
) -> dict[str, Any]:
    """Resumen rápido: total ingresos, egresos, neto y saldo total actual."""
    q = db.query(
        func.coalesce(func.sum(case(
            (MovimientoCaja.caja_destino.isnot(None) & MovimientoCaja.caja_origen.is_(None),
             MovimientoCaja.monto), else_=0)), 0).label("ingresos"),
        func.coalesce(func.sum(case(
            (MovimientoCaja.caja_origen.isnot(None) & MovimientoCaja.caja_destino.is_(None),
             MovimientoCaja.monto), else_=0)), 0).label("egresos"),
        func.coalesce(func.sum(case(
            (MovimientoCaja.caja_destino.isnot(None) & MovimientoCaja.caja_origen.isnot(None),
             MovimientoCaja.monto), else_=0)), 0).label("transferencias"),
    )
    q = _filtro_fecha(q, MovimientoCaja.fecha, desde, hasta)
    r = q.one()
    ingresos = Decimal(str(r.ingresos or 0))
    egresos = Decimal(str(r.egresos or 0))
    transferencias = Decimal(str(r.transferencias or 0))

    saldo = saldo_total(db)

    return {
        "ingresos_movimientos": _to_float(ingresos),
        "egresos_movimientos": _to_float(egresos),
        "neto_movimientos": _to_float(ingresos - egresos),
        "transferencias_internas": _to_float(transferencias),
        "saldo_total_actual": saldo["saldo_total"],
        "saldo_cajas_operativas": saldo["saldo_cajas_operativas"],
        "saldo_cajas_fc": saldo["saldo_cajas_fc"],
    }
