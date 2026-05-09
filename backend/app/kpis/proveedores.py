"""KPIs de proveedores y cuentas a pagar."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.kpis._fechas import hoy_ar
from app.models.movimiento_caja import MovimientoCaja
from app.models.proveedor import FacturaProveedor, Proveedor

# Tolerancia: una factura con < 1 centavo pendiente se considera pagada.
TOLERANCIA_CENTAVO = Decimal("0.01")


def _to_float(v) -> float:
    return float(v) if v is not None else 0.0


def _q(d: Decimal) -> Decimal:
    """Cuantiza a 2 decimales para comparar/exponer sin ruido binario."""
    return Decimal(str(d)).quantize(Decimal("0.01"))


def proveedores_con_saldo(
    db: Session, incluir_inactivos: bool = False
) -> list[dict[str, Any]]:
    """Lista de proveedores con su saldo (facturado - pagado)."""
    facturado = dict(
        db.query(
            FacturaProveedor.id_proveedor,
            func.coalesce(func.sum(FacturaProveedor.total), 0),
        ).filter(
            FacturaProveedor.anulada == False,  # noqa: E712
        ).group_by(FacturaProveedor.id_proveedor).all()
    )

    pagado_por_factura = dict(
        db.query(
            MovimientoCaja.id_factura_proveedor,
            func.coalesce(func.sum(MovimientoCaja.monto), 0),
        ).filter(
            MovimientoCaja.id_factura_proveedor.isnot(None),
            MovimientoCaja.caja_origen.isnot(None),
            MovimientoCaja.caja_destino.is_(None),  # egreso puro, no transferencia
        ).group_by(MovimientoCaja.id_factura_proveedor).all()
    )

    facturas_a_proveedor = dict(
        db.query(FacturaProveedor.id, FacturaProveedor.id_proveedor).filter(
            FacturaProveedor.anulada == False  # noqa: E712
        ).all()
    )
    pagado_por_proveedor: dict = {}
    for fact_id, monto in pagado_por_factura.items():
        p = facturas_a_proveedor.get(fact_id)
        if p is not None:
            pagado_por_proveedor[p] = pagado_por_proveedor.get(p, Decimal(0)) + Decimal(str(monto))

    q = db.query(Proveedor)
    if not incluir_inactivos:
        q = q.filter(Proveedor.activo == True)  # noqa: E712

    out = []
    for p in q.order_by(Proveedor.nombre).all():
        f = Decimal(str(facturado.get(p.id, 0)))
        pa = Decimal(str(pagado_por_proveedor.get(p.id, 0)))
        saldo = f - pa
        out.append({
            "id": p.id,
            "nombre": p.nombre,
            "cuit": p.cuit,
            "contacto": p.contacto,
            "activo": p.activo,
            "facturado_total": _to_float(f),
            "pagado_total": _to_float(pa),
            "saldo": _to_float(saldo),
        })
    # Saldo > 0 primero, después negativos (anticipos), saldo 0 al final.
    def _sort_key(r):
        s = r["saldo"]
        if s > 0:
            return (0, -s)
        if s < 0:
            return (1, -s)
        return (2, 0)
    out.sort(key=_sort_key)
    return out


def ledger_proveedor(db: Session, id_proveedor: int) -> dict[str, Any]:
    """Extracto del proveedor: facturas (DEBE) + pagos vinculados (HABER).

    Cada evento factura incluye `pendiente` para que el frontend pueda
    filtrar facturas ya saldadas en selects de vinculación.
    """
    p = db.get(Proveedor, id_proveedor)
    if p is None:
        return {"id": id_proveedor, "nombre": "(no encontrado)", "eventos": []}

    facturas = db.query(FacturaProveedor).filter(
        FacturaProveedor.id_proveedor == id_proveedor
    ).order_by(FacturaProveedor.fecha_emision, FacturaProveedor.id).all()

    pagos = db.query(MovimientoCaja).join(
        FacturaProveedor, FacturaProveedor.id == MovimientoCaja.id_factura_proveedor
    ).filter(
        FacturaProveedor.id_proveedor == id_proveedor,
        MovimientoCaja.caja_origen.isnot(None),
        MovimientoCaja.caja_destino.is_(None),
    ).order_by(MovimientoCaja.fecha, MovimientoCaja.id).all()

    # Mapa pagado por factura para calcular pendiente.
    pagado_por_factura: dict[int, Decimal] = defaultdict(lambda: Decimal(0))
    for m in pagos:
        pagado_por_factura[m.id_factura_proveedor] += Decimal(str(m.monto))

    # Cantidad de pagos vinculados por factura — el front lo necesita para
    # decidir si permite editar `total` (no se puede si hay pagos) sin tener
    # que adivinarlo del campo `pendiente` (que falla en facturas anuladas
    # o con saldos exactos por casualidad).
    cant_pagos_por_factura: dict[int, int] = defaultdict(int)
    for m in pagos:
        cant_pagos_por_factura[m.id_factura_proveedor] += 1

    eventos = []
    for f in facturas:
        pendiente = Decimal(str(f.total)) - pagado_por_factura.get(f.id, Decimal(0))
        n_pagos = cant_pagos_por_factura.get(f.id, 0)
        eventos.append({
            "fecha": f.fecha_emision.isoformat(),
            "_fecha_orden": f.fecha_emision,
            "_id_orden": f.id,
            "tipo": "factura",
            # Campos estructurados — el front no debería parsear `descripcion`
            # para extraerlos. `descripcion` se mantiene como string compuesto
            # para retrocompatibilidad de la tabla del ledger.
            "numero": f.numero,
            "factura_descripcion": f.descripcion,
            "descripcion": f"Factura {f.numero or '(sin nro)'}{' - ' + f.descripcion if f.descripcion else ''}",
            "vencimiento": f.fecha_vencimiento.isoformat() if f.fecha_vencimiento else None,
            "observaciones": f.observaciones,
            "anulada": f.anulada,
            "total": float(f.total),
            "debe": float(f.total) if not f.anulada else 0.0,
            "haber": 0.0,
            "pendiente": _to_float(pendiente if not f.anulada else Decimal(0)),
            "tiene_pagos": n_pagos > 0,
            "cantidad_pagos": n_pagos,
            "ref_id": f.id,
            "ref_tipo": "factura",
        })
    for m in pagos:
        eventos.append({
            "fecha": m.fecha.isoformat(),
            "_fecha_orden": m.fecha,
            "_id_orden": m.id,
            "tipo": "pago",
            "descripcion": f"{m.tipo_operacion}: {m.detalle or ''}",
            "vencimiento": None,
            "debe": 0.0,
            "haber": float(m.monto),
            "ref_id": m.id,
            "ref_tipo": "movimiento",
            "caja": m.caja_origen,
        })

    # Sort estable por (date, tipo, id) — mismo día factura primero, después
    # pagos. Tiebreak por id para orden determinista entre dos del mismo tipo.
    eventos.sort(key=lambda e: (
        e["_fecha_orden"],
        0 if e["tipo"] == "factura" else 1,
        e["_id_orden"],
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
        "id": p.id,
        "nombre": p.nombre,
        "cuit": p.cuit,
        "contacto": p.contacto,
        "saldo_actual": float(saldo),
        "total_debe": total_debe,
        "total_haber": total_haber,
        "eventos": eventos,
    }


def vencimientos_proximos(db: Session, dias_ventana: int = 30) -> list[dict[str, Any]]:
    """Facturas con vencimiento próximo (o ya vencidas) que NO están saldadas."""
    hoy = hoy_ar()
    limite = hoy + timedelta(days=dias_ventana)

    facturas = db.query(FacturaProveedor).filter(
        FacturaProveedor.fecha_vencimiento.isnot(None),
        FacturaProveedor.fecha_vencimiento <= limite,
        FacturaProveedor.anulada == False,  # noqa: E712
    ).order_by(FacturaProveedor.fecha_vencimiento).all()

    pagado_por_factura = dict(
        db.query(
            MovimientoCaja.id_factura_proveedor,
            func.coalesce(func.sum(MovimientoCaja.monto), 0),
        ).filter(
            MovimientoCaja.id_factura_proveedor.isnot(None),
            MovimientoCaja.caja_origen.isnot(None),
            MovimientoCaja.caja_destino.is_(None),
        ).group_by(MovimientoCaja.id_factura_proveedor).all()
    )

    out = []
    for f in facturas:
        pagado = Decimal(str(pagado_por_factura.get(f.id, 0)))
        pendiente = Decimal(str(f.total)) - pagado
        # Tolerancia: ignorar diferencias menores a un centavo (redondeos).
        if pendiente <= TOLERANCIA_CENTAVO:
            continue
        dias_para_vencer = (f.fecha_vencimiento - hoy).days
        out.append({
            "id_factura": f.id,
            "id_proveedor": f.id_proveedor,
            "proveedor": f.proveedor.nombre,
            "numero": f.numero,
            "fecha_emision": f.fecha_emision.isoformat(),
            "fecha_vencimiento": f.fecha_vencimiento.isoformat(),
            "dias_para_vencer": dias_para_vencer,
            "vencida": dias_para_vencer < 0,
            "total": _to_float(_q(Decimal(str(f.total)))),
            "pagado": _to_float(_q(pagado)),
            "pendiente": _to_float(_q(pendiente)),
        })
    return out


def aging_proveedores(
    db: Session, base: str = "vencimiento"
) -> dict[str, Any]:
    """Aging de deuda a proveedores agrupada en buckets temporales.

    Paridad con `aging_cobros` para clientes. `base`:
    - "vencimiento" (default): días = hoy - fecha_vencimiento
    - "emision": días = hoy - fecha_emision
    """
    hoy = hoy_ar()
    cortes = ["bucket_0_30", "bucket_31_60", "bucket_61_90", "bucket_90_mas"]

    facturas = db.query(FacturaProveedor).filter(
        FacturaProveedor.anulada == False,  # noqa: E712
    ).all()

    pagado_por_factura = dict(
        db.query(
            MovimientoCaja.id_factura_proveedor,
            func.coalesce(func.sum(MovimientoCaja.monto), 0),
        ).filter(
            MovimientoCaja.id_factura_proveedor.isnot(None),
            MovimientoCaja.caja_origen.isnot(None),
            MovimientoCaja.caja_destino.is_(None),
        ).group_by(MovimientoCaja.id_factura_proveedor).all()
    )

    por_prov: dict = defaultdict(lambda: {
        "nombre": None, "buckets": defaultdict(Decimal), "total": Decimal(0),
    })

    for f in facturas:
        pendiente = Decimal(str(f.total)) - Decimal(str(pagado_por_factura.get(f.id, 0)))
        if pendiente <= TOLERANCIA_CENTAVO:
            continue
        ref = f.fecha_vencimiento if base == "vencimiento" else f.fecha_emision
        if ref is None:
            ref = f.fecha_emision
        dias = max(0, (hoy - ref).days)
        bucket = (
            "bucket_0_30" if dias <= 30
            else "bucket_31_60" if dias <= 60
            else "bucket_61_90" if dias <= 90
            else "bucket_90_mas"
        )
        info = por_prov[f.id_proveedor]
        info["nombre"] = f.proveedor.nombre
        info["buckets"][bucket] += pendiente
        info["total"] += pendiente

    items = []
    totales = {b: Decimal(0) for b in cortes}
    total_global = Decimal(0)
    for prov_id, info in por_prov.items():
        item = {
            "id_proveedor": prov_id,
            "proveedor": info["nombre"],
            "total": _to_float(_q(info["total"])),
            **{b: _to_float(_q(info["buckets"][b])) for b in cortes},
        }
        items.append(item)
        for b in cortes:
            totales[b] += info["buckets"][b]
        total_global += info["total"]

    items.sort(key=lambda r: r["bucket_90_mas"], reverse=True)

    return {
        "base": base,
        "totales": {**{b: _to_float(_q(v)) for b, v in totales.items()}, "total": _to_float(_q(total_global))},
        "items": items,
    }
