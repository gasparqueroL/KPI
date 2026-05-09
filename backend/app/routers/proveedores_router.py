"""Endpoints de proveedores y cuentas a pagar."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.kpis import proveedores as kpi_prov
from app.models.movimiento_caja import MovimientoCaja
from app.models.proveedor import FacturaProveedor, Proveedor
from app.routers._cache_helpers import invalida_alertas
from app.routers._pdf_extracto import render_aging_pdf, render_extracto_pdf, slug_filename

router = APIRouter(prefix="/api/proveedores", tags=["proveedores"])


@router.get("")
def listar(
    incluir_inactivos: bool = Query(False),
    db: Session = Depends(get_db),
):
    return kpi_prov.proveedores_con_saldo(db, incluir_inactivos=incluir_inactivos)


@router.get("/vencimientos-proximos")
def vencimientos(
    dias: int = Query(30, ge=0, le=365, description="0 = solo vencidas o que vencen hoy"),
    db: Session = Depends(get_db),
):
    return kpi_prov.vencimientos_proximos(db, dias_ventana=dias)


@router.get("/aging")
def aging(
    base: str = Query("vencimiento", pattern="^(vencimiento|emision)$"),
    db: Session = Depends(get_db),
):
    return kpi_prov.aging_proveedores(db, base=base)


@router.get("/aging.pdf")
def aging_pdf(
    base: str = Query("vencimiento", pattern="^(vencimiento|emision)$"),
    db: Session = Depends(get_db),
):
    """PDF imprimible del aging de proveedores con saldo pendiente."""
    data = kpi_prov.aging_proveedores(db, base=base)
    items = [
        {
            "nombre": it.get("proveedor") or f"(ID {it['id_proveedor']})",
            "bucket_0_30": it["bucket_0_30"],
            "bucket_31_60": it["bucket_31_60"],
            "bucket_61_90": it["bucket_61_90"],
            "bucket_90_mas": it["bucket_90_mas"],
            "total": it["total"],
        }
        for it in data["items"]
    ]
    sufijo = "vencimiento" if base == "vencimiento" else "emision"
    pdf = render_aging_pdf(
        titulo=f"Aging de cuentas a pagar (base: {sufijo})",
        items=items,
        totales=data["totales"],
        nombre_columna="Proveedor",
    )
    hoy = date.today().isoformat()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="aging_proveedores_{sufijo}_{hoy}.pdf"'},
    )


@router.get("/movimientos-sin-asignar")
def movimientos_sin_asignar(
    busqueda: str | None = Query(None),
    limite: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Egresos sin vincular a ninguna factura."""
    q = db.query(MovimientoCaja).filter(
        MovimientoCaja.caja_origen.isnot(None),
        MovimientoCaja.id_factura_proveedor.is_(None),
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
            "caja_origen": m.caja_origen,
        }
        for m in q.all()
    ]


@router.get("/{id_proveedor}/ledger")
def ledger(id_proveedor: int, db: Session = Depends(get_db)):
    data = kpi_prov.ledger_proveedor(db, id_proveedor)
    # `ledger_proveedor` devuelve dict con `nombre="(no encontrado)"` cuando
    # el proveedor no existe (mantenido por retro-compat con `/extracto.pdf`
    # que ya chequea esa marca). Acá lo convertimos en 404 real para que
    # el frontend pueda manejar el caso (deep link a proveedor borrado, etc).
    if data.get("nombre") == "(no encontrado)":
        raise HTTPException(404, "Proveedor no encontrado")
    return data


@router.get("/{id_proveedor}/extracto.pdf")
def extracto_pdf(id_proveedor: int, db: Session = Depends(get_db)):
    """Descarga el extracto del proveedor como PDF."""
    data = kpi_prov.ledger_proveedor(db, id_proveedor)
    if data.get("nombre") == "(no encontrado)":
        raise HTTPException(404, "Proveedor no encontrado")
    pdf = render_extracto_pdf(
        titulo="Extracto de cuenta de proveedor",
        entidad={
            "id": data["id"],
            "nombre": data["nombre"],
            "cuit": data.get("cuit"),
            "contacto": data.get("contacto"),
        },
        totales={
            "saldo_actual": data["saldo_actual"],
            "total_debe": data["total_debe"],
            "total_haber": data["total_haber"],
        },
        eventos=data["eventos"],
    )
    nombre_safe = slug_filename(data["nombre"], f"proveedor_{id_proveedor}")
    hoy = date.today().isoformat()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="extracto_{nombre_safe}_{hoy}.pdf"'},
    )


class NuevoProveedor(BaseModel):
    nombre: str
    cuit: str | None = None
    contacto: str | None = None


@router.post("")
@invalida_alertas
def crear_proveedor(data: NuevoProveedor, db: Session = Depends(get_db)):
    if not data.nombre.strip():
        raise HTTPException(400, "Nombre es obligatorio")
    p = Proveedor(
        nombre=data.nombre.strip(),
        cuit=(data.cuit or "").strip() or None,
        contacto=(data.contacto or "").strip() or None,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"ok": True, "id": p.id}


