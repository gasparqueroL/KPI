"""Helpers compartidos para filtrado por rango de fechas en queries de KPIs."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

# El proyecto opera en horario de Argentina. Defaults de fecha que dependen
# de "hoy" (resumen diario, alertas, etc.) deben usar `hoy_ar()` en vez de
# `date.today()` directo: si el backend corre en un host con TZ=UTC (Render,
# Fly), `date.today()` puede devolver el día siguiente cuando es noche en
# AR (UTC-3), generando reportes "vacíos" o desfasados.
_TZ_AR = ZoneInfo("America/Argentina/Buenos_Aires")


def hoy_ar() -> date:
    """Fecha de hoy en zona horaria Argentina (independiente del TZ del host)."""
    return datetime.now(_TZ_AR).date()


def hasta_fin_dia(hasta: date | datetime | None) -> datetime | None:
    """Convierte una date en el último instante del día (23:59:59.999999).

    Necesario para que ``columna <= hasta`` incluya las filas registradas
    durante el día tope. Si ``hasta`` ya es datetime, se devuelve tal cual.
    """
    if hasta is None:
        return None
    if isinstance(hasta, datetime):
        return hasta
    return datetime.combine(hasta, time.max)


def filtro_fecha(query, columna, desde, hasta):
    """Aplica ``desde <= columna <= hasta`` con inclusión de fin de día."""
    if desde:
        query = query.filter(columna >= desde)
    h = hasta_fin_dia(hasta)
    if h is not None:
        query = query.filter(columna <= h)
    return query
