"""Cuentas corrientes por cliente.

Vista tipo extracto bancario:
- Ventas marcadas como cuenta corriente (o sin cobro) = cargos (DEBE)
- Movimientos de cobranza vinculados a ese cliente = pagos (HABER)
- Saldo running = lo que el cliente debe (positivo) o le sobró (negativo)
"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.kpis._fechas import hoy_ar

from app.models.categoria_caja import CategoriaCaja
from app.models.movimiento_caja import MovimientoCaja
from app.models.pago_aplicado import PagoAplicado
from app.models.venta import Venta


def _to_float(v) -> float:
    return float(v) if v is not None else 0.0


def _es_venta_pendiente(v: Venta) -> bool:
    """Una venta cuenta como cargo a cta cte si:
    - está marcada explícitamente, O
    - no tiene cobro registrado y total > 0 (probable cta cte mal marcada)
    """
    if v.es_cuenta_corriente:
        return True
    suma = (v.monto_pago1 or Decimal(0)) + (v.monto_pago2 or Decimal(0))
    return suma == 0 and v.total > 0


def clientes_con_cuenta(db: Session) -> list[dict[str, Any]]:
    """Lista de clientes con saldo distinto de cero o que tienen actividad
    de cuenta corriente. Ordenada por saldo descendente."""
    # Sub: cargos por cliente. Se agrupa SOLO por id_cliente para evitar
    # duplicados cuando el nombre tiene typos entre ventas. El nombre se
    # resuelve con MAX (uno cualquiera).
    cargos_q = db.query(
        Venta.id_cliente,
        func.max(Venta.cliente).label("cliente"),
        func.count(Venta.id_pedido).label("ventas_pendientes"),
        func.coalesce(func.sum(Venta.total), 0).label("monto_cargado"),
    ).filter(
        Venta.id_cliente.isnot(None),
        or_(
            Venta.es_cuenta_corriente == True,
            (
                (func.coalesce(Venta.monto_pago1, 0) + func.coalesce(Venta.monto_pago2, 0)) == 0
            ) & (Venta.total > 0),
        ),
    ).group_by(Venta.id_cliente).all()

    # Sub: pagos por cliente (movimientos asignados)
    pagos_q = db.query(
        MovimientoCaja.id_cliente_relacionado,
        func.coalesce(func.sum(MovimientoCaja.monto), 0).label("monto_pagado"),
        func.count().label("pagos"),
    ).filter(
        MovimientoCaja.id_cliente_relacionado.isnot(None),
        MovimientoCaja.caja_destino.isnot(None),
    ).group_by(MovimientoCaja.id_cliente_relacionado).all()
    pagos_dict = {p.id_cliente_relacionado: p for p in pagos_q}

    out = []
    for c in cargos_q:
        p = pagos_dict.get(c.id_cliente)
        cargado = Decimal(str(c.monto_cargado or 0))
        pagado = Decimal(str(p.monto_pagado if p else 0))
        out.append({
            "id_cliente": c.id_cliente,
            "cliente": c.cliente,
            "ventas_pendientes": c.ventas_pendientes,
            "monto_cargado": _to_float(cargado),
            "pagos_recibidos": p.pagos if p else 0,
            "monto_pagado": _to_float(pagado),
            "saldo": _to_float(cargado - pagado),
        })

    # Sumar también clientes que SOLO tienen pagos asignados sin venta marcada
    cargos_clientes = {c.id_cliente for c in cargos_q}
    for cli, p in pagos_dict.items():
        if cli in cargos_clientes:
            continue
        # Buscar nombre del cliente desde la tabla ventas
        nombre = db.query(Venta.cliente).filter(
            Venta.id_cliente == cli
        ).limit(1).scalar() or f"Cliente #{cli}"
        out.append({
            "id_cliente": cli,
            "cliente": nombre,
            "ventas_pendientes": 0,
            "monto_cargado": 0.0,
            "pagos_recibidos": p.pagos,
            "monto_pagado": _to_float(p.monto_pagado),
            "saldo": -_to_float(p.monto_pagado),
        })

    out.sort(key=lambda r: r["saldo"], reverse=True)
    return out


def ledger_cliente(db: Session, id_cliente: int) -> dict[str, Any]:
    """Extracto del cliente: ventas + cobranzas en orden cronológico
    con saldo running."""
    cliente_nombre = db.query(Venta.cliente).filter(
        Venta.id_cliente == id_cliente
    ).limit(1).scalar() or f"Cliente #{id_cliente}"

    # Ventas pendientes del cliente
    ventas = db.query(Venta).filter(
        Venta.id_cliente == id_cliente,
        or_(
            Venta.es_cuenta_corriente == True,
            (
                (func.coalesce(Venta.monto_pago1, 0) + func.coalesce(Venta.monto_pago2, 0)) == 0
            ) & (Venta.total > 0),
        ),
    ).order_by(Venta.fecha).all()

    # Movimientos asignados al cliente — solo ingresos puros
    # (caja_destino presente, sin caja_origen). Esto excluye transferencias
    # y egresos que pudieron asignarse erróneamente antes del fix de C1.
    movs = db.query(MovimientoCaja).filter(
        MovimientoCaja.id_cliente_relacionado == id_cliente,
        MovimientoCaja.caja_destino.isnot(None),
        MovimientoCaja.caja_origen.is_(None),
    ).order_by(MovimientoCaja.fecha).all()

    eventos = []
    for v in ventas:
        # Para Venta.fecha (datetime) usamos el datetime completo para
        # ordenar dos ventas del mismo día por hora real.
        eventos.append({
            "fecha": v.fecha.isoformat(),
            "_fecha_orden": v.fecha if isinstance(v.fecha, datetime) else datetime.combine(v.fecha, time.min),
            "_id_orden": v.id_pedido,
            "tipo": "venta",
            "descripcion": f"Venta {v.id_pedido[:8]} - {v.vendedor or '?'}{' [marcada cta cte]' if v.es_cuenta_corriente else ' [sin cobro]'}",
            "debe": float(v.total),
            "haber": 0.0,
            "ref_id": v.id_pedido,
            "ref_tipo": "venta",
            "venta_cliente": v.cliente,
            "venta_vendedor": v.vendedor,
            "venta_total": float(v.total),
            "venta_caja1": v.caja1,
            "venta_monto_pago1": float(v.monto_pago1) if v.monto_pago1 else None,
            "venta_pago_v1": v.pago_v1,
            "venta_caja2": v.caja2,
            "venta_monto_pago2": float(v.monto_pago2) if v.monto_pago2 else None,
            "venta_pago_v2": v.pago_v2,
            "venta_es_cuenta_corriente": v.es_cuenta_corriente,
        })
    for m in movs:
        # MovimientoCaja.fecha es Date; lo subimos a datetime al medio
        # del día para que un pago del mismo día caiga DESPUÉS de la
        # venta (que ya tiene hora real) — convención contable.
        m_fecha = m.fecha if isinstance(m.fecha, datetime) else datetime.combine(m.fecha, time.min)
        eventos.append({
            "fecha": m.fecha.isoformat(),
            "_fecha_orden": m_fecha,
            "_id_orden": m.id,
            "tipo": "pago",
            "descripcion": f"{m.tipo_operacion}: {m.detalle or ''}",
            "debe": 0.0,
            "haber": float(m.monto),
            "ref_id": m.id,
            "ref_tipo": "movimiento",
        })

    # Sort por (date, tipo, datetime, id):
    # - Convención contable mantenida: ventas antes que pagos del mismo día.
    # - Dentro del mismo (date, tipo), desempata por hora real y luego por id.
    eventos.sort(key=lambda e: (
        e["_fecha_orden"].date(),
        0 if e["tipo"] == "venta" else 1,
        e["_fecha_orden"],
        str(e["_id_orden"]),
    ))
    for e in eventos:
        e.pop("_fecha_orden", None)
        e.pop("_id_orden", None)

    saldo = Decimal(0)
    for e in eventos:
        saldo += Decimal(str(e["debe"])) - Decimal(str(e["haber"]))
        e["saldo"] = float(saldo)

    total_debe = sum(e["debe"] for e in eventos)
    total_haber = sum(e["haber"] for e in eventos)

    return {
        "id_cliente": id_cliente,
        "cliente": cliente_nombre,
        "saldo_actual": float(saldo),
        "total_debe": total_debe,
        "total_haber": total_haber,
        "eventos": eventos,
    }


def movimientos_sin_asignar(
    db: Session,
    busqueda: str | None = None,
    limite: int = 100,
) -> list[dict[str, Any]]:
    """Movimientos que parecen cobranzas (ingreso operativo) y NO están
    vinculados a ningún cliente. Para que el usuario los asigne."""
    q = db.query(MovimientoCaja).join(
        CategoriaCaja, CategoriaCaja.tipo_operacion == MovimientoCaja.tipo_operacion
    ).filter(
        CategoriaCaja.es_ingreso_operativo == True,
        MovimientoCaja.id_cliente_relacionado.is_(None),
        MovimientoCaja.caja_destino.isnot(None),
    )
    if busqueda:
        q = q.filter(MovimientoCaja.detalle.ilike(f"%{busqueda}%"))
    q = q.order_by(MovimientoCaja.fecha.desc()).limit(limite)
    return [
        {
            "id": m.id,
            "fecha": m.fecha.isoformat(),
            "tipo_operacion": m.tipo_operacion,
            "detalle": m.detalle,
            "monto": float(m.monto),
            "caja_destino": m.caja_destino,
        }
        for m in q.all()
    ]


def aging_cobros(db: Session) -> dict[str, Any]:
    """Aging de saldos pendientes por cliente, agrupado en buckets temporales.

    Convención: FIFO clásico — los pagos no específicos se imputan a la
    deuda más antigua primero. Para imputación venta-por-venta usar
    `pagos_aplicados`: si una venta tiene aplicaciones explícitas, su
    saldo se calcula `total - sum(aplicados)` y se descuenta del bucket
    correspondiente, sin pasar por la cobranza cliente-nivel.

    Devuelve además:
    - `con_credito`: clientes con saldo a favor (sobrepago/anticipo).
    """
    hoy = hoy_ar()
    cortes = ["bucket_0_30", "bucket_31_60", "bucket_61_90", "bucket_90_mas"]

    # Cobranzas cliente-nivel (excluye transferencias).
    pagado_por_cliente = dict(
        db.query(
            MovimientoCaja.id_cliente_relacionado,
            func.coalesce(func.sum(MovimientoCaja.monto), 0),
        ).filter(
            MovimientoCaja.id_cliente_relacionado.isnot(None),
            MovimientoCaja.caja_destino.isnot(None),
            MovimientoCaja.caja_origen.is_(None),
        ).group_by(MovimientoCaja.id_cliente_relacionado).all()
    )

    # Pagos aplicados venta-nivel (Sesión 4): por venta, suma aplicada.
    aplicado_por_venta = dict(
        db.query(
            PagoAplicado.id_venta,
            func.coalesce(func.sum(PagoAplicado.monto), 0),
        ).group_by(PagoAplicado.id_venta).all()
    )

    # Movimientos cliente-nivel cuyo cobro YA fue parcial/totalmente
    # aplicado a una venta vía pagos_aplicados: se resta del cliente-nivel
    # para no contar dos veces (camino viejo + camino nuevo).
    aplicado_cliente_nivel = dict(
        db.query(
            MovimientoCaja.id_cliente_relacionado,
            func.coalesce(func.sum(PagoAplicado.monto), 0),
        ).join(PagoAplicado, PagoAplicado.id_movimiento == MovimientoCaja.id)
        .filter(MovimientoCaja.id_cliente_relacionado.isnot(None))
        .group_by(MovimientoCaja.id_cliente_relacionado).all()
    )
    for cli_id, ap in aplicado_cliente_nivel.items():
        actual = Decimal(str(pagado_por_cliente.get(cli_id, 0)))
        pagado_por_cliente[cli_id] = actual - Decimal(str(ap))

    # Perf: cargar solo columnas necesarias en vez de hidratar el ORM completo.
    ventas_rows = db.query(
        Venta.id_pedido, Venta.id_cliente, Venta.cliente, Venta.fecha, Venta.total
    ).filter(
        Venta.id_cliente.isnot(None),
        or_(
            Venta.es_cuenta_corriente == True,
            (
                (func.coalesce(Venta.monto_pago1, 0) + func.coalesce(Venta.monto_pago2, 0)) == 0
            ) & (Venta.total > 0),
        ),
    ).order_by(Venta.fecha).all()

    por_cliente: dict = defaultdict(lambda: {"nombre": None, "buckets": defaultdict(Decimal), "total": Decimal(0)})

    for id_pedido, id_cli, cli_nombre, vfecha, vtotal in ventas_rows:
        v_fecha = vfecha.date() if hasattr(vfecha, "date") else vfecha
        dias = max(0, (hoy - v_fecha).days)
        bucket = (
            "bucket_0_30" if dias <= 30
            else "bucket_31_60" if dias <= 60
            else "bucket_61_90" if dias <= 90
            else "bucket_90_mas"
        )
        # Si la venta tiene pagos aplicados explícitos, restar antes de
        # ubicarla en el bucket — su saldo "real" es total - aplicado.
        aplicado = Decimal(str(aplicado_por_venta.get(id_pedido, 0)))
        saldo_venta_neto = Decimal(str(vtotal)) - aplicado
        if saldo_venta_neto <= 0:
            continue
        info = por_cliente[id_cli]
        info["nombre"] = cli_nombre or info["nombre"]
        info["buckets"][bucket] += saldo_venta_neto
        info["total"] += saldo_venta_neto

    # FIFO clásico para imputar las cobranzas cliente-nivel restantes.
    orden_buckets = ["bucket_90_mas", "bucket_61_90", "bucket_31_60", "bucket_0_30"]
    for cli_id, info in por_cliente.items():
        pagado = Decimal(str(pagado_por_cliente.get(cli_id, 0)))
        if pagado <= 0:
            continue
        restante = pagado
        for b in orden_buckets:
            if restante <= 0:
                break
            si = info["buckets"].get(b, Decimal(0))
            if si > 0:
                aplicado = min(si, restante)
                info["buckets"][b] = si - aplicado
                restante -= aplicado
        info["total"] -= pagado

    items = []
    con_credito = []
    totales = {b: Decimal(0) for b in cortes}
    total_global = Decimal(0)
    for cli_id, info in por_cliente.items():
        if info["total"] > 0:
            item = {
                "id_cliente": cli_id,
                "cliente": info["nombre"],
                "total": _to_float(info["total"]),
                **{b: _to_float(info["buckets"].get(b, Decimal(0))) for b in cortes},
            }
            items.append(item)
            for b in cortes:
                totales[b] += info["buckets"].get(b, Decimal(0))
            total_global += info["total"]
        elif info["total"] < 0:
            con_credito.append({
                "id_cliente": cli_id,
                "cliente": info["nombre"],
                "credito_a_favor": _to_float(-info["total"]),
            })

    items.sort(key=lambda r: r["bucket_90_mas"], reverse=True)
    con_credito.sort(key=lambda r: r["credito_a_favor"], reverse=True)

    return {
        "totales": {**{b: _to_float(v) for b, v in totales.items()}, "total": _to_float(total_global)},
        "items": items,
        "con_credito": con_credito,
    }


def dso(db: Session, dias_ventana: int = 90) -> dict[str, Any]:
    """Days Sales Outstanding aproximado: días promedio que tardan los
    clientes en pagar.

    Fórmula: ``(saldo_pendiente / ventas_periodo) * dias_ventana``.
    NO es el DSO contable clásico (countback) — es una proxy útil que
    dice "qué fracción del periodo está aún pendiente, escalado a días".
    Resta los `pagos_aplicados` específicos a cada venta para no inflar
    el pendiente cuando hay cobertura granular.
    """
    hoy = hoy_ar()
    desde = hoy - timedelta(days=dias_ventana)
    desde_dt = datetime.combine(desde, time.min)

    ventas_total = db.query(func.coalesce(func.sum(Venta.total), 0)).filter(
        Venta.fecha >= desde_dt
    ).scalar()
    ventas_total = Decimal(str(ventas_total or 0))

    # Saldo pendiente: ventas del periodo que cumplen el predicado de
    # "deuda activa", restando los pagos_aplicados explícitos.
    ventas_pendientes = db.query(
        Venta.id_pedido, Venta.total
    ).filter(
        Venta.fecha >= desde_dt,
        or_(
            Venta.es_cuenta_corriente == True,
            (
                (func.coalesce(Venta.monto_pago1, 0) + func.coalesce(Venta.monto_pago2, 0)) == 0
            ) & (Venta.total > 0),
        ),
    ).all()
    aplicado_por_venta = dict(
        db.query(
            PagoAplicado.id_venta,
            func.coalesce(func.sum(PagoAplicado.monto), 0),
        ).group_by(PagoAplicado.id_venta).all()
    )
    pendiente = Decimal(0)
    for id_pedido, vtotal in ventas_pendientes:
        ap = Decimal(str(aplicado_por_venta.get(id_pedido, 0)))
        neto = Decimal(str(vtotal)) - ap
        if neto > 0:
            pendiente += neto

    # Sin ventas en el periodo la métrica no es calculable: devolver None
    # para que el frontend muestre "-" en vez de un engañoso "0 días"
    # (que sugeriría "los clientes pagan instantáneamente").
    if ventas_total > 0:
        dso_val = (pendiente / ventas_total) * dias_ventana
        dso_aprox = float(round(dso_val, 1))
    else:
        dso_aprox = None

    return {
        "dias_ventana": dias_ventana,
        "ventas_periodo": _to_float(ventas_total),
        "saldo_pendiente_periodo": _to_float(pendiente),
        # `dso_aprox_dias`: NO es DSO contable clásico (countback). Es proxy
        # = (saldo pendiente / ventas del periodo) * dias_ventana. El nombre
        # explicita la aproximación para que nadie lo cite como DSO formal.
        "dso_aprox_dias": dso_aprox,
    }
