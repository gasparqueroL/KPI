"""Importer de ventas.csv (cabecera de pedidos)."""

from decimal import Decimal

import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import TOLERANCIA_DISCREPANCIA_ARS
from app.importers.base import ImportResult, Rechazo, serializar_fila
from app.importers.cajas_helper import get_or_create_caja
from app.importers.parsing import (
    normalize_str,
    parse_bool,
    parse_datetime_es,
    parse_monto,
)
from app.models.caso_revisar import CasoRevisar
from app.models.venta import Venta

HEADERS_VENTAS = {
    "IdPedido",
    "Fecha",
    "idCliente",
    "cliente",
    "total",
    "idVenta",
}


def es_csv_ventas(headers: set[str]) -> bool:
    return HEADERS_VENTAS.issubset(headers)


def import_ventas(db: Session, df: pd.DataFrame, crear_casos: bool = True) -> ImportResult:
    result = ImportResult(fuente="ventas")
    cache_cajas: dict = {}
    result._crear_casos = crear_casos  # consumido por _rechazar

    existentes_pedido = {r[0] for r in db.query(Venta.id_pedido).all()}
    existentes_venta = {r[0] for r in db.query(Venta.id_venta).all()}

    for idx, row in df.iterrows():
        fila_dict = row.to_dict()
        try:
            id_pedido = normalize_str(row.get("IdPedido"))
            id_venta = normalize_str(row.get("idVenta"))

            if not id_pedido or not id_venta:
                _rechazar(
                    db, result, int(idx), fila_dict,
                    "id_faltante", "IdPedido o idVenta vacíos",
                )
                continue

            if id_pedido in existentes_pedido or id_venta in existentes_venta:
                result.ya_existian += 1
                continue

            fecha = parse_datetime_es(row.get("Fecha"))
            if fecha is None:
                _rechazar(
                    db, result, int(idx), fila_dict,
                    "fecha_invalida", f"Fecha no parseable: {row.get('Fecha')}",
                )
                continue

            total = parse_monto(row.get("total"))
            if total is None:
                _rechazar(
                    db, result, int(idx), fila_dict,
                    "total_invalido", "Total no parseable",
                )
                continue

            forma1 = normalize_str(row.get("formaDePago1"))
            monto1 = parse_monto(row.get("montoPago1"))
            forma2 = normalize_str(row.get("formaDePago2"))
            monto2 = parse_monto(row.get("montoPago2"))

            # Cuenta corriente: FALTA PAGAR puede aparecer en cualquiera de las
            # dos formas de pago (caso split: parte efectivo + parte cta cte).
            es_cta_corriente = (
                forma1.upper() == "FALTA PAGAR"
                or forma2.upper() == "FALTA PAGAR"
            )

            # discrepancia_pago marca cuando lo cobrado difiere significativamente
            # del total facturado. Captura tanto pago > total (vuelto/cobro doble)
            # como pago < total (descuento aplicado al momento). NO se rechaza
            # la fila — solo se flag para que el usuario audite si quiere.
            suma_pagos = (monto1 or Decimal(0)) + (monto2 or Decimal(0))
            tiene_discrepancia = (
                not es_cta_corriente
                and suma_pagos > Decimal(0)
                and abs(suma_pagos - total) > TOLERANCIA_DISCREPANCIA_ARS
            )

            caja1 = caja2 = None
            if forma1 and not es_cta_corriente:
                obj = get_or_create_caja(
                    db, forma1, cache_cajas, result.cajas_creadas
                )
                if obj is not None:
                    caja1 = obj.nombre_normalizado
            if forma2:
                obj = get_or_create_caja(
                    db, forma2, cache_cajas, result.cajas_creadas
                )
                if obj is not None:
                    caja2 = obj.nombre_normalizado

            db.flush()

            id_cliente = None
            raw_cli = row.get("idCliente")
            if pd.notna(raw_cli) and str(raw_cli).strip() != "":
                try:
                    id_cliente = int(float(raw_cli))
                except (ValueError, TypeError):
                    id_cliente = None

            venta = Venta(
                id_pedido=id_pedido,
                id_venta=id_venta,
                fecha=fecha,
                id_cliente=id_cliente,
                cliente=normalize_str(row.get("cliente")) or None,
                vendedor=normalize_str(row.get("vendedor")) or None,
                caja1=caja1,
                monto_pago1=monto1,
                pago_v1=parse_bool(row.get("PAGO V.")),
                caja2=caja2,
                monto_pago2=monto2,
                pago_v2=parse_bool(row.get("PAGO V. 2")),
                total=total,
                comprobante=normalize_str(row.get("comprobanteDePago")) or None,
                helper_v=parse_bool(row.get("helperV")),
                es_cuenta_corriente=es_cta_corriente,
                discrepancia_pago=tiene_discrepancia,
            )
            db.add(venta)
            existentes_pedido.add(id_pedido)
            existentes_venta.add(id_venta)
            result.aceptados += 1

        except Exception as e:
            _rechazar(
                db, result, int(idx), fila_dict, "excepcion", repr(e)
            )

    db.commit()
    return result


def _rechazar(db, result, idx, fila_dict, codigo, descripcion):
    result.rechazados.append(
        Rechazo(fila=idx, motivo=codigo, descripcion=descripcion, datos=fila_dict)
    )
    if getattr(result, "_crear_casos", True):
        db.add(
            CasoRevisar(
                fuente="ventas",
                motivo_codigo=codigo,
                motivo_descripcion=descripcion,
                datos_originales=serializar_fila(fila_dict),
            )
        )
