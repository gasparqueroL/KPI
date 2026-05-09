"""Smoke tests vía TestClient HTTP para routers que no tenían cobertura
directa. Verifican que los endpoints respondan 200/4xx esperados y que
el shape básico del payload coincida — no validan lógica de negocio
profunda (eso vive en tests de los módulos `app.kpis.*`)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app as fastapi_app


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    def override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    c = TestClient(fastapi_app)
    yield c
    fastapi_app.dependency_overrides.clear()


# ===== caja_diaria_router =====

def test_sugerencias_endpoint_devuelve_estructura(client):
    r = client.get("/api/caja-diaria/sugerencias")
    assert r.status_code == 200
    data = r.json()
    assert "cajas" in data
    assert "categorias" in data
    assert isinstance(data["cajas"], list)


def test_resumen_diario_pdf_se_genera(client):
    r = client.get("/api/caja-diaria/resumen-diario.pdf")
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"


def test_crear_movimiento_sin_caja_400(client):
    r = client.post("/api/caja-diaria/movimiento", json={
        "fecha": "2026-04-15",
        "tipo_operacion": "Test",
        "monto": 1000,
    })
    assert r.status_code == 400
    assert "caja" in r.json()["detail"].lower()


def test_crear_movimiento_tipo_vacio_400(client):
    r = client.post("/api/caja-diaria/movimiento", json={
        "fecha": "2026-04-15",
        "tipo_operacion": "",
        "monto": 1000,
        "caja_destino": "ALGUNA",
    })
    assert r.status_code == 400


# ===== configuracion =====

def test_listar_categorias_estructura(client):
    r = client.get("/api/config/categorias")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_listar_familias(client):
    r = client.get("/api/config/familias")
    assert r.status_code == 200
    fams = r.json()
    assert isinstance(fams, list)
    assert "Personal" in fams  # del catálogo hardcoded


def test_listar_cajas_estructura(client):
    r = client.get("/api/config/cajas")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_actualizar_categoria_inexistente_404(client):
    r = client.put("/api/config/categorias/CategoriaXYZ", json={
        "familia": "Personal",
    })
    assert r.status_code == 404


# ===== ventas_router =====

def test_clientes_buscar_query_corta_devuelve_vacio(client):
    r = client.get("/api/ventas/clientes-buscar?q=A")
    assert r.status_code == 200
    assert r.json() == []  # query < 2 chars


def test_vendedores_lista(client):
    r = client.get("/api/ventas/vendedores")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ===== admin_router =====

def test_admin_info_responde(client):
    r = client.get("/api/admin/info")
    assert r.status_code == 200
    data = r.json()
    assert "db_existe" in data
    assert "backups_count" in data


def test_admin_backups_list_estructura(client):
    r = client.get("/api/admin/backups")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_admin_freeze_status(client):
    r = client.get("/api/admin/freeze-status")
    assert r.status_code == 200
    data = r.json()
    assert "legacy_total" in data


# ===== alertas_router =====

def test_alertas_endpoint_devuelve_payload(client):
    r = client.get("/api/alertas?refresh=true")
    assert r.status_code == 200
    data = r.json()
    # Puede ser dict o list según versión — aceptar ambos
    assert "alertas" in data or isinstance(data, list)


# ===== conciliacion_router =====

def test_conciliacion_resumen_estructura(client):
    r = client.get("/api/conciliacion/resumen")
    assert r.status_code == 200


def test_conciliacion_sin_cobro_acepta_filtro_fecha(client):
    r = client.get("/api/conciliacion/sin-cobro?desde=2026-01-01&hasta=2026-12-31&limite=10")
    assert r.status_code == 200


# ===== health_router =====

def test_health_responde_200(client):
    r = client.get("/api/health")
    assert r.status_code == 200


# ===== kpis_caja, kpis_comerciales, kpis_financieros (smoke) =====

def test_kpis_caja_resumen(client):
    r = client.get("/api/kpis/caja/resumen")
    assert r.status_code == 200


def test_kpis_caja_saldos(client):
    r = client.get("/api/kpis/caja/saldos")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_kpis_comerciales_resumen(client):
    r = client.get("/api/kpis/comerciales/resumen")
    assert r.status_code == 200


def test_kpis_financieros_margen_operativo(client):
    r = client.get("/api/kpis/financieros/margen-operativo")
    assert r.status_code == 200
    data = r.json()
    assert "margen_operativo" in data


def test_kpis_financieros_punto_equilibrio(client):
    r = client.get("/api/kpis/financieros/punto-equilibrio")
    assert r.status_code == 200
    # Sin cats fijas → nota explicativa
    assert r.json().get("nota") is not None


def test_kpis_financieros_dpo(client):
    r = client.get("/api/kpis/financieros/dpo")
    assert r.status_code == 200


# ===== PDFs (smoke: status + magic bytes) =====

def test_reporte_mensual_pdf_genera(client):
    """PDF mensual ejecutivo se emite con DB vacía sin crashear."""
    r = client.get("/api/dashboard/reporte-mensual.pdf?mes=2026-04")
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"


def test_reporte_mensual_pdf_mes_futuro_rechazado(client):
    r = client.get("/api/dashboard/reporte-mensual.pdf?mes=2099-12")
    assert r.status_code == 400


def test_reporte_mensual_pdf_formato_invalido(client):
    r = client.get("/api/dashboard/reporte-mensual.pdf?mes=invalido")
    assert r.status_code == 400


def test_extracto_cliente_pdf_genera_aunque_vacio(client):
    """Si el cliente no existe, el PDF se genera con datos vacíos (la
    dueña ve 'sin movimientos') en vez de 404. Esto es decisión UX."""
    r = client.get("/api/cuentas-corrientes/99999/extracto.pdf")
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"


def test_extracto_proveedor_pdf_404_si_no_existe(client):
    r = client.get("/api/proveedores/99999/extracto.pdf")
    assert r.status_code == 404


# ===== freeze + restore =====

def test_freeze_status_estructura(client):
    r = client.get("/api/admin/freeze-status")
    data = r.json()
    assert "legacy_total" in data
    assert "legacy_sin_pago_aplicado" in data
    assert "legacy_con_pago_aplicado" in data


def test_export_json_contiene_tablas(client):
    r = client.get("/api/admin/export.json")
    assert r.status_code == 200
    import json as jsonlib
    data = jsonlib.loads(r.content)
    assert "tablas" in data
    assert "ventas" in data["tablas"]
    assert "movimientos_caja" in data["tablas"]
    assert "exportado_en" in data


# ===== rotación + restore endpoints =====

def test_endpoint_restore_archivo_inexistente_404(client):
    r = client.post("/api/admin/backups/kpi_99999999_999999.db/restore")
    assert r.status_code == 404


def test_endpoint_restore_nombre_invalido_400(client):
    r = client.post("/api/admin/backups/no_es_backup.db/restore")
    assert r.status_code == 400
