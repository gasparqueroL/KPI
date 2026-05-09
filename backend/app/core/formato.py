"""Helpers de formato compartidos entre módulos del backend.

La idea: una sola fuente de verdad para la convención AR (puntos como miles,
coma decimal) — sino terminamos con `$45,000` US-style en alertas y
`$45.000` AR-style en PDFs/frontend, generando inconsistencia que la dueña
nota inmediatamente.

El frontend usa `Intl.NumberFormat("es-AR")` (ver `fmtMoney` en api/client.js),
que produce exactamente este formato. Esta función lo replica server-side.
"""

import math
from decimal import Decimal
from typing import Union

# Tipo aceptado: number-like que pueda convertirse a float sin pérdida.
NumLike = Union[int, float, Decimal, None]


def fmt_money_ar(v: NumLike, *, strict: bool = False) -> str:
    """Formatea un monto como string AR-style: `$1.234.567`.

    - Miles separados con punto (convención AR/ES, NO coma US-style).
    - 0 decimales por default (importes operativos rara vez tienen centavos
      a nivel UI).
    - Negativos: `-$5.000` (signo ANTES del símbolo, convención Excel-style
      AR). Excel/Sheets en es-AR muestran negativos así por default.
    - `strict=False` (default): valores `None` o `0` devuelven string vacío.
      Útil para celdas de tabla donde mostrar `$0` agrega ruido visual.
    - `strict=True`: siempre muestra el monto. Para `0` retorna `"$0"`;
      para `None` retorna `"-"` (distingue "valor desconocido" de "valor
      cero genuino" — semántica útil en tablas de KPIs).
    - Valores no finitos (`inf`, `nan`): retornan string vacío (modo default)
      o `"-"` (modo strict). NO surfacear `$inf` o `$nan` a la dueña.
      Cumple "solo entra al sistema lo válido" — un cálculo upstream con
      división por cero es bug que debe diagnosticarse, no mostrarse en UI.

    Args:
        v: monto. Acepta int, float, Decimal, o None.
        strict: si True, fuerza render aunque el valor sea None o 0.

    Returns:
        String con formato `$X.XXX` (positivos), `-$X.XXX` (negativos),
        `""` o `"-"` según el modo cuando no hay valor representable.
    """
    if v is None:
        return "-" if strict else ""
    n = float(v)
    # Inf/NaN: cualquier path que llegue acá con uno de estos viene de un
    # cálculo upstream defectuoso (división por cero, agregación rota).
    # No queremos mostrar "$inf" o "$nan" en una alerta o KPI — devolvemos
    # placeholder y dejamos que el bug se diagnostique por logs/contexto.
    if not math.isfinite(n):
        return "-" if strict else ""
    if n == 0 and not strict:
        return ""
    # Para negativos formateamos el absoluto y prefijamos el signo —
    # `f"{-5000:,.0f}"` da "-5,000", al replace + f"${s}" daría "$-5.000"
    # (signo ENTRE $ y dígitos), no es la convención AR estándar.
    if n < 0:
        s = f"{-n:,.0f}".replace(",", ".")
        return f"-${s}"
    s = f"{n:,.0f}".replace(",", ".")
    return f"${s}"
