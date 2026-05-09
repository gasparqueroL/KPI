import logging
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import CORS_ORIGINS
from app.db import init_db, seed_defaults
from app.routers import admin_router, alertas_router, caja_diaria_router, casos_revisar, cierres_router, conciliacion_router, configuracion, cuentas_corrientes_router, dashboard, health_router, import_router, kpis_caja, kpis_comerciales, kpis_financieros_router, kpis_manuales_router, kpis_objetivos_router, pagos_aplicados_router, proveedores_router, search_router, ventas_router

logger = logging.getLogger("kpi")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    init_db()
    n = seed_defaults()
    if n:
        logger.info("seed_defaults: %d categorías clasificadas", n)
    # Backup automático diario (idempotente: solo si no hay uno de hoy)
    bk = admin_router.backup_diario_si_corresponde()
    if bk:
        logger.info("Backup diario creado: %s", bk)
    # Rotar backups viejos al startup (caso: server reiniciado tras
    # acumular varios sin el scheduler).
    eliminados = admin_router.rotar_backups()
    if eliminados:
        logger.info("Backups rotados al startup: %s", eliminados)
    # Scheduler periódico: 1 backup/día + rotación. Tarea en background;
    # se cancela al shutdown.
    scheduler_task = asyncio.create_task(admin_router.scheduler_backups())
    try:
        yield
    finally:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except (asyncio.CancelledError, Exception):
            pass


app = FastAPI(title="KPI Dashboard API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== Middleware global de auth =====
# Si KPI_API_KEY está seteada en env, EXIGE el header X-API-Key en TODA
# request salvo health/docs. Si no está seteada, todo libre (modo localhost).
#
# Whitelist:
# - `/api/health` → necesario para que load balancers / scripts de deploy
#   puedan pingear sin key (caso de uso explícito del endpoint).
# - `/docs`, `/redoc`, `/openapi.json` → docs interactivas de FastAPI;
#   bloquearlas no aporta seguridad (todo el schema se reconstruye desde
#   los responses) y dificulta debugging legítimo.
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    from app.core.auth import auth_activa
    import os

    if not auth_activa():
        return await call_next(request)

    path = request.url.path
    if (
        path == "/api/health"
        or path.startswith("/docs")
        or path.startswith("/openapi")
        or path.startswith("/redoc")
    ):
        return await call_next(request)

    expected = os.environ["KPI_API_KEY"]
    if request.headers.get("x-api-key") != expected:
        return JSONResponse(
            status_code=401,
            content={"detail": "API key inválida o ausente. Configurá header X-API-Key."},
        )
    return await call_next(request)


@app.exception_handler(Exception)
async def excepcion_global(request: Request, exc: Exception):
    """Handler para excepciones no atajadas. Loguea trace, devuelve 500 genérico."""
    logger.error(
        "Error no manejado en %s %s\n%s",
        request.method, request.url.path,
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Error interno del servidor. Revisá los logs."},
    )

app.include_router(import_router.router)
app.include_router(kpis_comerciales.router)
app.include_router(kpis_caja.router)
app.include_router(casos_revisar.router)
app.include_router(configuracion.router)
app.include_router(ventas_router.router)
app.include_router(dashboard.router)
app.include_router(alertas_router.router)
app.include_router(conciliacion_router.router)
app.include_router(cuentas_corrientes_router.router)
app.include_router(caja_diaria_router.router)
app.include_router(cierres_router.router)
app.include_router(admin_router.router)
app.include_router(proveedores_router.router)
app.include_router(kpis_financieros_router.router)
app.include_router(kpis_manuales_router.router)
app.include_router(kpis_objetivos_router.router)
app.include_router(pagos_aplicados_router.router)
app.include_router(health_router.router)
app.include_router(search_router.router)
