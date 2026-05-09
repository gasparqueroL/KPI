"""Detección automática del tipo de CSV y ruteo al importer correcto."""

import io

import pandas as pd
from sqlalchemy.orm import Session

from app.importers.base import ImportResult
from app.importers.detalle_ventas import (
    es_csv_detalle,
    import_detalle_ventas,
)
from app.importers.movimientos_caja import (
    es_csv_caja,
    import_movimientos_caja,
)
from app.importers.ventas import es_csv_ventas, import_ventas


# Magic bytes de archivos zip (XLSX es un zip de XMLs). Los 4 primeros bytes
# son siempre uno de estos para un xlsx válido. Detectamos por contenido —
# no por extensión — para no depender del filename y aceptar uploads sin
# nombre (chunks streamed sin metadata).
_XLSX_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


def es_xlsx(contenido: bytes) -> bool:
    return any(contenido.startswith(m) for m in _XLSX_MAGIC)


def leer_xlsx(contenido: bytes) -> pd.DataFrame:
    """Lee la primera hoja de un XLSX. Misma semántica que `leer_csv`:
    todo como string para que los importers parseen consistentemente."""
    return pd.read_excel(
        io.BytesIO(contenido),
        engine="openpyxl",
        dtype=str,
        keep_default_na=False,
        na_values=["", "nan", "NaN"],
    )


def leer_csv(contenido: bytes) -> pd.DataFrame:
    """Lee CSV con encoding tolerante (UTF-8 con o sin BOM)."""
    return pd.read_csv(
        io.BytesIO(contenido),
        encoding="utf-8-sig",
        dtype=str,
        keep_default_na=False,
        na_values=["", "nan", "NaN"],
    )


def leer_archivo(contenido: bytes) -> pd.DataFrame:
    """Auto-detecta CSV vs XLSX por magic bytes y delega.

    Acepta XLSX directo: la dueña no necesita exportar a CSV antes desde
    Excel — un paso menos en su flujo cotidiano."""
    if es_xlsx(contenido):
        return leer_xlsx(contenido)
    return leer_csv(contenido)


def detectar_tipo(df: pd.DataFrame) -> str | None:
    headers = set(df.columns)
    if es_csv_ventas(headers):
        return "ventas"
    if es_csv_detalle(headers):
        return "detalle_ventas"
    if es_csv_caja(headers):
        return "movimientos_caja"
    return None


def importar(db: Session, contenido: bytes, tipo_forzado: str | None = None) -> tuple[str, ImportResult]:
    df = leer_archivo(contenido)
    tipo = tipo_forzado or detectar_tipo(df)
    if tipo is None:
        raise ValueError(
            f"No pude detectar el tipo de CSV. Columnas: {list(df.columns)}"
        )
    if tipo == "ventas":
        return tipo, import_ventas(db, df)
    if tipo == "detalle_ventas":
        return tipo, import_detalle_ventas(db, df)
    if tipo == "movimientos_caja":
        result = import_movimientos_caja(db, df)
        # Aplicar defaults a categorías recién creadas
        from app.importers.categorias_seed import aplicar_defaults
        aplicar_defaults(db)
        return tipo, result
    raise ValueError(f"Tipo desconocido: {tipo}")
