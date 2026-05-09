"""Conciliación: cuánto se facturó vs cuánto realmente entró a las cajas.

El "ingreso real comercial" = lo cobrado al hacer la venta + cobranzas
posteriores de cuentas corrientes. Los "otros ingresos" (devolución de
adelantos, etc.) se reportan separados porque NO son operación comercial.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.kpis.comerciales import _filtro_fecha
from app.models.categoria_caja import CategoriaCaja
from app.models.movimiento_caja import MovimientoCaja
from app.models.venta import Venta


def _to_float(v) -> float:
    return float(v) if v is not None else 0.0


def conciliacion(
    db: Session,
    desde: date | None = None,
    hasta: date | None = None,
) -> dict[str, Any]:
    # 1. Facturado en período (suma de Venta.total)
    fact_q = db.query(func.coalesce(func.sum(Venta.total), 0))
    fact_q = _filtro_fecha(fact_q, Venta.fecha, desde, hasta)
    facturado = Decimal(str(fact_q.scalar() or 0))

    # 2. Cobrado en cajas en momento de venta (monto_pago1 + monto_pago2)
    cobrado_q = db.query(
        func.coalesce(func.sum(
            func.coalesce(Venta.monto_pago1, 0) + func.coalesce(Venta.monto_pago2, 0)
        ), 0)
    )
    cobrado_q = _filtro_fecha(cobrado_q, Venta.fecha, desde, hasta)
    cobrado_en_caja = Decimal(str(cobrado_q.scalar() or 0))

    # 3. Cobranzas operativas (ingresos a caja por cobranza de cta cte)
    cobr_q = db.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)).join(
        CategoriaCaja, CategoriaCaja.tipo_operacion == MovimientoCaja.tipo_operacion
    ).filter(
        CategoriaCaja.es_ingreso_operativo == True,
        MovimientoCaja.caja_destino.isnot(None),
        MovimientoCaja.caja_origen.is_(None),
    )
    cobr_q = _filtro_fecha(cobr_q, MovimientoCaja.fecha, desde, hasta)
    cobranzas_cta_cte = Decimal(str(cobr_q.scalar() or 0))

    # 4. Otros ingresos a caja (NO operativos)
    otros_q = db.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)).outerjoin(
        CategoriaCaja, CategoriaCaja.tipo_operacion == MovimientoCaja.tipo_operacion
    ).filter(
        MovimientoCaja.caja_destino.isnot(None),
        MovimientoCaja.caja_origen.is_(None),
        # Excluir los que son ingreso operativo
        (CategoriaCaja.es_ingreso_operativo == False) | (CategoriaCaja.es_ingreso_operativo.is_(None)),
    )
    otros_q = _filtro_fecha(otros_q, MovimientoCaja.fecha, desde, hasta)
    otros_ingresos = Decimal(str(otros_q.scalar() or 0))

    # 5. Métricas derivadas
    ingreso_operativo = cobrado_en_caja + cobranzas_cta_cte
    diferencia = facturado - ingreso_operativo
    cobertura_pct = (ingreso_operativo / facturado * 100) if facturado else Decimal(0)

    # 6. Conteos auxiliares: ventas en cuenta corriente nueva + discrepancias
    cta_cte_q = db.query(func.count(), func.coalesce(func.sum(Venta.total), 0)).filter(
        Venta.es_cuenta_corriente == True
    )
    cta_cte_q = _filtro_fecha(cta_cte_q, Venta.fecha, desde, hasta)
    cta_cte_n, cta_cte_total = cta_cte_q.one()

    disc_q = db.query(
        func.count(),
        func.coalesce(func.sum(
            Venta.total - func.coalesce(Venta.monto_pago1, 0) - func.coalesce(Venta.monto_pago2, 0)
        ), 0)
    ).filter(Venta.discrepancia_pago == True)
    disc_q = _filtro_fecha(disc_q, Venta.fecha, desde, hasta)
    disc_n, disc_total_dif = disc_q.one()

    # 7. Ventas SIN cobro (monto_pago1+2 == 0/null) que NO son cta cte.
    # Estas son las que probablemente explican el grueso del gap de cobertura.
    sin_cobro_q = db.query(
        func.count(),
        func.coalesce(func.sum(Venta.total), 0),
    ).filter(
        Venta.es_cuenta_corriente == False,
        (func.coalesce(Venta.monto_pago1, 0) + func.coalesce(Venta.monto_pago2, 0)) == 0,
        Venta.total > 0,
    )
    sin_cobro_q = _filtro_fecha(sin_cobro_q, Venta.fecha, desde, hasta)
    sin_cobro_n, sin_cobro_total = sin_cobro_q.one()

    return {
        "desde": desde.isoformat() if desde else None,
        "hasta": hasta.isoformat() if hasta else None,
        "facturado": _to_float(facturado),
        "cobrado_en_caja": _to_float(cobrado_en_caja),
        "cobranzas_cta_cte": _to_float(cobranzas_cta_cte),
        "ingreso_operativo": _to_float(ingreso_operativo),
        "otros_ingresos_movimientos": _to_float(otros_ingresos),
        "ingreso_real_total": _to_float(ingreso_operativo + otros_ingresos),
        "diferencia_facturado_vs_operativo": _to_float(diferencia),
        "cobertura_pct": _to_float(cobertura_pct),
        "ventas_cta_cte": {
            "cantidad": cta_cte_n or 0,
            "monto_total": _to_float(cta_cte_total),
        },
        "ventas_con_discrepancia": {
            "cantidad": disc_n or 0,
            "diferencia_total": _to_float(disc_total_dif),
        },
        "ventas_sin_cobro": {
            "cantidad": sin_cobro_n or 0,
            "monto_total": _to_float(sin_cobro_total),
        },
    }


def lista_sin_cobro(
    db: Session,
    desde: date | None = None,
    hasta: date | None = None,
    limite: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Ventas sin cobro registrado y que NO son cuenta corriente.
    Probable causa principal del gap de cobertura."""
    base = db.query(Venta).filter(
        Venta.es_cuenta_corriente == False,
        (func.coalesce(Venta.monto_pago1, 0) + func.coalesce(Venta.monto_pago2, 0)) == 0,
        Venta.total > 0,
    )
    base = _filtro_fecha(base, Venta.fecha, desde, hasta)

    # Una sola query agregada para count + sum (evita materializar todas las filas)
    total, monto = base.with_entities(
        func.count(),
        func.coalesce(func.sum(Venta.total), 0),
    ).one()
    monto = float(monto or 0)

    rows = base.order_by(Venta.fecha.desc()).offset(offset).limit(limite).all()
    return {
        "total": total,
        "monto_total": monto,
        "limite": limite,
        "offset": offset,
        "items": [
            {
                "id_pedido": v.id_pedido,
                "fecha": v.fecha.isoformat(),
                "cliente": v.cliente,
                "vendedor": v.vendedor,
                "total": float(v.total),
                "caja1": v.caja1,
                "caja2": v.caja2,
            }
            for v in rows
        ],
    }


