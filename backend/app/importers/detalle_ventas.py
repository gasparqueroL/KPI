"""Importer de detalle_ventas.csv (productos por pedido)."""

from decimal import Decimal

import pandas as pd
from sqlalchemy.orm import Session

from app.importers.base import ImportResult, Rechazo, serializar_fila
from app.importers.parsing import (
    normalize_str,
    parse_datetime_es,
    parse_monto,
)
from app.models.caso_revisar import CasoRevisar
from app.models.venta import DetalleVenta, Venta


def _norm_dec(d) -> str:
    """Forma canónica para Decimals en hash. Evita que el round-trip
    a SQL Numeric (que agrega ceros: 1 → 1.0000) cambie el hash."""
    if d is None:
        return ""
    return format(Decimal(d).normalize(), "f")

HEADERS_DETALLE = {
    "idVenta",
    "fecha",
    "producto",
    "listaDePrecios",
    "cantidad",
    "precioUnitario",
    "subTotal",
}


def es_csv_detalle(headers: set[str]) -> bool:
    return HEADERS_DETALLE.issubset(headers)


def clasificar_linea(producto: str, precio_unit) -> str:
    """Heurística para tipo de línea. Importante para filtrar KPIs."""
    p = (producto or "").upper()
    if "ENVIO" in p or "ENVÍO" in p:
        return "envio"
    if "BONIFICACION" in p or "BONIFICACIÓN" in p:
        return "bonificacion"
    if precio_unit is not None and precio_unit < 0:
        return "bonificacion"
    return "mercaderia"


def import_detalle_ventas(db: Session, df: pd.DataFrame, crear_casos: bool = True) -> ImportResult:
    result = ImportResult(fuente="detalle_ventas")
    result._crear_casos = crear_casos

    ventas_validas = {r[0] for r in db.query(Venta.id_venta).all()}

    # Identidad lógica de una línea: (id_venta, producto, lista_precios,
    # cantidad_norm, subtotal_norm). Dos líneas con esa 5-tupla son
    # intercambiables a efectos de KPIs y se consideran duplicadas
    # independientemente de su posición original en el CSV.
    # Usamos un dict (clave -> linea_num) en vez de un set de hashes
    # reconstruidos para que el dedupe sea O(1) por fila.
    existentes: dict[tuple, int] = {}
    siguiente_linea: dict[str, int] = {}
    for r in db.query(
        DetalleVenta.id_venta, DetalleVenta.linea_num,
        DetalleVenta.producto, DetalleVenta.lista_precios,
        DetalleVenta.cantidad, DetalleVenta.subtotal,
    ).all():
        clave = (
            r.id_venta, r.producto, r.lista_precios or "",
            _norm_dec(r.cantidad), _norm_dec(r.subtotal),
        )
        existentes[clave] = r.linea_num
        siguiente_linea[r.id_venta] = max(siguiente_linea.get(r.id_venta, 0), r.linea_num + 1)

    pos_actual: dict[str, int] = dict(siguiente_linea)

    for idx, row in df.iterrows():
        fila_dict = row.to_dict()
        try:
            id_venta = normalize_str(row.get("idVenta"))
            if not id_venta:
                _rechazar(db, result, int(idx), fila_dict,
                          "id_venta_faltante", "idVenta vacío")
                continue

            if id_venta not in ventas_validas:
                _rechazar(db, result, int(idx), fila_dict,
                          "venta_inexistente",
                          f"idVenta {id_venta} no existe en ventas")
                continue

            fecha = parse_datetime_es(row.get("fecha"))
            if fecha is None:
                _rechazar(db, result, int(idx), fila_dict,
                          "fecha_invalida", f"fecha no parseable")
                continue

            producto = normalize_str(row.get("producto"))
            if not producto:
                _rechazar(db, result, int(idx), fila_dict,
                          "producto_faltante", "producto vacío")
                continue

            lista_precios = normalize_str(row.get("listaDePrecios")) or None
            cantidad = parse_monto(row.get("cantidad"))
            precio_unit = parse_monto(row.get("precioUnitario"))
            subtotal = parse_monto(row.get("subTotal"))
            descuento = parse_monto(row.get("descuentoUnitario"))
            cst = parse_monto(row.get("CST"))

            if cantidad is None or precio_unit is None or subtotal is None:
                _rechazar(db, result, int(idx), fila_dict,
                          "valores_invalidos",
                          "cantidad/precioUnitario/subTotal no parseables")
                continue

            cantidad_norm = _norm_dec(cantidad)
            subtotal_norm = _norm_dec(subtotal)

            clave = (id_venta, producto, lista_precios or "", cantidad_norm, subtotal_norm)
            if clave in existentes:
                result.ya_existian += 1
                continue

            n_nueva = pos_actual.get(id_venta, 0)
            existentes[clave] = n_nueva
            pos_actual[id_venta] = n_nueva + 1

            categoria = clasificar_linea(producto, precio_unit)

            db.add(DetalleVenta(
                id_venta=id_venta,
                fecha=fecha,
                producto=producto,
                lista_precios=lista_precios,
                cantidad=cantidad,
                precio_unitario=precio_unit,
                subtotal=subtotal,
                descuento_unitario=descuento,
                cst=cst,
                categoria_linea=categoria,
                linea_num=n_nueva,
            ))
            result.aceptados += 1

        except Exception as e:
            _rechazar(db, result, int(idx), fila_dict, "excepcion", repr(e))

    db.commit()
    return result


def _rechazar(db, result, idx, fila_dict, codigo, descripcion):
    result.rechazados.append(
        Rechazo(fila=idx, motivo=codigo, descripcion=descripcion, datos=fila_dict)
    )
    if getattr(result, "_crear_casos", True):
        db.add(CasoRevisar(
            fuente="detalle_ventas",
            motivo_codigo=codigo,
            motivo_descripcion=descripcion,
            datos_originales=serializar_fila(fila_dict),
        ))
