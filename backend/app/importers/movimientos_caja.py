"""Importer de movimientos_caja.csv."""

from decimal import Decimal

import pandas as pd
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.importers.base import ImportResult, Rechazo, hash_row, serializar_fila
from app.importers.cajas_helper import get_or_create_caja, get_or_create_categoria
from app.importers.parsing import (
    normalize_str,
    parse_date_es,
    parse_monto,
)
from app.models.caja import Caja
from app.models.caso_revisar import CasoRevisar
from app.models.movimiento_caja import MovimientoCaja

HEADERS_CAJA = {
    "FECHA",
    "Tipo de Operación",
    "DETALLE DEL GASTO",
    "MONTO",
    "SALIDAS",
    "ENTRADAS",
}


def es_csv_caja(headers: set[str]) -> bool:
    return HEADERS_CAJA.issubset(headers)


def import_movimientos_caja(db: Session, df: pd.DataFrame, crear_casos: bool = True) -> ImportResult:
    result = ImportResult(fuente="movimientos_caja")
    result._crear_casos = crear_casos
    cache_cajas: dict = {}
    cache_cats: dict = {}

    hashes_existentes = {
        r[0] for r in db.query(MovimientoCaja.hash_dedupe).all()
    }

    for idx, row in df.iterrows():
        fila_dict = row.to_dict()
        # SAVEPOINT por fila: aísla errores SQL para no envenenar la
        # transacción del batch. Si la fila falla, solo se rollbackea
        # ESTE savepoint y las filas previas quedan intactas.
        try:
            with db.begin_nested():
                fecha = parse_date_es(row.get("FECHA"))
                tipo_op = normalize_str(row.get("Tipo de Operación"))
                monto = parse_monto(row.get("MONTO"))
                origen_disp = normalize_str(row.get("SALIDAS"))
                destino_disp = normalize_str(row.get("ENTRADAS"))
                detalle = normalize_str(row.get("DETALLE DEL GASTO")) or None

                if fecha is None:
                    raise _RowReject("fecha_invalida",
                                     f"Fecha no parseable: {row.get('FECHA')}")
                if not tipo_op:
                    raise _RowReject("tipo_faltante", "Tipo de Operación vacío")
                if monto is None:
                    raise _RowReject("monto_invalido",
                                     f"Monto no parseable: {row.get('MONTO')}")
                if monto <= 0:
                    # Decisión de jurado adversarial: el importer rechaza
                    # negativos. El sistema source a veces exporta egresos
                    # con signo negativo en vez de usar la columna SALIDAS.
                    # Rechazamos para que la dueña edite el caso desde
                    # /casos y asigne explícitamente la caja correcta.
                    raise _RowReject("monto_invalido",
                                     f"Monto negativo o cero ({row.get('MONTO')}). "
                                     f"Editá: poné el monto en POSITIVO y agregá la "
                                     f"caja en SALIDAS (egreso) o ENTRADAS (ingreso).")
                if not origen_disp and not destino_disp:
                    raise _RowReject("sin_caja",
                                     "Falta SALIDAS y ENTRADAS — no se puede asignar")

                # Normalizar nombres SIN persistir todavía: el hash necesita
                # los nombres normalizados, pero crear cajas/categorías antes
                # del check de dedupe ensuciaría el catálogo si la fila resulta
                # duplicada (ver review I2).
                origen = Caja.normalizar(origen_disp) if origen_disp else None
                destino = Caja.normalizar(destino_disp) if destino_disp else None

                h = hash_row(
                    fecha.isoformat(), tipo_op, detalle or "",
                    str(monto), origen or "", destino or "",
                )

                if h in hashes_existentes:
                    result.ya_existian += 1
                    continue

                # Recién acá creamos cajas/categoría: la fila pasa el dedupe.
                get_or_create_categoria(
                    db, tipo_op, cache_cats, result.categorias_creadas
                )
                if origen_disp:
                    get_or_create_caja(db, origen_disp, cache_cajas, result.cajas_creadas)
                if destino_disp:
                    get_or_create_caja(db, destino_disp, cache_cajas, result.cajas_creadas)
                db.flush()

                mov = MovimientoCaja(
                    fecha=fecha,
                    tipo_operacion=tipo_op,
                    detalle=detalle,
                    monto=monto,
                    caja_origen=origen,
                    caja_destino=destino,
                    hash_dedupe=h,
                )
                db.add(mov)
                db.flush()
                hashes_existentes.add(h)
                result.aceptados += 1

        except _RowReject as e:
            _rechazar(db, result, int(idx), fila_dict, e.codigo, e.descripcion)
        except IntegrityError:
            # Carrera con otra fila idéntica del mismo batch: dedupe
            result.ya_existian += 1
        except Exception as e:
            # El SAVEPOINT ya rollbackeó esta fila. La sesión queda usable.
            _rechazar(db, result, int(idx), fila_dict, "excepcion", repr(e))

    db.commit()
    return result


class _RowReject(Exception):
    """Marca rechazos esperados de una fila — el savepoint hace rollback
    y el handler externo crea el CasoRevisar correspondiente."""
    def __init__(self, codigo: str, descripcion: str):
        self.codigo = codigo
        self.descripcion = descripcion
        super().__init__(descripcion)


def _rechazar(db, result, idx, fila_dict, codigo, descripcion):
    result.rechazados.append(
        Rechazo(fila=idx, motivo=codigo, descripcion=descripcion, datos=fila_dict)
    )
    if getattr(result, "_crear_casos", True):
        db.add(CasoRevisar(
            fuente="movimientos_caja",
            motivo_codigo=codigo,
            motivo_descripcion=descripcion,
            datos_originales=serializar_fila(fila_dict),
        ))
