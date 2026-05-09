"""Lógica de aplicación de pagos a ventas (pagos parciales / sobrepagos)."""

from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.movimiento_caja import MovimientoCaja
from app.models.pago_aplicado import PagoAplicado
from app.models.venta import Venta


def saldo_venta(db: Session, id_pedido: str) -> Decimal | None:
    """Total de la venta - sum(pagos aplicados a esa venta).

    Devuelve None si la venta no existe — para que el caller distinga
    "venta inexistente" (404) de "venta cobrada totalmente" (Decimal(0)).
    """
    v = db.get(Venta, id_pedido)
    if v is None:
        return None
    aplicado = db.query(func.coalesce(func.sum(PagoAplicado.monto), 0)).filter(
        PagoAplicado.id_venta == id_pedido
    ).scalar()
    return Decimal(str(v.total)) - Decimal(str(aplicado or 0))


def disponible_movimiento(db: Session, id_movimiento: int) -> Decimal | None:
    """Monto del movimiento de cobranza (ingreso puro) - sum(pagos aplicados).

    Devuelve None si el movimiento no existe O no es un ingreso puro
    (transferencia, egreso). Permite al caller distinguir "no aplicable"
    de "totalmente aplicado".
    """
    m = db.get(MovimientoCaja, id_movimiento)
    if m is None or m.caja_destino is None or m.caja_origen is not None:
        return None
    aplicado = db.query(func.coalesce(func.sum(PagoAplicado.monto), 0)).filter(
        PagoAplicado.id_movimiento == id_movimiento
    ).scalar()
    return Decimal(str(m.monto)) - Decimal(str(aplicado or 0))


def aplicar_pago(
    db: Session,
    id_pedido: str,
    id_movimiento: int,
    monto: Decimal | None = None,
) -> PagoAplicado:
    """Aplica `monto` (o todo el disponible si None) del movimiento a la venta."""
    # Lock pessimista sobre la venta TAMBIÉN: dos requests simultáneas
    # contra la misma venta podrían ambas pasar el chequeo `saldo > 0` y
    # crear aplicaciones que sumadas exceden `Venta.total`. Lockear
    # ambas filas (orden estable: venta primero por PK string) evita
    # deadlocks y serializa el acceso. No-op en SQLite (que serializa
    # commits a nivel DB), real en Postgres.
    v = db.query(Venta).filter(
        Venta.id_pedido == id_pedido
    ).with_for_update().first()
    if v is None:
        raise ValueError(f"Venta {id_pedido} no existe")
    m = db.query(MovimientoCaja).filter(
        MovimientoCaja.id == id_movimiento
    ).with_for_update().first()
    if m is None:
        raise ValueError(f"Movimiento {id_movimiento} no existe")
    if m.caja_destino is None or m.caja_origen is not None:
        raise ValueError(
            "El movimiento debe ser un ingreso puro (caja_destino sin caja_origen). "
            "Las transferencias entre cajas no son cobranzas."
        )

    saldo = saldo_venta(db, id_pedido)
    disp = disponible_movimiento(db, id_movimiento)

    if saldo is None or saldo <= 0:
        raise ValueError("La venta ya está totalmente cobrada")
    if disp is None or disp <= 0:
        raise ValueError("El movimiento no tiene saldo disponible")

    monto_a_aplicar = Decimal(str(monto)) if monto is not None else min(saldo, disp)
    if monto_a_aplicar <= 0:
        raise ValueError("Monto a aplicar debe ser > 0")
    if monto_a_aplicar > disp:
        raise ValueError(f"Monto {monto_a_aplicar} excede disponible del movimiento ({disp})")

    # ¿Ya hay una aplicación entre este venta+movimiento? Sumar al existente.
    existente = db.query(PagoAplicado).filter(
        PagoAplicado.id_venta == id_pedido,
        PagoAplicado.id_movimiento == id_movimiento,
    ).first()
    if existente is not None:
        nuevo_total = Decimal(str(existente.monto)) + monto_a_aplicar
        if nuevo_total > Decimal(str(m.monto)):
            raise ValueError("La suma excede el monto del movimiento")
        existente.monto = nuevo_total
        db.commit()
        return existente

    p = PagoAplicado(id_venta=id_pedido, id_movimiento=id_movimiento, monto=monto_a_aplicar)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def desaplicar_pago(db: Session, id_pago_aplicado: int) -> dict[str, Any]:
    """Borra una aplicación. Devuelve los ids afectados para que el
    caller pueda invalidar las queries correctas sin un round-trip."""
    p = db.get(PagoAplicado, id_pago_aplicado)
    if p is None:
        raise ValueError("Pago aplicado no existe")
    res = {"id_venta": p.id_venta, "id_movimiento": p.id_movimiento}
    db.delete(p)
    db.commit()
    return res


def aplicaciones_de_venta(db: Session, id_pedido: str) -> list[dict[str, Any]]:
    """Lista los pagos aplicados a una venta con detalle del movimiento."""
    rows = db.query(PagoAplicado, MovimientoCaja).join(
        MovimientoCaja, MovimientoCaja.id == PagoAplicado.id_movimiento
    ).filter(PagoAplicado.id_venta == id_pedido).order_by(MovimientoCaja.fecha).all()
    return [
        {
            "id_pago_aplicado": p.id,
            "id_movimiento": m.id,
            "fecha_pago": m.fecha.isoformat(),
            "tipo_operacion": m.tipo_operacion,
            "detalle": m.detalle,
            "caja_destino": m.caja_destino,
            "monto_aplicado": float(p.monto),
            "monto_total_movimiento": float(m.monto),
        }
        for p, m in rows
    ]


def aplicaciones_de_movimiento(db: Session, id_movimiento: int) -> list[dict[str, Any]]:
    """Lista las ventas que cubre un movimiento (con cuánto a cada una)."""
    rows = db.query(PagoAplicado, Venta).join(
        Venta, Venta.id_pedido == PagoAplicado.id_venta
    ).filter(PagoAplicado.id_movimiento == id_movimiento).order_by(Venta.fecha).all()
    return [
        {
            "id_pago_aplicado": p.id,
            "id_pedido": v.id_pedido,
            "fecha_venta": v.fecha.isoformat(),
            "cliente": v.cliente,
            "total_venta": float(v.total),
            "monto_aplicado": float(p.monto),
        }
        for p, v in rows
    ]
