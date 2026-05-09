"""Tests de endpoints (FastAPI TestClient) para los flujos críticos
de cierres y proveedores: cascada DELETE, fecha futura, validación
cross-proveedor en vincular, anular factura, POST movimiento bloqueado.

Usa una DB SQLite en memoria compartida entre el cliente HTTP y los
fixtures del test (override de get_db)."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app as fastapi_app
from app.models.caja import Caja
from app.models.cierre_caja import CierreCaja
from app.models.movimiento_caja import MovimientoCaja
from app.models.proveedor import FacturaProveedor, Proveedor
from app.models.venta import DetalleVenta, Venta


@pytest.fixture
def client():
    # StaticPool: una sola conexión compartida para que el ":memory:" sea
    # visible desde el TestClient (que abre conexiones nuevas) y desde el
    # session_factory que usamos en el setup del test.
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


def _setup_caja(client):
    s = client._session_factory()
    s.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    s.commit()
    s.close()


def test_cerrar_rechaza_fecha_futura(client):
    _setup_caja(client)
    futuro = (date.today() + timedelta(days=10)).isoformat()
    r = client.post("/api/cierres", json={
        "fecha": futuro, "caja": "cl", "saldo_cierre": 0,
    })
    assert r.status_code == 400
    assert "futura" in r.json()["detail"].lower()


def test_reabrir_con_posteriores_sin_cascada_falla(client):
    _setup_caja(client)
    s = client._session_factory()
    s.add(CierreCaja(fecha=date(2026, 4, 30), caja="cl", saldo_cierre=Decimal("0")))
    s.add(CierreCaja(fecha=date(2026, 5, 31), caja="cl", saldo_cierre=Decimal("0")))
    s.commit()
    cierre_abril_id = s.query(CierreCaja).filter(
        CierreCaja.fecha == date(2026, 4, 30)
    ).first().id
    s.close()

    r = client.delete(f"/api/cierres/{cierre_abril_id}")
    assert r.status_code == 409
    assert "posterior" in r.json()["detail"].lower()


def test_reabrir_con_cascada_borra_posteriores(client):
    _setup_caja(client)
    s = client._session_factory()
    s.add(CierreCaja(fecha=date(2026, 4, 30), caja="cl", saldo_cierre=Decimal("0")))
    s.add(CierreCaja(fecha=date(2026, 5, 31), caja="cl", saldo_cierre=Decimal("0")))
    s.commit()
    cierre_abril_id = s.query(CierreCaja).filter(
        CierreCaja.fecha == date(2026, 4, 30)
    ).first().id
    s.close()

    r = client.delete(f"/api/cierres/{cierre_abril_id}?cascada=true")
    assert r.status_code == 200
    assert r.json()["borrados"] == 2

    s = client._session_factory()
    assert s.query(CierreCaja).count() == 0
    s.close()


def test_post_movimiento_en_caja_cerrada_rechaza_403(client):
    _setup_caja(client)
    s = client._session_factory()
    s.add(CierreCaja(fecha=date(2026, 4, 30), caja="cl", saldo_cierre=Decimal("0")))
    s.commit()
    s.close()

    # Movimiento retroactivo a una caja cerrada → 403
    r = client.post("/api/caja-diaria/movimiento", json={
        "fecha": "2026-04-15",
        "tipo_operacion": "Ingreso",
        "monto": 500,
        "caja_destino": "cl",
    })
    assert r.status_code == 403
    assert "cierre" in r.json()["detail"].lower()


def test_vincular_movimiento_con_factura_de_otro_proveedor_falla(client):
    _setup_caja(client)
    s = client._session_factory()
    p1 = Proveedor(nombre="Prov A")
    p2 = Proveedor(nombre="Prov B")
    s.add_all([p1, p2])
    s.commit()
    s.refresh(p1)
    s.refresh(p2)
    f_de_p2 = FacturaProveedor(
        id_proveedor=p2.id, fecha_emision=date(2026, 4, 1),
        total=Decimal("1000"),
    )
    s.add(f_de_p2)
    s.commit()
    s.refresh(f_de_p2)
    mov = MovimientoCaja(
        fecha=date(2026, 4, 5), tipo_operacion="Materia Prima",
        monto=Decimal("1000"), caja_origen="cl",
        hash_dedupe="hcross",
    )
    s.add(mov)
    s.commit()
    s.refresh(mov)
    p1_id, mov_id, factura_id = p1.id, mov.id, f_de_p2.id
    s.close()

    # Intento vincular factura de p2 declarando que estoy en p1 → 400
    r = client.post(
        f"/api/proveedores/movimiento/{mov_id}/vincular",
        json={"id_factura": factura_id, "id_proveedor": p1_id},
    )
    assert r.status_code == 400
    assert "pertenece" in r.json()["detail"].lower()


def test_anular_factura_la_excluye_y_desvincula_pagos(client):
    _setup_caja(client)
    s = client._session_factory()
    p = Proveedor(nombre="Prov X")
    s.add(p)
    s.commit()
    s.refresh(p)
    f = FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date(2026, 4, 1),
        total=Decimal("5000"),
    )
    s.add(f)
    s.commit()
    s.refresh(f)
    mov = MovimientoCaja(
        fecha=date(2026, 4, 10), tipo_operacion="Materia Prima",
        monto=Decimal("2000"), caja_origen="cl",
        id_factura_proveedor=f.id, hash_dedupe="hp_an",
    )
    s.add(mov)
    s.commit()
    factura_id, mov_id = f.id, mov.id
    s.close()

    r = client.post(
        f"/api/proveedores/factura/{factura_id}/anular",
        json={"motivo": "carga duplicada"},
    )
    assert r.status_code == 200
    assert r.json()["pagos_desvinculados"] == 1

    # La factura ya no aparece en saldo
    listado = client.get("/api/proveedores").json()
    assert listado[0]["facturado_total"] == 0.0
    # El movimiento quedó desvinculado (id_factura_proveedor=None) y con traza
    s = client._session_factory()
    m = s.get(MovimientoCaja, mov_id)
    assert m.id_factura_proveedor is None
    assert f"ex-factura #{factura_id}" in (m.detalle or "")
    assert "anulada" in (m.detalle or "")
    # observaciones tiene la marca
    f2 = s.get(FacturaProveedor, factura_id)
    assert f2.anulada is True
    assert "ANULADA" in (f2.observaciones or "")
    s.close()


def test_anular_factura_dos_veces_falla(client):
    _setup_caja(client)
    s = client._session_factory()
    p = Proveedor(nombre="Prov Y")
    s.add(p)
    s.commit()
    s.refresh(p)
    f = FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date(2026, 4, 1),
        total=Decimal("100"), anulada=True,
    )
    s.add(f)
    s.commit()
    factura_id = f.id
    s.close()

    r = client.post(f"/api/proveedores/factura/{factura_id}/anular", json={})
    assert r.status_code == 409


def test_editar_factura_metadata_ok(client):
    _setup_caja(client)
    s = client._session_factory()
    p = Proveedor(nombre="Prov M")
    s.add(p)
    s.commit()
    s.refresh(p)
    f = FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date(2026, 4, 1),
        total=Decimal("1000"), numero="F-1",
    )
    s.add(f)
    s.commit()
    factura_id = f.id
    s.close()

    r = client.patch(f"/api/proveedores/factura/{factura_id}", json={
        "numero": "F-99", "descripcion": "actualizada",
        "fecha_vencimiento": "2026-05-15",
    })
    assert r.status_code == 200

    s = client._session_factory()
    f2 = s.get(FacturaProveedor, factura_id)
    assert f2.numero == "F-99"
    assert f2.descripcion == "actualizada"
    assert f2.fecha_vencimiento == date(2026, 5, 15)
    assert f2.total == Decimal("1000")  # no cambió
    s.close()


def test_editar_factura_total_con_pagos_falla(client):
    _setup_caja(client)
    s = client._session_factory()
    p = Proveedor(nombre="Prov P")
    s.add(p)
    s.commit()
    s.refresh(p)
    f = FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date(2026, 4, 1),
        total=Decimal("1000"),
    )
    s.add(f)
    s.commit()
    s.refresh(f)
    mov = MovimientoCaja(
        fecha=date(2026, 4, 5), tipo_operacion="Materia Prima",
        monto=Decimal("500"), caja_origen="cl",
        id_factura_proveedor=f.id, hash_dedupe="hp_edit",
    )
    s.add(mov)
    s.commit()
    factura_id = f.id
    s.close()

    r = client.patch(f"/api/proveedores/factura/{factura_id}", json={"total": 2000})
    assert r.status_code == 409
    assert "pagos vinculados" in r.json()["detail"].lower()


def test_editar_factura_null_limpia_campos_opcionales(client):
    """Semántica RFC 7396: null explícito en payload limpia el campo."""
    _setup_caja(client)
    s = client._session_factory()
    p = Proveedor(nombre="Prov N")
    s.add(p)
    s.commit()
    s.refresh(p)
    f = FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date(2026, 4, 1),
        fecha_vencimiento=date(2026, 5, 1),
        total=Decimal("100"), numero="R-1234", descripcion="remito por error",
    )
    s.add(f)
    s.commit()
    factura_id = f.id
    s.close()

    r = client.patch(f"/api/proveedores/factura/{factura_id}", json={
        "numero": None,
        "fecha_vencimiento": None,
        "descripcion": None,
    })
    assert r.status_code == 200

    s = client._session_factory()
    f2 = s.get(FacturaProveedor, factura_id)
    assert f2.numero is None
    assert f2.fecha_vencimiento is None
    assert f2.descripcion is None
    # los campos no enviados quedan intactos
    assert f2.total == Decimal("100")
    assert f2.fecha_emision == date(2026, 4, 1)
    s.close()


def test_editar_factura_campo_ausente_no_toca(client):
    """Campo ausente del JSON no debe cambiar el valor en DB."""
    _setup_caja(client)
    s = client._session_factory()
    p = Proveedor(nombre="Prov A2")
    s.add(p)
    s.commit()
    s.refresh(p)
    f = FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date(2026, 4, 1),
        total=Decimal("500"), numero="F-1", descripcion="original",
    )
    s.add(f)
    s.commit()
    factura_id = f.id
    s.close()

    # Solo cambiamos numero — descripcion y total quedan intactos
    r = client.patch(f"/api/proveedores/factura/{factura_id}", json={"numero": "F-2"})
    assert r.status_code == 200

    s = client._session_factory()
    f2 = s.get(FacturaProveedor, factura_id)
    assert f2.numero == "F-2"
    assert f2.descripcion == "original"
    assert f2.total == Decimal("500")
    s.close()


def test_editar_factura_total_null_rechaza(client):
    _setup_caja(client)
    s = client._session_factory()
    p = Proveedor(nombre="Prov T")
    s.add(p)
    s.commit()
    s.refresh(p)
    f = FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date(2026, 4, 1), total=Decimal("100"),
    )
    s.add(f)
    s.commit()
    factura_id = f.id
    s.close()

    r = client.patch(f"/api/proveedores/factura/{factura_id}", json={"total": None})
    assert r.status_code == 400


def test_extracto_pdf_proveedor_devuelve_pdf(client):
    """Smoke test: el endpoint PDF responde 200 con content-type pdf y
    bytes que arrancan con %PDF-."""
    _setup_caja(client)
    s = client._session_factory()
    p = Proveedor(nombre="Prov PDF", cuit="30-99999999-9")
    s.add(p)
    s.commit()
    s.refresh(p)
    s.add(FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date(2026, 4, 1),
        total=Decimal("1500"), numero="F-PDF",
    ))
    s.commit()
    pid = p.id
    s.close()

    r = client.get(f"/api/proveedores/{pid}/extracto.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert "extracto_Prov_PDF" in r.headers["content-disposition"]
    assert r.content[:5] == b"%PDF-"


def test_extracto_pdf_proveedor_no_existe_404(client):
    r = client.get("/api/proveedores/99999/extracto.pdf")
    assert r.status_code == 404


def test_extracto_pdf_cliente_devuelve_pdf(client):
    """Smoke test del endpoint PDF de cliente: una venta cta cte y el
    extracto debe responder PDF válido."""
    _setup_caja(client)
    s = client._session_factory()
    s.add(Venta(
        id_pedido="P-PDF-1", id_venta="V-PDF-1",
        id_cliente=77, cliente="Cliente PDF SA",
        fecha=datetime(2026, 4, 15),
        total=Decimal("3000"),
        es_cuenta_corriente=True,
    ))
    s.commit()
    s.close()

    r = client.get("/api/cuentas-corrientes/77/extracto.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert "extracto_Cliente_PDF_SA" in r.headers["content-disposition"]
    assert r.content[:5] == b"%PDF-"


def test_aging_pdf_clientes_devuelve_pdf(client):
    _setup_caja(client)
    s = client._session_factory()
    s.add(Venta(
        id_pedido="P-AG-1", id_venta="V-AG-1",
        id_cliente=88, cliente="Deudor Aging SA",
        fecha=datetime(2026, 1, 1),  # viejo, va al bucket 90+
        total=Decimal("12000"),
        es_cuenta_corriente=True,
    ))
    s.commit()
    s.close()

    r = client.get("/api/cuentas-corrientes/aging.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert "aging_clientes" in r.headers["content-disposition"]
    assert r.content[:5] == b"%PDF-"


def test_aging_pdf_proveedores_devuelve_pdf(client):
    _setup_caja(client)
    s = client._session_factory()
    p = Proveedor(nombre="Prov AGING")
    s.add(p)
    s.commit()
    s.refresh(p)
    s.add(FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date(2026, 1, 1),
        fecha_vencimiento=date(2026, 2, 1),  # vencida hace mucho
        total=Decimal("9000"),
    ))
    s.commit()
    s.close()

    r = client.get("/api/proveedores/aging.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert "aging_proveedores" in r.headers["content-disposition"]
    assert r.content[:5] == b"%PDF-"


def test_aging_pdf_proveedores_vacio_devuelve_pdf(client):
    """Sin facturas pendientes: el PDF se genera igual con texto 'sin saldos'."""
    _setup_caja(client)
    r = client.get("/api/proveedores/aging.pdf")
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"


def test_reporte_mensual_pdf_default_mes_pasado(client):
    """Sin parámetro mes: debe devolver PDF del mes pasado completo."""
    _setup_caja(client)
    r = client.get("/api/dashboard/reporte-mensual.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content[:5] == b"%PDF-"
    assert "reporte_mensual_" in r.headers["content-disposition"]


def test_reporte_mensual_pdf_con_mes_explicito(client):
    """Mes válido YYYY-MM debe parsearse y generar PDF."""
    _setup_caja(client)
    r = client.get("/api/dashboard/reporte-mensual.pdf?mes=2026-04")
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"
    assert "reporte_mensual_2026-04" in r.headers["content-disposition"]


def test_reporte_mensual_pdf_mes_invalido_400(client):
    _setup_caja(client)
    r = client.get("/api/dashboard/reporte-mensual.pdf?mes=2026-13")
    assert r.status_code == 400
    r2 = client.get("/api/dashboard/reporte-mensual.pdf?mes=abril-2026")
    assert r2.status_code == 400


def test_reporte_mensual_pdf_mes_futuro_400(client):
    """Mes íntegramente futuro → 400. Sin esto, dias quedaba negativo y
    el período comparativo se invertía silenciosamente."""
    _setup_caja(client)
    # Año futuro lejano → garantizado fuera de today() sin importar cuándo
    # corra el test.
    futuro = "2099-06"
    r = client.get(f"/api/dashboard/reporte-mensual.pdf?mes={futuro}")
    assert r.status_code == 400
    assert "futuro" in r.json()["detail"].lower()


def test_reporte_mensual_pdf_mes_en_curso_parcial(client):
    """Mes en curso → permitido pero el PDF debe marcarlo como parcial."""
    _setup_caja(client)
    hoy = date.today()
    mes_en_curso = hoy.strftime("%Y-%m")
    r = client.get(f"/api/dashboard/reporte-mensual.pdf?mes={mes_en_curso}")
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"
    # El título "(parcial al DD/MM)" se incrusta en el PDF — buscamos el
    # marker como bytes. PDF puede comprimir/escapear, pero en reportlab
    # con el flow simple suele quedar legible. Búsqueda case-insensitive.
    assert b"parcial al" in r.content.lower() or b"(parcial" in r.content.lower()


def test_clientes_de_producto_endpoint_smoke(client):
    """Smoke test del wiring del endpoint REST: validación de min_length,
    delegación al helper, serialización JSON."""
    _setup_caja(client)
    s = client._session_factory()
    s.add(Venta(id_pedido="P1", id_venta="V1", id_cliente=1,
                cliente="Cliente Test", fecha=datetime(2026, 4, 1),
                total=Decimal("500")))
    s.add(DetalleVenta(id_venta="V1", fecha=datetime(2026, 4, 1), linea_num=1,
                       producto="Detergente", cantidad=Decimal("5"),
                       precio_unitario=Decimal("100"), subtotal=Decimal("500")))
    s.commit()
    s.close()

    # Producto que existe → 200 con un cliente
    r = client.get("/api/kpis/comerciales/clientes-de-producto?producto=Detergente")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["cliente"] == "Cliente Test"
    assert data[0]["cantidad_total"] == 5.0

    # Producto vacío → 422 (min_length=1)
    r2 = client.get("/api/kpis/comerciales/clientes-de-producto?producto=")
    assert r2.status_code == 422

    # Limite fuera de rango → 422
    r3 = client.get("/api/kpis/comerciales/clientes-de-producto?producto=X&limite=999")
    assert r3.status_code == 422


def test_clientes_duplicados_detecta_typos_comunes(client):
    """Clientes con nombres similares (típicos errores de carga) se agrupan."""
    _setup_caja(client)
    s = client._session_factory()
    # Cuatro variantes que deberían normalizar al mismo string:
    s.add(Venta(id_pedido="P1", id_venta="V1", id_cliente=1,
                cliente="Acme SA", fecha=datetime(2026, 4, 1), total=Decimal("100")))
    s.add(Venta(id_pedido="P2", id_venta="V2", id_cliente=2,
                cliente="Acme S.A.", fecha=datetime(2026, 4, 2), total=Decimal("200")))
    s.add(Venta(id_pedido="P3", id_venta="V3", id_cliente=3,
                cliente="ACME S A", fecha=datetime(2026, 4, 3), total=Decimal("300")))
    # Cliente realmente distinto (no debería estar en este grupo):
    s.add(Venta(id_pedido="P4", id_venta="V4", id_cliente=4,
                cliente="Distribuidora Sur", fecha=datetime(2026, 4, 4), total=Decimal("50")))
    s.commit()
    s.close()

    r = client.get("/api/admin/clientes-duplicados-sospechosos")
    assert r.status_code == 200
    data = r.json()
    # Debería haber al menos 1 grupo (los 3 Acme)
    assert data["total_grupos"] >= 1
    grupo_acme = next(
        (g for g in data["grupos"] if "acme" in g["nombre_normalizado"]),
        None,
    )
    assert grupo_acme is not None
    assert len(grupo_acme["clientes"]) == 3
    ids = {c["id_cliente"] for c in grupo_acme["clientes"]}
    assert ids == {1, 2, 3}


def test_clientes_duplicados_ignora_tildes_y_puntuacion(client):
    """Tildes y puntuación distintas no deben considerarse diferencias."""
    _setup_caja(client)
    s = client._session_factory()
    s.add(Venta(id_pedido="P1", id_venta="V1", id_cliente=1,
                cliente="Café Río", fecha=datetime(2026, 4, 1), total=Decimal("100")))
    s.add(Venta(id_pedido="P2", id_venta="V2", id_cliente=2,
                cliente="cafe rio", fecha=datetime(2026, 4, 2), total=Decimal("100")))
    s.commit()
    s.close()

    r = client.get("/api/admin/clientes-duplicados-sospechosos")
    grupos = r.json()["grupos"]
    # Los 2 deberían estar en el mismo grupo
    assert any(len(g["clientes"]) == 2 for g in grupos)


def test_clientes_duplicados_no_borra_sa_intermedio(client):
    """Regresión: el regex de sufijos NO debe borrar 'Sa' en medio del nombre.
    'Don Sa Pedro' y 'Don Pedro' son clientes distintos, no deben agrupar.
    Sin el ancla `$` al final del regex, el sufijo se borraba incluso si
    aparecía intermedio."""
    _setup_caja(client)
    s = client._session_factory()
    s.add(Venta(id_pedido="P1", id_venta="V1", id_cliente=1,
                cliente="Don Sa Pedro", fecha=datetime(2026, 4, 1), total=Decimal("100")))
    s.add(Venta(id_pedido="P2", id_venta="V2", id_cliente=2,
                cliente="Don Pedro", fecha=datetime(2026, 4, 2), total=Decimal("100")))
    s.commit()
    s.close()

    r = client.get("/api/admin/clientes-duplicados-sospechosos")
    # Estos NO deben agruparse: son nombres con tokens distintos.
    assert r.json()["total_grupos"] == 0


def test_movimientos_duplicados_detecta_repetidos(client):
    """Dos movs con misma fecha+monto+caja+tipo_op pero detalle distinto
    pasan el dedupe del import (hash incluye detalle) y deben aparecer
    como sospechosos."""
    _setup_caja(client)
    s = client._session_factory()
    s.add(MovimientoCaja(
        fecha=date(2026, 4, 1), tipo_operacion="Sueldo",
        monto=Decimal("100000"), caja_origen="cl",
        detalle="Pago Juan", hash_dedupe="hmd1",
    ))
    s.add(MovimientoCaja(
        fecha=date(2026, 4, 1), tipo_operacion="Sueldo",
        monto=Decimal("100000"), caja_origen="cl",
        detalle="sueldo Juan",  # Detalle distinto pero mismos campos clave
        hash_dedupe="hmd2",
    ))
    s.commit()
    s.close()

    r = client.get("/api/admin/movimientos-duplicados-sospechosos")
    assert r.status_code == 200
    data = r.json()
    assert data["total_grupos"] == 1
    g = data["grupos"][0]
    assert g["cantidad"] == 2
    assert len(g["movimientos"]) == 2
    detalles = {m["detalle"] for m in g["movimientos"]}
    assert detalles == {"Pago Juan", "sueldo Juan"}


def test_movimientos_duplicados_orden_por_monto_desc(client):
    """Grupos ordenados por monto desc (mayor impacto arriba)."""
    _setup_caja(client)
    s = client._session_factory()
    # Grupo barato (2 movs de $100)
    s.add(MovimientoCaja(fecha=date(2026, 4, 1), tipo_operacion="Op",
                          monto=Decimal("100"), caja_origen="cl",
                          detalle="A", hash_dedupe="hmd_a1"))
    s.add(MovimientoCaja(fecha=date(2026, 4, 1), tipo_operacion="Op",
                          monto=Decimal("100"), caja_origen="cl",
                          detalle="B", hash_dedupe="hmd_a2"))
    # Grupo caro (2 movs de $50000)
    s.add(MovimientoCaja(fecha=date(2026, 4, 2), tipo_operacion="Op",
                          monto=Decimal("50000"), caja_origen="cl",
                          detalle="X", hash_dedupe="hmd_b1"))
    s.add(MovimientoCaja(fecha=date(2026, 4, 2), tipo_operacion="Op",
                          monto=Decimal("50000"), caja_origen="cl",
                          detalle="Y", hash_dedupe="hmd_b2"))
    s.commit()
    s.close()

    r = client.get("/api/admin/movimientos-duplicados-sospechosos")
    grupos = r.json()["grupos"]
    assert grupos[0]["monto"] == 50000.0
    assert grupos[1]["monto"] == 100.0


def test_movimientos_duplicados_sin_repetidos_lista_vacia(client):
    _setup_caja(client)
    s = client._session_factory()
    s.add(MovimientoCaja(fecha=date(2026, 4, 1), tipo_operacion="Op1",
                          monto=Decimal("100"), caja_origen="cl",
                          hash_dedupe="hu1"))
    s.add(MovimientoCaja(fecha=date(2026, 4, 1), tipo_operacion="Op2",
                          monto=Decimal("100"), caja_origen="cl",
                          hash_dedupe="hu2"))
    s.commit()
    s.close()

    r = client.get("/api/admin/movimientos-duplicados-sospechosos")
    assert r.json()["total_grupos"] == 0


def test_clientes_duplicados_sin_duplicados_lista_vacia(client):
    """Clientes todos distintos → total_grupos = 0."""
    _setup_caja(client)
    s = client._session_factory()
    s.add(Venta(id_pedido="P1", id_venta="V1", id_cliente=1,
                cliente="Acme", fecha=datetime(2026, 4, 1), total=Decimal("100")))
    s.add(Venta(id_pedido="P2", id_venta="V2", id_cliente=2,
                cliente="Otra Empresa", fecha=datetime(2026, 4, 2), total=Decimal("100")))
    s.commit()
    s.close()

    r = client.get("/api/admin/clientes-duplicados-sospechosos")
    assert r.json()["total_grupos"] == 0


def test_export_json_devuelve_payload_estructurado(client):
    """Smoke + estructura: el JSON debe tener `tablas` con todas las
    entidades clave + `exportado_en` ISO + cada tabla con su contador."""
    _setup_caja(client)
    s = client._session_factory()
    s.add(Venta(
        id_pedido="P-EX-1", id_venta="V-EX-1",
        id_cliente=1, cliente="Cliente Export",
        fecha=datetime(2026, 4, 1), total=Decimal("100"),
    ))
    s.commit()
    s.close()

    r = client.get("/api/admin/export.json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert "kpi_export_" in r.headers["content-disposition"]

    data = r.json()
    assert "exportado_en" in data
    assert "schema_version" in data
    for nombre in [
        "ventas", "detalle_ventas", "movimientos_caja",
        "proveedores", "facturas_proveedor", "cierres_caja", "pagos_aplicados",
    ]:
        assert nombre in data["tablas"], f"falta {nombre}"
        assert f"{nombre}__total" in data["tablas"]

    # La venta sembrada está
    assert data["tablas"]["ventas__total"] == 1
    venta = data["tablas"]["ventas"][0]
    assert venta["id_pedido"] == "P-EX-1"
    # Decimal serializado como string para preservar precisión.
    # Numeric(14,2) almacena con 2 decimales, así "100" → "100.00".
    assert venta["total"] in ("100", "100.00")


def test_export_json_vacio_devuelve_estructura_completa(client):
    """Sin datos, el JSON debe igual tener todas las tablas con [] vacío."""
    _setup_caja(client)
    r = client.get("/api/admin/export.json")
    assert r.status_code == 200
    data = r.json()
    assert data["tablas"]["ventas"] == []
    assert data["tablas"]["ventas__total"] == 0


def test_health_check_devuelve_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "uptime_segundos" in body


def test_health_check_db_caida_devuelve_503(client):
    """Si la DB no responde, el endpoint debe devolver 503 sin filtrar el
    detalle del error (solo categoría). Es el caso de uso del endpoint —
    sin este test, no hay cobertura de la rama de error."""
    # Reemplazamos el override de get_db para que la sesión tire al ejecutar.
    def db_rota_override():
        class SesionRota:
            def execute(self, *a, **kw):
                raise RuntimeError("simulación: DB no responde")
            def close(self):
                pass
        s = SesionRota()
        try:
            yield s
        finally:
            s.close()

    from app.db import get_db
    fastapi_app.dependency_overrides[get_db] = db_rota_override
    try:
        r = client.get("/api/health")
    finally:
        # Restaurar el override original (el del fixture client)
        fastapi_app.dependency_overrides[get_db] = client.app.dependency_overrides.get(get_db)
    assert r.status_code == 503
    detail = r.json()["detail"]
    # No debe filtrar el error real ("simulación") — solo categoría
    assert "simulación" not in detail
    assert "DB" in detail or "responde" in detail.lower()


def test_ultima_actividad_devuelve_estructura(client):
    """Sin datos cargados, ultima_carga debe ser None pero la estructura
    de respuesta debe estar completa (no falla por queries vacías)."""
    _setup_caja(client)
    r = client.get("/api/admin/ultima-actividad")
    assert r.status_code == 200
    body = r.json()
    assert "ventas" in body
    assert "movimientos_caja" in body
    assert "facturas_proveedor" in body
    # Sin datos, ultima_carga debería ser None
    assert body["ventas"]["total_filas"] == 0
    assert body["ventas"]["ultima_carga"] is None


def test_ultima_actividad_con_datos(client):
    _setup_caja(client)
    s = client._session_factory()
    s.add(Venta(
        id_pedido="P-UA-1", id_venta="V-UA-1",
        id_cliente=1, cliente="C",
        fecha=datetime(2026, 4, 1),
        total=Decimal("100"),
    ))
    s.commit()
    s.close()

    r = client.get("/api/admin/ultima-actividad")
    assert r.status_code == 200
    body = r.json()
    assert body["ventas"]["total_filas"] == 1
    assert body["ventas"]["ultima_carga"] is not None


def test_resumen_diario_pdf_default_hoy(client):
    """Sin fecha: usa hoy. Debe devolver PDF aunque no haya movs."""
    _setup_caja(client)
    r = client.get("/api/caja-diaria/resumen-diario.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content[:5] == b"%PDF-"
    assert "resumen_diario_" in r.headers["content-disposition"]


def test_resumen_diario_pdf_con_movs(client):
    """Con movimientos del día, el PDF debe ser razonablemente grande."""
    _setup_caja(client)
    s = client._session_factory()
    fecha_test = date.today()
    s.add(MovimientoCaja(
        fecha=fecha_test, tipo_operacion="Ingreso",
        monto=Decimal("5000"), caja_destino="cl",
        detalle="Cobro cliente X", hash_dedupe="hr1",
    ))
    s.add(MovimientoCaja(
        fecha=fecha_test, tipo_operacion="Gasto general",
        monto=Decimal("1500"), caja_origen="cl",
        detalle="Compra insumos", hash_dedupe="hr2",
    ))
    s.commit()
    s.close()

    r = client.get(f"/api/caja-diaria/resumen-diario.pdf?fecha={fecha_test.isoformat()}")
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"
    assert len(r.content) > 2000  # con movs debe ser más grande que el vacío


def test_resumen_diario_pdf_fecha_futura_400(client):
    _setup_caja(client)
    futuro = (date.today() + timedelta(days=10)).isoformat()
    r = client.get(f"/api/caja-diaria/resumen-diario.pdf?fecha={futuro}")
    assert r.status_code == 400


def test_resumen_diario_pdf_fecha_hoy_permitida(client):
    """Caso borde: fecha == hoy NO debe ser 400 (es el caso de uso default)."""
    _setup_caja(client)
    r = client.get(f"/api/caja-diaria/resumen-diario.pdf?fecha={date.today().isoformat()}")
    assert r.status_code == 200


def test_resumen_diario_pdf_transferencia_smoke(client):
    """Una transferencia entre cajas debe generar PDF válido sin romper
    el cálculo de KPIs (ingresos/egresos del día), aunque la lógica de
    "no suma" se valida con el unit test de `saldos_por_caja_al`."""
    _setup_caja(client)
    s = client._session_factory()
    s.add(Caja(nombre_normalizado="cl2", nombre_display="CAJA 2", tipo="operativa"))
    s.commit()
    fecha_test = date.today()
    s.add(MovimientoCaja(
        fecha=fecha_test, tipo_operacion="Transferencia",
        monto=Decimal("10000"), caja_origen="cl", caja_destino="cl2",
        detalle="Mover plata", hash_dedupe="ht1",
    ))
    s.commit()
    s.close()

    r = client.get(f"/api/caja-diaria/resumen-diario.pdf?fecha={fecha_test.isoformat()}")
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"


def test_saldos_por_caja_al_filtra_por_fecha(db):
    """Unit test del helper crítico para retroactivos: `saldos_por_caja_al`
    debe sumar SOLO los movs con `fecha <= corte`, ignorando posteriores.
    Sin esto, el PDF del martes mostraría saldos del jueves (bug semántico
    en reportes financieros)."""
    from app.kpis.caja import saldos_por_caja_al
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 6), tipo_operacion="Ingreso",
        monto=Decimal("5000"), caja_destino="cl", hash_dedupe="hsa1",
    ))
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 7), tipo_operacion="Ingreso",
        monto=Decimal("3000"), caja_destino="cl", hash_dedupe="hsa2",
    ))
    # Mov del miércoles: NO debe entrar en el corte del martes
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 8), tipo_operacion="Ingreso",
        monto=Decimal("9000"), caja_destino="cl", hash_dedupe="hsa3",
    ))
    db.commit()

    saldos_martes = saldos_por_caja_al(db, date(2026, 4, 7))
    cl = next(s for s in saldos_martes if s["caja"] == "CAJA LOCAL")
    assert cl["saldo"] == 8000.0  # 5000 + 3000

    saldos_miercoles = saldos_por_caja_al(db, date(2026, 4, 8))
    cl_mi = next(s for s in saldos_miercoles if s["caja"] == "CAJA LOCAL")
    assert cl_mi["saldo"] == 17000.0  # 5000 + 3000 + 9000


def test_aging_pdf_landscape_con_30_clientes(client):
    """Cuando hay >25 items el helper cambia a A4 landscape para que entren
    los nombres. Smoke test: 30 ventas viejas → PDF se genera sin errores
    y mantiene cabecera %PDF-. La validación visual del layout queda fuera
    de scope (requeriría parsear el PDF), pero al menos confirma que el
    cálculo de columnas con A4 rotado no rompe."""
    _setup_caja(client)
    s = client._session_factory()
    for i in range(30):
        s.add(Venta(
            id_pedido=f"P-LS-{i}", id_venta=f"V-LS-{i}",
            id_cliente=1000 + i,
            cliente=f"Cliente Largo Para Testear Anchos S.A. {i}",
            fecha=datetime(2026, 1, 1),  # bucket 90+
            total=Decimal("1000"),
            es_cuenta_corriente=True,
        ))
    s.commit()
    s.close()

    r = client.get("/api/cuentas-corrientes/aging.pdf")
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"
    # PDF con 30 filas + header + totales debería ser razonablemente grande
    assert len(r.content) > 3000


def test_editar_factura_anulada_falla(client):
    _setup_caja(client)
    s = client._session_factory()
    p = Proveedor(nombre="Prov A")
    s.add(p)
    s.commit()
    s.refresh(p)
    f = FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date(2026, 4, 1),
        total=Decimal("100"), anulada=True,
    )
    s.add(f)
    s.commit()
    factura_id = f.id
    s.close()

    r = client.patch(f"/api/proveedores/factura/{factura_id}", json={"numero": "X"})
    assert r.status_code == 409
