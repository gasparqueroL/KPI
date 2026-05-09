"""Endpoint para importar CSVs."""

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.importers.dispatch import importar
from app.routers._cache_helpers import invalida_caches_pesados

router = APIRouter(prefix="/api/import", tags=["import"])

# Cap de tamaño de upload — protege contra OOM si alguien sube un GB
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


@router.post("")
@invalida_caches_pesados
async def importar_csv(
    file: UploadFile = File(...),
    tipo: str | None = Query(
        default=None,
        description="Forzar tipo: ventas | detalle_ventas | movimientos_caja",
    ),
    db: Session = Depends(get_db),
):
    # Chequeo de tamaño con Content-Length declarado (rápido)
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413,
            f"Archivo demasiado grande ({file.size // 1024 // 1024} MB). "
            f"Máximo permitido: {MAX_UPLOAD_BYTES // 1024 // 1024} MB.",
        )
    # Lectura por chunks: corta a 50MB sin OOMear si el upload es chunked sin Content-Length
    chunks: list[bytes] = []
    leido = 0
    while True:
        chunk = await file.read(1024 * 64)
        if not chunk:
            break
        leido += len(chunk)
        if leido > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"Archivo excede el límite de {MAX_UPLOAD_BYTES // 1024 // 1024} MB.")
        chunks.append(chunk)
    contenido = b"".join(chunks)
    try:
        tipo_detectado, result = importar(db, contenido, tipo_forzado=tipo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "archivo": file.filename,
        "tipo_detectado": tipo_detectado,
        **result.to_dict(),
    }
