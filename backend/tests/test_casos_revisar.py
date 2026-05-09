"""Tests del endpoint de casos a revisar — foco en bulk y búsqueda."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app as fastapi_app
from app.models.caso_revisar import CasoRevisar


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
        db = Session()
        try:
            yield db
        finally:
            db.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    c = TestClient(fastapi_app)
    c._session_factory = Session
    yield c
    fastapi_app.dependency_overrides.clear()


def _crear_casos(client, items):
    """Crea casos directos en DB. items = [(fuente, motivo, descripcion, datos_dict)]."""
    s = client._session_factory()
    for fuente, motivo, desc, datos in items:
        s.add(CasoRevisar(
            fuente=fuente,
            motivo_codigo=motivo,
            motivo_descripcion=desc,
            datos_originales=json.dumps(datos),
            estado="pendiente",
        ))
    s.commit()
    s.close()


def test_descartar_bulk_marca_todos(client):
    _crear_casos(client, [
        ("ventas", "fecha_invalida", "Fecha vacía", {"f": ""}),
        ("ventas", "fecha_invalida", "Fecha vacía", {"f": "x"}),
        ("ventas", "monto_invalido", "Monto raro", {"m": "abc"}),
    ])
    s = client._session_factory()
    ids = [c.id for c in s.query(CasoRevisar).all()]
    s.close()

    r = client.post("/api/casos-revisar/descartar-bulk", json={"ids": ids})
    assert r.status_code == 200
    assert r.json()["descartados"] == 3

    s = client._session_factory()
    estados = [c.estado for c in s.query(CasoRevisar).all()]
    s.close()
    assert all(e == "descartado" for e in estados)


def test_descartar_bulk_idempotente_con_ya_descartados(client):
    _crear_casos(client, [
        ("ventas", "x", "test", {}),
    ])
    s = client._session_factory()
    cid = s.query(CasoRevisar).first().id
    s.close()

    r1 = client.post("/api/casos-revisar/descartar-bulk", json={"ids": [cid]})
    assert r1.json()["descartados"] == 1
    # Re-descartar el mismo: debe devolver 0 (ya estaba descartado)
    r2 = client.post("/api/casos-revisar/descartar-bulk", json={"ids": [cid]})
    assert r2.json()["descartados"] == 0


def test_descartar_bulk_ids_vacio_400(client):
    r = client.post("/api/casos-revisar/descartar-bulk", json={"ids": []})
    assert r.status_code == 400


def test_descartar_bulk_max_500(client):
    r = client.post("/api/casos-revisar/descartar-bulk", json={"ids": list(range(501))})
    assert r.status_code == 400


def test_busqueda_q_filtra_por_descripcion(client):
    _crear_casos(client, [
        ("ventas", "x", "Cliente Acme SA con problema", {"f": "v1"}),
        ("ventas", "x", "Cliente Distribuidora Sur", {"f": "v2"}),
        ("ventas", "x", "Producto sin código", {"f": "v3"}),
    ])
    r = client.get("/api/casos-revisar?q=Acme")
    items = r.json()["items"]
    assert len(items) == 1
    assert "Acme" in items[0]["motivo_descripcion"]


def test_busqueda_q_filtra_por_datos_originales(client):
    """La búsqueda también penetra en el JSON de datos_originales serializado."""
    _crear_casos(client, [
        ("ventas", "x", "Caso A", {"cliente": "Acme SA"}),
        ("ventas", "x", "Caso B", {"cliente": "Otra Empresa"}),
    ])
    r = client.get("/api/casos-revisar?q=Acme")
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["motivo_descripcion"] == "Caso A"


def test_busqueda_q_case_insensitive(client):
    _crear_casos(client, [
        ("ventas", "x", "Cliente ACME", {}),
    ])
    r = client.get("/api/casos-revisar?q=acme")
    assert len(r.json()["items"]) == 1


# ===== Archivado =====

def _crear_caso(client, estado="pendiente"):
    s = client._session_factory()
    c = CasoRevisar(
        fuente="ventas", motivo_codigo="x", motivo_descripcion="t",
        datos_originales="{}", estado=estado,
    )
    s.add(c)
    s.commit()
    cid = c.id
    s.close()
    return cid


def test_archivar_oculta_caso_de_listado_default(client):
    """Caso archivado no aparece en listar por default."""
    cid_p = _crear_caso(client, "pendiente")
    cid_a = _crear_caso(client, "pendiente")

    # Ambos visibles antes
    r = client.get("/api/casos-revisar?estado=pendiente")
    assert r.json()["total"] == 2

    # Archivar uno
    r = client.post(f"/api/casos-revisar/{cid_a}/archivar")
    assert r.status_code == 200
    assert r.json()["archivado_at"] is not None

    # Ahora solo el no-archivado aparece
    r = client.get("/api/casos-revisar?estado=pendiente")
    items = r.json()["items"]
    assert r.json()["total"] == 1
    assert items[0]["id"] == cid_p


def test_solo_archivados_lista_solo_los_archivados(client):
    cid_p = _crear_caso(client, "pendiente")
    cid_a = _crear_caso(client, "pendiente")
    client.post(f"/api/casos-revisar/{cid_a}/archivar")

    r = client.get("/api/casos-revisar?estado=pendiente&solo_archivados=true")
    items = r.json()["items"]
    assert r.json()["total"] == 1
    assert items[0]["id"] == cid_a


def test_desarchivar_devuelve_caso_a_listado(client):
    cid = _crear_caso(client, "pendiente")
    client.post(f"/api/casos-revisar/{cid}/archivar")
    r = client.get("/api/casos-revisar?estado=pendiente")
    assert r.json()["total"] == 0

    r = client.post(f"/api/casos-revisar/{cid}/desarchivar")
    assert r.status_code == 200
    assert r.json()["archivado_at"] is None

    r = client.get("/api/casos-revisar?estado=pendiente")
    assert r.json()["total"] == 1


def test_archivar_resueltos_archiva_descartados_y_corregidos(client):
    """Bulk: solo afecta descartado/corregido, no toca pendientes."""
    cid_p = _crear_caso(client, "pendiente")
    cid_d = _crear_caso(client, "descartado")
    cid_c = _crear_caso(client, "corregido")

    r = client.post("/api/casos-revisar/archivar-resueltos")
    assert r.status_code == 200
    assert r.json()["archivados"] == 2

    s = client._session_factory()
    casos = {c.id: c for c in s.query(CasoRevisar).all()}
    assert casos[cid_p].archivado_at is None  # pendiente NO se archiva
    assert casos[cid_d].archivado_at is not None
    assert casos[cid_c].archivado_at is not None
    s.close()


def test_archivar_resueltos_idempotente(client):
    """Re-correr no re-archiva los ya archivados."""
    _crear_caso(client, "descartado")
    r1 = client.post("/api/casos-revisar/archivar-resueltos")
    assert r1.json()["archivados"] == 1
    r2 = client.post("/api/casos-revisar/archivar-resueltos")
    assert r2.json()["archivados"] == 0


def test_resumen_separa_archivados_de_estados_visibles(client):
    """`por_estado` solo cuenta no-archivados; `archivados` se reporta aparte."""
    _crear_caso(client, "pendiente")
    cid = _crear_caso(client, "descartado")
    client.post(f"/api/casos-revisar/{cid}/archivar")

    r = client.get("/api/casos-revisar/resumen")
    data = r.json()
    assert data["por_estado"].get("pendiente") == 1
    # El descartado archivado NO aparece en por_estado
    assert data["por_estado"].get("descartado", 0) == 0
    assert data["archivados"] == 1
    assert data["total"] == 1  # solo el pendiente activo
