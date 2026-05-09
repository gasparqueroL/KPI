import os
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "kpi.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

# CORS: lista coma-separada en `KPI_CORS_ORIGINS`. Default localhost dev.
# Por seguridad NO incluimos "*" — si la dueña deploya el frontend en
# otra URL, debe configurar explícitamente.
# CORS: usamos `or` en vez de default arg porque KPI_CORS_ORIGINS=""
# (caso típico en docker-compose con var seteada vacía) caería al default
# vacío con `os.getenv(name, default)`. Con `or` el "" falsy también
# usa el default → comportamiento esperado.
CORS_ORIGINS = [
    o.strip()
    for o in (
        os.getenv("KPI_CORS_ORIGINS")
        or "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if o.strip()
]

# Tolerancia para considerar que la suma de pagos coincide con el total
# de la venta. Por debajo se ignoran (redondeos). Por encima se marca
# discrepancia_pago=True (no rechaza la fila, solo flag de auditoría).
TOLERANCIA_DISCREPANCIA_ARS = Decimal("0.50")


# ===== Umbrales centralizados =====
# Todos leídos vía `os.getenv` con defaults para que la dueña pueda
# afinar sin tocar código. Centralizar acá evita drift entre módulos
# (alertas/comerciales/financieros/cierres compartían env vars con
# convenciones distintas — ahora un solo lugar).

def _f(env: str, default: float) -> float:
    """Helper: lee env var como float con default."""
    try:
        return float(os.getenv(env, str(default)))
    except (ValueError, TypeError):
        return default


def umbrales_concentracion_clientes() -> dict[str, float]:
    """Concentración de top1/top3 clientes sobre ventas totales.
    Usado en `kpis/comerciales.py` y `kpis/alertas.py`."""
    return {
        "top1_critica": _f("UMBRAL_TOP1_CRITICA_PCT", 50),
        "top1_atencion": _f("UMBRAL_TOP1_ATENCION_PCT", 30),
        "top3_atencion": _f("UMBRAL_TOP3_ATENCION_PCT", 60),
    }


def umbrales_concentracion_proveedores() -> dict[str, float]:
    """Concentración top1 proveedor. Cadena de fallback: env var
    específica de proveedores → env var compartida con clientes →
    default. Permite afinar por separado o reusar."""
    return {
        "top1_atencion": _f(
            "UMBRAL_TOP1_ATENCION_PROV_PCT",
            _f("UMBRAL_TOP1_ATENCION_PCT", 30),
        ),
        "top1_critica": _f(
            "UMBRAL_TOP1_CRITICA_PROV_PCT",
            _f("UMBRAL_TOP1_CRITICA_PCT", 50),
        ),
    }


def umbrales_auditoria_cierres() -> dict[str, Decimal]:
    """Discrepancias en cierre de caja vs saldo computado."""
    return {
        "tolerancia": Decimal(os.getenv("UMBRAL_TOLERANCIA_CIERRE_ARS", "100")),
        "umbral_critica": Decimal(os.getenv("UMBRAL_CIERRE_CRITICO_ARS", "50000")),
    }


def umbrales_alerta_caja() -> dict[str, float]:
    """Saldos mínimos y atípicos."""
    return {
        "saldo_caja_critico_ars": _f("UMBRAL_SALDO_CRITICO_ARS", 0),
        "factor_atipico": _f("UMBRAL_FACTOR_ATIPICO", 5.0),
    }


def umbrales_facturas() -> dict[str, int]:
    """Días para alertas de facturas próximas a vencer / vencidas."""
    return {
        "dias_proximas": int(_f("UMBRAL_FACTURAS_DIAS_PROXIMAS", 7)),
        "dias_morosidad": int(_f("UMBRAL_DIAS_MOROSIDAD", 30)),
    }
