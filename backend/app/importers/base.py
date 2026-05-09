"""Tipos comunes y helpers para los importadores."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any


def limpiar_para_json(v: Any) -> Any:
    """Convierte NaN/None/floats raros a algo JSON-serializable."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return str(v) if not isinstance(v, (str, int, bool)) else v


@dataclass
class Rechazo:
    fila: int
    motivo: str
    descripcion: str
    datos: dict[str, Any]


@dataclass
class ImportResult:
    fuente: str
    aceptados: int = 0
    ya_existian: int = 0
    rechazados: list[Rechazo] = field(default_factory=list)
    cajas_creadas: list[str] = field(default_factory=list)
    categorias_creadas: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        rechazados_clean = []
        for r in self.rechazados:
            d = asdict(r)
            d["datos"] = {k: limpiar_para_json(v) for k, v in d["datos"].items()}
            rechazados_clean.append(d)
        return {
            "fuente": self.fuente,
            "aceptados": self.aceptados,
            "ya_existian": self.ya_existian,
            "rechazados": rechazados_clean,
            "rechazados_count": len(self.rechazados),
            "cajas_creadas": self.cajas_creadas,
            "categorias_creadas": self.categorias_creadas,
        }


def hash_row(*parts: Any) -> str:
    """Hash sha1 estable sobre componentes normalizados a string lower-trim."""
    payload = "|".join(
        ("" if p is None else str(p).strip().lower()) for p in parts
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def serializar_fila(fila: dict[str, Any]) -> str:
    return json.dumps(
        {k: limpiar_para_json(v) for k, v in fila.items()},
        ensure_ascii=False,
    )
