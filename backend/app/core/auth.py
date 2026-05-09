"""Auth simple por API key estática (env var).

Comportamiento:
- Si `KPI_API_KEY` NO está seteada → modo localhost-only sin auth (default).
- Si está seteada → todo endpoint que use el dependency `requiere_api_key`
  exige el header `X-API-Key` con el valor exacto.

Pensado como hardening cuando el sistema deja de ser localhost (LAN, deploy).
"""

import os

from fastapi import Header, HTTPException


def _api_key_configurada() -> str | None:
    return os.environ.get("KPI_API_KEY")


def requiere_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Dependency: si está configurada KPI_API_KEY, exige el header X-API-Key."""
    expected = _api_key_configurada()
    if expected is None:
        return  # sin API key configurada = modo localhost sin auth
    if not x_api_key or x_api_key != expected:
        raise HTTPException(401, "API key inválida o ausente")


def auth_activa() -> bool:
    return _api_key_configurada() is not None
