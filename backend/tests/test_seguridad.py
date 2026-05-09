"""Tests de hardening de seguridad."""
import os

from app.core.auth import auth_activa, requiere_api_key
from fastapi import HTTPException
import pytest


def test_sin_env_var_auth_inactiva(monkeypatch):
    monkeypatch.delenv("KPI_API_KEY", raising=False)
    assert auth_activa() is False
    # Sin auth configurada, no debe levantar nada aunque no llegue el header
    requiere_api_key(x_api_key=None)


def test_con_env_var_requiere_header(monkeypatch):
    monkeypatch.setenv("KPI_API_KEY", "secreto123")
    assert auth_activa() is True
    with pytest.raises(HTTPException) as exc:
        requiere_api_key(x_api_key=None)
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException):
        requiere_api_key(x_api_key="otra-cosa")
    # Header correcto: no levanta
    requiere_api_key(x_api_key="secreto123")


def test_csv_injection_se_prefija():
    from app.routers.cuentas_corrientes_router import _safe_csv_field
    assert _safe_csv_field("=cmd|calc") == "'=cmd|calc"
    assert _safe_csv_field("+1+1") == "'+1+1"
    assert _safe_csv_field("-2") == "'-2"
    assert _safe_csv_field("@SUM(A1)") == "'@SUM(A1)"
    # Texto normal pasa intacto
    assert _safe_csv_field("Ariel Gonzales") == "Ariel Gonzales"
    assert _safe_csv_field(None) == ""
    assert _safe_csv_field(1500) == "1500"


def test_csv_injection_sanitiza_newlines():
    """Newlines embebidos no deben permitir que la siguiente "línea"
    sea interpretada como fórmula (ej. 'foo\\n=cmd' que Excel parsearía)."""
    from app.routers.cuentas_corrientes_router import _safe_csv_field
    assert _safe_csv_field("foo\n=cmd") == "foo =cmd"
    assert _safe_csv_field("foo\r=cmd") == "foo =cmd"
    assert _safe_csv_field("foo\r\n=cmd") == "foo  =cmd"


# ===== Tests E2E del middleware de auth aplicado =====

def test_middleware_sin_key_configurada_pasa_libre(monkeypatch):
    """Sin KPI_API_KEY: cualquier endpoint responde sin pedir header."""
    monkeypatch.delenv("KPI_API_KEY", raising=False)
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app
    client = TestClient(fastapi_app)
    r = client.get("/api/health")
    assert r.status_code == 200


def test_middleware_con_key_sin_header_devuelve_401(monkeypatch):
    """Con KPI_API_KEY configurada: request sin X-API-Key → 401 (excepto whitelist).
    Usamos /api/admin/auth-status que no toca DB para aislar el test del middleware."""
    monkeypatch.setenv("KPI_API_KEY", "miclave-secreta")
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app
    client = TestClient(fastapi_app)
    r = client.get("/api/admin/auth-status")
    assert r.status_code == 401
    assert "API key" in r.json()["detail"]


def test_middleware_con_header_valido_devuelve_200(monkeypatch):
    monkeypatch.setenv("KPI_API_KEY", "miclave-secreta")
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app
    client = TestClient(fastapi_app)
    r = client.get("/api/admin/auth-status", headers={"X-API-Key": "miclave-secreta"})
    assert r.status_code == 200
    assert r.json()["auth_activa"] is True


def test_middleware_health_no_requiere_key(monkeypatch):
    """`/api/health` debe responder sin key incluso con auth activa.
    Necesario para load balancers / scripts de deploy."""
    monkeypatch.setenv("KPI_API_KEY", "miclave-secreta")
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app
    client = TestClient(fastapi_app)
    r = client.get("/api/health")
    assert r.status_code == 200


def test_middleware_docs_no_requieren_key(monkeypatch):
    """Docs y OpenAPI schema no requieren key — bloquearlas no aporta
    seguridad real (el schema se reconstruye desde responses) y dificulta
    debugging legítimo."""
    monkeypatch.setenv("KPI_API_KEY", "miclave-secreta")
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app
    client = TestClient(fastapi_app)
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
