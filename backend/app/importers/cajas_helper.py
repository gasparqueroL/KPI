"""Get-or-create para cajas y categorías (Opción B: auto-detect on import)."""

from sqlalchemy.orm import Session

from app.models.caja import Caja
from app.models.categoria_caja import CategoriaCaja


def get_or_create_caja(
    db: Session,
    nombre_display: str,
    cache: dict[str, Caja],
    creadas: list[str],
) -> Caja | None:
    if not nombre_display:
        return None
    nombre_display = nombre_display.strip()
    norm = Caja.normalizar(nombre_display)
    if not norm:
        return None

    if norm in cache:
        return cache[norm]

    caja = db.get(Caja, norm)
    if caja is None:
        tipo = "fc_empleado" if norm.endswith(".fc") else "operativa"
        caja = Caja(
            nombre_normalizado=norm,
            nombre_display=nombre_display,
            tipo=tipo,
        )
        db.add(caja)
        creadas.append(nombre_display)
    elif caja.archivado_at is not None:
        # Caja archivada que vuelve a ser referenciada: desarchivar
        # automáticamente. La intención del usuario es que la caja exista
        # (la incluyó en el CSV o la eligió desde sugerencias-caja en
        # /casos). No es un comportamiento silencioso peligroso porque la
        # acción del usuario es explícita en ambos casos.
        caja.archivado_at = None

    cache[norm] = caja
    return caja


def get_or_create_categoria(
    db: Session,
    tipo_op: str,
    cache: dict[str, CategoriaCaja],
    creadas: list[str],
) -> CategoriaCaja | None:
    if not tipo_op:
        return None
    tipo_op = tipo_op.strip()
    if not tipo_op:
        return None

    if tipo_op in cache:
        return cache[tipo_op]

    cat = db.get(CategoriaCaja, tipo_op)
    if cat is None:
        cat = CategoriaCaja(tipo_operacion=tipo_op)
        db.add(cat)
        creadas.append(tipo_op)

    cache[tipo_op] = cat
    return cat