def lista_discrepancias(
    db: Session,
    desde: date | None = None,
    hasta: date | None = None,
    limite: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Ventas con `discrepancia_pago=True` ordenadas por magnitud."""
    q = db.query(Venta).filter(Venta.discrepancia_pago == True)
    q = _filtro_fecha(q, Venta.fecha, desde, hasta)
    total = q.count()

    rows = q.order_by(Venta.fecha.desc()).offset(offset).limit(limite).all()
    items = []
    for v in rows:
        m1 = float(v.monto_pago1 or 0)
        m2 = float(v.monto_pago2 or 0)
        suma = m1 + m2
        items.append({
            "id_pedido": v.id_pedido,
            "fecha": v.fecha.isoformat(),
            "cliente": v.cliente,
            "vendedor": v.vendedor,
            "total": float(v.total),
            "monto_pago1": m1 or None,
            "caja1": v.caja1,
            "monto_pago2": m2 or None,
            "caja2": v.caja2,
            "suma_pagos": suma,
            "diferencia": float(v.total) - suma,
        })
    return {"total": total, "limite": limite, "offset": offset, "items": items}


def cuentas_corrientes_emitidas(
    db: Session,
    desde: date | None = None,
    hasta: date | None = None,
    limite: int = 100,
) -> dict[str, Any]:
    """Ventas EMITIDAS marcadas como cuenta corriente en el período.
    Esto NO descuenta cobranzas posteriores — para saldos netos por cliente
    usar `/api/cuentas-corrientes/clientes`. El nombre del endpoint reconoce
    que devuelve emisiones, no saldos abiertos.
    """
    base = db.query(Venta).filter(Venta.es_cuenta_corriente == True)
    base = _filtro_fecha(base, Venta.fecha, desde, hasta)

    # Una sola query agregada
    total, monto = base.with_entities(
        func.count(),
        func.coalesce(func.sum(Venta.total), 0),
    ).one()

    rows = base.order_by(Venta.fecha.desc()).limit(limite).all()
    return {
        "total_cantidad": total,
        "total_monto": float(monto or 0),
        "items": [
            {
                "id_pedido": v.id_pedido,
                "fecha": v.fecha.isoformat(),
                "cliente": v.cliente,
                "vendedor": v.vendedor,
                "total": float(v.total),
            }
            for v in rows
        ],
    }


# Alias por compatibilidad con código viejo (deprecated, usar la nueva)
def cuentas_corrientes_abiertas(*args, **kwargs):
    return cuentas_corrientes_emitidas(*args, **kwargs)
