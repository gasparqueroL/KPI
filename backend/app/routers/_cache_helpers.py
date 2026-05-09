"""Helpers compartidos para routers."""

import asyncio
from functools import wraps


def invalida_alertas(func):
    """Decorator: invalida cache de alertas después de un response exitoso.
    Soporta funciones sync y async.

    IMPORTANTE: la invalidación corre SOLO si la función retorna sin
    levantar excepción. Si se lanza HTTPException (4xx/5xx) u otra
    excepción, el cache NO se invalida — esto es deseable porque un
    rollback no cambia el estado observable. Footgun: si una función
    modifica y commitea estado parcial y DESPUÉS levanta HTTPException,
    el cache queda desincronizado. No hacer eso: o se commitea entero,
    o se rollbackea entero.

    Uso:
        @router.post("/foo")
        @invalida_alertas
        def crear_foo(...):
            ...
    """
    if asyncio.iscoroutinefunction(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            from app.routers import alertas_router  # diferido para evitar ciclos
            result = await func(*args, **kwargs)
            alertas_router.invalidar_cache()
            return result
        return async_wrapper

    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        from app.routers import alertas_router  # diferido para evitar ciclos
        result = func(*args, **kwargs)
        alertas_router.invalidar_cache()
        return result
    return sync_wrapper


def invalida_caches_pesados(func):
    """Decorator extendido: invalida alertas + caches de KPIs derivados,
    objetivos y financieros. Para usar en imports masivos / ediciones que
    afectan agregados (movimientos, ventas, facturas).

    Sin esto, después de un import los endpoints `/punto-equilibrio`,
    `/crecimiento-sostenido`, `/api/kpis-objetivos/resumen` y `/heatmap`
    sirven datos viejos hasta el próximo TTL (5min-1h)."""
    if asyncio.iscoroutinefunction(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            from app.routers import alertas_router
            from app.routers import kpis_financieros_router
            from app.routers import kpis_objetivos_router
            result = await func(*args, **kwargs)
            alertas_router.invalidar_cache()
            kpis_financieros_router._invalidar_cache_financieros()
            kpis_objetivos_router._invalidar_cache_resumen()
            kpis_objetivos_router._invalidar_cache_heatmap()
            return result
        return async_wrapper

    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        from app.routers import alertas_router
        from app.routers import kpis_financieros_router
        from app.routers import kpis_objetivos_router
        result = func(*args, **kwargs)
        alertas_router.invalidar_cache()
        kpis_financieros_router._invalidar_cache_financieros()
        kpis_objetivos_router._invalidar_cache_resumen()
        kpis_objetivos_router._invalidar_cache_heatmap()
        return result
    return sync_wrapper