class EditarProveedor(BaseModel):
    nombre: str | None = None
    cuit: str | None = None
    contacto: str | None = None
    activo: bool | None = None


@router.patch("/{id_proveedor}")
@invalida_alertas
def editar_proveedor(id_proveedor: int, data: EditarProveedor, db: Session = Depends(get_db)):
    p = db.get(Proveedor, id_proveedor)
    if p is None:
        raise HTTPException(404, "Proveedor no encontrado")
    if data.nombre is not None:
        p.nombre = data.nombre.strip() or p.nombre
    if data.cuit is not None:
        p.cuit = data.cuit.strip() or None
    if data.contacto is not None:
        p.contacto = data.contacto.strip() or None
    if data.activo is not None:
        p.activo = data.activo
    db.commit()
    return {"ok": True}


class NuevaFactura(BaseModel):
    id_proveedor: int
    numero: str | None = None
    fecha_emision: date
    fecha_vencimiento: date | None = None
    total: float
    descripcion: str | None = None
    observaciones: str | None = None


@router.post("/factura")
@invalida_alertas
def crear_factura(data: NuevaFactura, db: Session = Depends(get_db)):
    if data.total <= 0:
        raise HTTPException(400, "total debe ser > 0")
    if db.get(Proveedor, data.id_proveedor) is None:
        raise HTTPException(404, "Proveedor no encontrado")
    f = FacturaProveedor(
        id_proveedor=data.id_proveedor,
        numero=(data.numero or "").strip() or None,
        fecha_emision=data.fecha_emision,
        fecha_vencimiento=data.fecha_vencimiento,
        total=Decimal(str(data.total)),
        descripcion=(data.descripcion or "").strip() or None,
        observaciones=(data.observaciones or "").strip() or None,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return {"ok": True, "id": f.id}


class EditarFactura(BaseModel):
    numero: str | None = None
    fecha_emision: date | None = None
    fecha_vencimiento: date | None = None
    total: float | None = None
    descripcion: str | None = None
    observaciones: str | None = None


@router.patch("/factura/{id_factura}")
@invalida_alertas
def editar_factura(id_factura: int, data: EditarFactura, db: Session = Depends(get_db)):
    """Edita campos de la factura.

    Semántica del payload (RFC 7396 / JSON Merge Patch — decidida con jurado
    adversarial conservador+pragmático, ambos convergen):
    - **Campo ausente** del JSON → no se toca.
    - **Campo con valor** → se setea a ese valor.
    - **Campo `null` explícito** → se limpia (NULL en DB).

    Distinción implementada con `model_fields_set` de Pydantic v2.

    `total` solo se permite cambiar si la factura NO tiene pagos vinculados
    (cambiarlo invalidaría conciliaciones previas). El resto de los campos
    son metadata segura de editar.
    """
    f = db.get(FacturaProveedor, id_factura)
    if f is None:
        raise HTTPException(404, "Factura no encontrada")
    if f.anulada:
        raise HTTPException(409, "La factura está anulada, no se puede editar")

    enviado = data.model_fields_set

    # ── PASO 1: validar TODO antes de mutar nada ─────────────────────────
    # Si validamos y mutamos en la misma pasada, un payload con varios
    # `null` inválidos dejaría cambios parciales en memoria sobre `f` antes
    # del raise. Hoy no rompe (sin commit, SQLAlchemy descarta), pero un
    # flush futuro podría filtrarlos. Mejor blindar el orden ahora.
    if "fecha_emision" in enviado and data.fecha_emision is None:
        raise HTTPException(400, "fecha_emision no puede ser null")
    if "total" in enviado:
        if data.total is None:
            raise HTTPException(400, "total no puede ser null")
        if data.total <= 0:
            raise HTTPException(400, "total debe ser > 0")
        n_pagos = db.query(MovimientoCaja).filter(
            MovimientoCaja.id_factura_proveedor == id_factura
        ).count()
        if n_pagos > 0:
            raise HTTPException(
                409,
                f"La factura tiene {n_pagos} pagos vinculados. Para cambiar el "
                "total, primero desvinculá los pagos (o anulá esta factura y "
                "creá una nueva con el monto correcto).",
            )

    # ── PASO 2: aplicar mutaciones (todas las validaciones ya pasaron) ───
    if "numero" in enviado:
        f.numero = _strip_o_null(data.numero)
    if "fecha_emision" in enviado:
        f.fecha_emision = data.fecha_emision
    if "fecha_vencimiento" in enviado:
        f.fecha_vencimiento = data.fecha_vencimiento  # puede ser None: limpia
    if "descripcion" in enviado:
        f.descripcion = _strip_o_null(data.descripcion)
    if "observaciones" in enviado:
        f.observaciones = _strip_o_null(data.observaciones)
    if "total" in enviado:
        f.total = Decimal(str(data.total))
    db.commit()
    return {"ok": True}


def _strip_o_null(valor: str | None) -> str | None:
    """Helper: `None` se mantiene `None` (limpia el campo); string se
    .strip() y vuelve `None` si quedó vacío. Usado para campos opcionales
    de texto donde "" se trata como ausencia de valor."""
    if valor is None:
        return None
    s = valor.strip()
    return s or None


@router.delete("/factura/{id_factura}")
@invalida_alertas
def eliminar_factura(id_factura: int, db: Session = Depends(get_db)):
    f = db.get(FacturaProveedor, id_factura)
    if f is None:
        raise HTTPException(404, "Factura no encontrada")
    n_pagos = db.query(MovimientoCaja).filter(
        MovimientoCaja.id_factura_proveedor == id_factura
    ).count()
    if n_pagos > 0:
        raise HTTPException(
            409,
            f"La factura tiene {n_pagos} pagos vinculados. Desvinculá primero "
            "esos movimientos antes de borrar — o anulala si querés conservar histórico."
        )
    db.delete(f)
    db.commit()
    return {"ok": True}


class AnularFactura(BaseModel):
    motivo: str | None = None


@router.post("/factura/{id_factura}/anular")
@invalida_alertas
def anular_factura(id_factura: int, data: AnularFactura, db: Session = Depends(get_db)):
    """Soft-delete: marca la factura como anulada (se excluye de saldo,
    aging y vencimientos) sin perder histórico ni romper FK de pagos.

    Trazabilidad: cada movimiento desvinculado recibe una marca en `detalle`
    con el id de factura previa y la fecha de anulación, para poder
    reconstruir manualmente el vínculo si más adelante se decide reabrir
    la factura. Sin esto, los pagos vuelven a "egresos sin asignar"
    silenciosamente y la información se pierde.
    """
    f = db.get(FacturaProveedor, id_factura)
    if f is None:
        raise HTTPException(404, "Factura no encontrada")
    if f.anulada:
        raise HTTPException(409, "La factura ya está anulada")
    f.anulada = True
    if data.motivo:
        marca = f"[ANULADA: {data.motivo}]"
        f.observaciones = f"{f.observaciones} {marca}".strip() if f.observaciones else marca
    # Desvincular pagos asociados para que vuelvan a "egresos sin asignar",
    # dejando traza en el detalle del movimiento. Idempotente: si la marca
    # ya está (anular → reabrir externamente → anular de nuevo), no se
    # duplica para no inflar el campo `detalle` indefinidamente.
    pagos_vinculados = db.query(MovimientoCaja).filter(
        MovimientoCaja.id_factura_proveedor == id_factura
    ).all()
    fecha_anulacion = date.today().isoformat()
    marca_traza = f"[ex-factura #{id_factura}, anulada {fecha_anulacion}]"
    for m in pagos_vinculados:
        if m.detalle and marca_traza in m.detalle:
            pass  # ya tiene la marca, no concatenar
        elif m.detalle:
            m.detalle = f"{m.detalle} {marca_traza}".strip()
        else:
            m.detalle = marca_traza
        m.id_factura_proveedor = None
    db.commit()
    return {"ok": True, "pagos_desvinculados": len(pagos_vinculados)}


class VincularPago(BaseModel):
    id_factura: int
    # Opcional: si el caller sabe a qué proveedor "pertenece" la operación,
    # lo pasamos acá y se valida que la factura sea efectivamente de ese
    # proveedor. Previene cross-tenant accidental: el frontend siempre lo
    # envía desde DetalleProveedor.
    id_proveedor: int | None = None


@router.post("/movimiento/{movimiento_id}/vincular")
@invalida_alertas
def vincular_movimiento(movimiento_id: int, data: VincularPago, db: Session = Depends(get_db)):
    m = db.get(MovimientoCaja, movimiento_id)
    if m is None:
        raise HTTPException(404, "Movimiento no encontrado")
    if m.caja_origen is None or m.caja_destino is not None:
        raise HTTPException(
            400,
            "Solo se pueden vincular EGRESOS PUROS (con caja_origen, sin caja_destino). "
            "Las transferencias entre cajas no son pagos a proveedor.",
        )
    factura = db.get(FacturaProveedor, data.id_factura)
    if factura is None:
        raise HTTPException(404, "Factura no encontrada")
    if data.id_proveedor is not None and factura.id_proveedor != data.id_proveedor:
        raise HTTPException(
            400,
            f"La factura {data.id_factura} pertenece al proveedor "
            f"{factura.id_proveedor}, no al {data.id_proveedor}.",
        )
    m.id_factura_proveedor = data.id_factura
    db.commit()
    return {"ok": True, "id_proveedor": factura.id_proveedor}


@router.post("/movimiento/{movimiento_id}/desvincular")
@invalida_alertas
def desvincular_movimiento(movimiento_id: int, db: Session = Depends(get_db)):
    m = db.get(MovimientoCaja, movimiento_id)
    if m is None:
        raise HTTPException(404, "Movimiento no encontrado")
    m.id_factura_proveedor = None
    db.commit()
    return {"ok": True}
