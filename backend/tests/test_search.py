"""Tests del endpoint de búsqueda global (alimenta el modal Cmd-K)."""
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app as fastapi_app
from app.models.caja import Caja
from app.models.movimiento_caja import MovimientoCaja
from app.models.proveedor import FacturaProveedor, Proveedor
from app.models.venta import Venta


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


def _setup(client):
    s = client._session_factory()
    s.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    s.add(Venta(
        id_pedido="P1", id_venta="V1",
        id_cliente=42, cliente="Acme Distribuidora SA",
        fecha=datetime(2026, 4, 1), total=Decimal("1000"),
    ))
    s.add(Venta(
        id_pedido="P2", id_venta="V2",
        id_cliente=43, cliente="Otra Empresa SRL",
        fecha=datetime(2026, 4, 2), total=Decimal("500"),
    ))
    p = Proveedor(nombre="Insumos Acme", cuit="30-99999999-9")
    s.add(p)
    s.commit()
    s.refresh(p)
    s.add(FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date(2026, 4, 5),
        total=Decimal("3000"), numero="F-001", descripcion="Insumos varios",
    ))
    s.add(MovimientoCaja(
        fecha=date(2026, 4, 10), tipo_operacion="Sueldo",
        monto=Decimal("75000"), caja_origen="cl",
        detalle="Sueldo mensual Acme empleado", hash_dedupe="hs1",
    ))
    s.commit()
    s.close()


def test_search_encuentra_cliente(client):
    _setup(client)
    r = client.get("/api/search?q=Acme")
    assert r.status_code == 200
    data = r.json()
    tipos = [r["tipo"] for r in data["resultados"]]
    # "Acme" matchea cliente, proveedor (Insumos Acme), y movimiento (detalle).
    assert "cliente" in tipos
    assert "proveedor" in tipos
    assert "movimiento" in tipos


def test_search_case_insensitive(client):
    _setup(client)
    r1 = client.get("/api/search?q=acme")
    r2 = client.get("/api/search?q=ACME")
    assert r1.json()["total"] == r2.json()["total"]
    assert r1.json()["total"] > 0


def test_search_q_vacio_rechaza(client):
    """min_length=1 — query vacía debe rechazar con 422."""
    r = client.get("/api/search?q=")
    assert r.status_code == 422


def test_search_factura_anulada_no_aparece(client):
    _setup(client)
    s = client._session_factory()
    f = s.query(FacturaProveedor).first()
    f.anulada = True
    s.commit()
    s.close()

    r = client.get("/api/search?q=F-001")
    tipos = [x["tipo"] for x in r.json()["resultados"]]
    assert "factura" not in tipos


def test_search_devuelve_link_con_query_param_para_deep_link(client):
    """Cliente, proveedor y factura devuelven `link` con query param que
    permite a la página abrir el detalle directo (no la lista genérica)."""
    _setup(client)
    r = client.get("/api/search?q=Otra")
    items = r.json()["resultados"]
    assert all("link" in i and "id" in i and "label" in i for i in items)
    cliente = next(i for i in items if i["tipo"] == "cliente")
    assert cliente["link"] == "/cuentas-corrientes?cliente=43"
    assert cliente["id"] == 43


def test_search_factura_link_apunta_al_proveedor_con_factura_param(client):
    """La factura no tiene página propia: el link va al proveedor con el
    id de factura como param para que el frontend haga scroll + highlight."""
    _setup(client)
    s = client._session_factory()
    from app.models.proveedor import FacturaProveedor, Proveedor
    prov = s.query(Proveedor).first()
    fact = s.query(FacturaProveedor).first()
    pid, fid = prov.id, fact.id
    s.close()

    r = client.get("/api/search?q=F-001")
    items = r.json()["resultados"]
    factura = next(i for i in items if i["tipo"] == "factura")
    assert factura["link"] == f"/proveedores?proveedor={pid}&factura={fid}"


def test_search_sin_match_devuelve_vacio(client):
    _setup(client)
    r = client.get("/api/search?q=zzznoexiste")
    assert r.status_code == 200
    assert r.json()["resultados"] == []


def test_search_q_muy_largo_rechaza(client):
    """max_length=100."""
    r = client.get("/api/search?q=" + "x" * 200)
    assert r.status_code == 422
