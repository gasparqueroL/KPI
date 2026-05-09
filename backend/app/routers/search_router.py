"""Búsqueda global unificada — alimenta el modal Cmd-K del frontend.

Busca substring case-insensitive en 4 entidades:
- Clientes (Venta.cliente agrupado por id_cliente)
- Proveedores
- Facturas de proveedor (numero o descripcion)
- Movimientos de caja (detalle, recientes primero)

Cada resultado devuelve `tipo`, `label`, `sub` (subtítulo opcional con
contexto) y `link` para que el frontend navegue al hacer click.
"""
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.movimiento_caja import MovimientoCaja
from app.models.proveedor import FacturaProveedor, Proveedor
from app.models.venta import Venta

router = APIRouter(prefix="/api/search", tags=["search"])

# Cap por entidad: si la dueña escribe "S", no inundamos con todos los
# clientes que tengan S — top N por relevancia (recencia o saldo).
MAX_POR_ENTIDAD = 8


@router.get("")
def buscar(
    q: str = Query(..., min_length=1, max_length=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Búsqueda unificada. `q` es substring case-insensitive."""
    patron = f"%{q.strip()}%"
    resultados: list[dict] = []

    # Clientes — agrupados por id_cliente para no devolver una entrada por venta.
    clientes = (
        db.query(
            Venta.id_cliente,
            func.max(Venta.cliente).label("cliente"),
            func.count(Venta.id_pedido).label("pedidos"),
        )
        .filter(
            Venta.id_cliente.isnot(None),
            Venta.cliente.ilike(patron),
        )
        .group_by(Venta.id_cliente)
        .order_by(func.count(Venta.id_pedido).desc())
        .limit(MAX_POR_ENTIDAD)
        .all()
    )
    for c in clientes:
        resultados.append({
            "tipo": "cliente",
            "label": c.cliente,
            "sub": f"ID {c.id_cliente} · {c.pedidos} pedidos",
            # Deep link: la página lee el param y abre el detalle directo,
            # en vez de aterrizar en la lista y obligar a la dueña a buscar.
            "link": f"/cuentas-corrientes?cliente={c.id_cliente}",
            "id": c.id_cliente,
        })

    # Proveedores — por nombre o cuit.
    provs = (
        db.query(Proveedor)
        .filter(or_(
            Proveedor.nombre.ilike(patron),
            Proveedor.cuit.ilike(patron),
        ))
        .order_by(Proveedor.nombre)
        .limit(MAX_POR_ENTIDAD)
        .all()
    )
    for p in provs:
        sub_parts = []
        if p.cuit:
            sub_parts.append(f"CUIT {p.cuit}")
        if not p.activo:
            sub_parts.append("inactivo")
        resultados.append({
            "tipo": "proveedor",
            "label": p.nombre,
            "sub": " · ".join(sub_parts) or "proveedor",
            "link": f"/proveedores?proveedor={p.id}",
            "id": p.id,
        })

    # Facturas — por numero o descripcion. Excluye anuladas.
    facts = (
        db.query(FacturaProveedor, Proveedor.nombre)
        .join(Proveedor, Proveedor.id == FacturaProveedor.id_proveedor)
        .filter(
            FacturaProveedor.anulada == False,  # noqa: E712
            or_(
                FacturaProveedor.numero.ilike(patron),
                FacturaProveedor.descripcion.ilike(patron),
            ),
        )
        .order_by(FacturaProveedor.fecha_emision.desc())
        .limit(MAX_POR_ENTIDAD)
        .all()
    )
    for f, prov_nombre in facts:
        resultados.append({
            "tipo": "factura",
            "label": f"Factura {f.numero or '(sin nro)'} · {prov_nombre}",
            "sub": f"{f.fecha_emision.isoformat()} · ${float(f.total):,.0f}".replace(",", "."),
            # La factura no tiene página propia, así que llevamos al detalle
            # del proveedor con el id de factura como param: el frontend
            # hace scrollIntoView + highlight de la fila correspondiente.
            "link": f"/proveedores?proveedor={f.id_proveedor}&factura={f.id}",
            "id": f.id,
        })

    # Movimientos — busca en detalle y tipo_operacion. Recientes primero.
    movs = (
        db.query(MovimientoCaja)
        .filter(or_(
            MovimientoCaja.detalle.ilike(patron),
            MovimientoCaja.tipo_operacion.ilike(patron),
        ))
        .order_by(desc(MovimientoCaja.fecha), desc(MovimientoCaja.id))
        .limit(MAX_POR_ENTIDAD)
        .all()
    )
    for m in movs:
        ruta = " → ".join(filter(None, [m.caja_origen, m.caja_destino])) or "-"
        resultados.append({
            "tipo": "movimiento",
            "label": f"{m.tipo_operacion}: {(m.detalle or '')[:60]}",
            "sub": f"{m.fecha.isoformat()} · ${float(m.monto):,.0f}".replace(",", ".") + f" · {ruta}",
            "link": "/caja-diaria",
            "id": m.id,
        })

    return {"q": q, "total": len(resultados), "resultados": resultados}
