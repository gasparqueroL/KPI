"""Tests del archivado de cajas: saldos_por_caja oculta cajas archivadas
pero los movimientos asociados siguen contribuyendo a las cajas activas."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.kpis.caja import saldo_total, saldos_por_caja
from app.models.caja import Caja
from app.models.movimiento_caja import MovimientoCaja
from app.models.venta import Venta


def test_caja_archivada_no_aparece_en_saldos(db):
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.add(Caja(
        nombre_normalizado="vieja", nombre_display="CAJA VIEJA", tipo="operativa",
        archivado_at=datetime.utcnow(),
    ))
    db.commit()

    saldos = saldos_por_caja(db)
    nombres = {s["caja"] for s in saldos}
    assert "CAJA LOCAL" in nombres
    assert "CAJA VIEJA" not in nombres


def test_movs_de_caja_archivada_siguen_afectando_otra_caja(db):
    """Una transferencia desde caja archivada -> caja activa debe sumar
    a la caja activa (la plata realmente se movió). Solo se oculta la
    fila de la caja archivada misma."""
    db.add(Caja(nombre_normalizado="activa", nombre_display="ACTIVA", tipo="operativa"))
    db.add(Caja(
        nombre_normalizado="vieja", nombre_display="VIEJA", tipo="operativa",
        archivado_at=datetime.utcnow(),
    ))
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 1), tipo_operacion="Transfer",
        monto=Decimal("5000"), caja_origen="vieja", caja_destino="activa",
        hash_dedupe="hx1",
    ))
    db.commit()

    saldos = saldos_por_caja(db)
    # ACTIVA recibió 5000 (ingreso de movimiento). VIEJA está oculta.
    activa = next((s for s in saldos if s["caja"] == "ACTIVA"), None)
    assert activa is not None
    assert activa["saldo"] == 5000.0
    assert "VIEJA" not in {s["caja"] for s in saldos}


def test_saldo_total_excluye_cajas_archivadas(db):
    db.add(Caja(nombre_normalizado="a", nombre_display="A", tipo="operativa"))
    db.add(Caja(
        nombre_normalizado="b", nombre_display="B", tipo="operativa",
        archivado_at=datetime.utcnow(),
    ))
    # B tiene movimientos pero está archivada — no debería aparecer en saldo_total.
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 1), tipo_operacion="Cobranza",
        monto=Decimal("1000"), caja_destino="b",
        hash_dedupe="hsa",
    ))
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 1), tipo_operacion="Cobranza",
        monto=Decimal("2000"), caja_destino="a",
        hash_dedupe="hsa2",
    ))
    db.commit()

    total = saldo_total(db)
    # Solo cuenta 'a' (operativa) — 'b' archivada se ignora.
    assert total["saldo_cajas_operativas"] == 2000.0
    assert total["saldo_total"] == 2000.0


def test_get_or_create_caja_desarchiva_si_vuelve_a_aparecer(db):
    """Si la dueña archiva una caja y luego importa un CSV que la
    referencia, debe desarchivarse automáticamente: la intención es
    que la caja exista (la incluyó en el CSV)."""
    from app.importers.cajas_helper import get_or_create_caja

    norm = Caja.normalizar("CAJA LOCAL")
    caja = Caja(
        nombre_normalizado=norm, nombre_display="CAJA LOCAL", tipo="operativa",
        archivado_at=datetime.utcnow(),
    )
    db.add(caja)
    db.commit()

    cache, creadas = {}, []
    c = get_or_create_caja(db, "CAJA LOCAL", cache, creadas)
    db.commit()

    assert c is not None
    assert c.archivado_at is None  # se desarchivó
    assert creadas == []  # no se creó una nueva, se desarchivó la existente


# ===== Tests de endpoints (HTTP) =====

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
    c._session_factory = Session
    yield c
    fastapi_app.dependency_overrides.clear()


def test_merge_rechaza_destino_archivado(client):
    """No se puede mergear hacia una caja archivada (movs huérfanos en oculto)."""
    s = client._session_factory()
    s.add(Caja(nombre_normalizado="src", nombre_display="SRC", tipo="operativa"))
    s.add(Caja(
        nombre_normalizado="dst", nombre_display="DST", tipo="operativa",
        archivado_at=datetime.utcnow(),
    ))
    s.commit()
    s.close()

    r = client.post("/api/config/cajas/merge", json={"desde": "src", "hacia": "dst"})
    assert r.status_code == 400
    assert "archivada" in r.json()["detail"].lower()


def test_archivar_inactivas_excluye_cajas_con_uso(client):
    """archivar-inactivas NO archiva cajas con movs/ventas; SÍ archiva las vacías."""
    s = client._session_factory()
    # Caja con movs (NO debe archivarse)
    s.add(Caja(nombre_normalizado="conuso", nombre_display="CON USO", tipo="operativa"))
    s.add(MovimientoCaja(
        fecha=date(2026, 4, 1), tipo_operacion="Cobranza",
        monto=Decimal("100"), caja_destino="conuso",
        hash_dedupe="hcu1",
    ))
    # Caja sin movs ni ventas (SÍ debe archivarse)
    s.add(Caja(nombre_normalizado="vacia", nombre_display="VACIA", tipo="operativa"))
    # Caja ya archivada (no debe contarse)
    s.add(Caja(
        nombre_normalizado="yarch", nombre_display="YARCH", tipo="operativa",
        archivado_at=datetime.utcnow(),
    ))
    s.commit()
    s.close()

    r = client.post("/api/config/cajas/archivar-inactivas")
    assert r.status_code == 200
    data = r.json()
    assert data["archivadas"] == 1
    assert data["nombres"] == ["VACIA"]

    # Verificar estado final
    s = client._session_factory()
    cajas_archivadas = {
        c.nombre_normalizado for c in s.query(Caja).filter(Caja.archivado_at.isnot(None)).all()
    }
    assert "vacia" in cajas_archivadas
    assert "conuso" not in cajas_archivadas  # tiene mov, no se archivó
    s.close()


def test_archivar_inactivas_idempotente(client):
    """Re-correr no re-archiva nada."""
    s = client._session_factory()
    s.add(Caja(nombre_normalizado="vacia", nombre_display="VACIA", tipo="operativa"))
    s.commit()
    s.close()

    r1 = client.post("/api/config/cajas/archivar-inactivas")
    assert r1.json()["archivadas"] == 1
    r2 = client.post("/api/config/cajas/archivar-inactivas")
    assert r2.json()["archivadas"] == 0


def test_sugerencias_no_lista_caja_archivada(client):
    """El form de nuevo movimiento NO debe ofrecer cajas archivadas."""
    s = client._session_factory()
    s.add(Caja(nombre_normalizado="activa", nombre_display="ACTIVA", tipo="operativa"))
    s.add(Caja(
        nombre_normalizado="archivada", nombre_display="ARCHIVADA", tipo="operativa",
        archivado_at=datetime.utcnow(),
    ))
    s.commit()
    s.close()

    r = client.get("/api/caja-diaria/sugerencias")
    assert r.status_code == 200
    nombres = {c["nombre_normalizado"] for c in r.json()["cajas"]}
    assert "activa" in nombres
    assert "archivada" not in nombres


def test_alertas_ignora_casos_archivados(client):
    """Caso pendiente archivado no debe generar la alerta de casos pendientes."""
    from app.models.caso_revisar import CasoRevisar
    from app.routers.alertas_router import invalidar_cache
    invalidar_cache()  # cache global entre tests del mismo proceso

    s = client._session_factory()
    s.add(CasoRevisar(
        fuente="ventas", motivo_codigo="x", motivo_descripcion="t",
        datos_originales="{}", estado="pendiente",
        archivado_at=datetime.utcnow(),
    ))
    s.commit()
    s.close()

    r = client.get("/api/alertas?refresh=true")
    assert r.status_code == 200
    payload = r.json()
    alertas = payload.get("alertas", payload) if isinstance(payload, dict) else payload
    codigos = [a["codigo"] for a in alertas]
    assert "casos_pendientes" not in codigos


def test_cierres_saldo_actual_rechaza_caja_archivada(client):
    """saldo-actual no debe calcular saldos de cajas archivadas (incoherente
    con saldos_por_caja que las oculta)."""
    s = client._session_factory()
    s.add(Caja(
        nombre_normalizado="arch", nombre_display="ARCH", tipo="operativa",
        archivado_at=datetime.utcnow(),
    ))
    s.commit()
    s.close()

    r = client.get("/api/cierres/saldo-actual?caja=arch&fecha=2026-04-01")
    assert r.status_code == 400
    assert "archivada" in r.json()["detail"].lower()


def test_sugerencias_caja_rankea_por_uso_historico(client):
    """Para un caso sin_caja, devuelve cajas top usadas para ese tipo_operacion."""
    from app.models.caso_revisar import CasoRevisar
    from app.models.movimiento_caja import MovimientoCaja
    import json as jsonlib

    s = client._session_factory()
    # Catálogo de cajas
    s.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    s.add(Caja(nombre_normalizado="bcc", nombre_display="GASPAR B.CORDOBA", tipo="operativa"))
    s.add(Caja(nombre_normalizado="lemon", nombre_display="LEMON", tipo="operativa"))
    # Caja archivada con uso — NO debe aparecer en sugerencias
    s.add(Caja(
        nombre_normalizado="vieja", nombre_display="VIEJA", tipo="operativa",
        archivado_at=datetime.utcnow(),
    ))
    # 5 cobros con caja_destino=cl, 1 con destino=lemon, 0 con bcc → cl gana
    for i in range(5):
        s.add(MovimientoCaja(
            fecha=date(2026, 4, i + 1), tipo_operacion="Cobranza",
            monto=Decimal("100"), caja_destino="cl",
            hash_dedupe=f"h{i}",
        ))
    s.add(MovimientoCaja(
        fecha=date(2026, 4, 10), tipo_operacion="Cobranza",
        monto=Decimal("50"), caja_destino="lemon",
        hash_dedupe="hl1",
    ))
    # Mov con caja archivada — NO debe contar
    s.add(MovimientoCaja(
        fecha=date(2026, 4, 11), tipo_operacion="Cobranza",
        monto=Decimal("999"), caja_destino="vieja",
        hash_dedupe="hv1",
    ))
    # Caso sin_caja
    caso = CasoRevisar(
        fuente="movimientos_caja", motivo_codigo="sin_caja",
        motivo_descripcion="sin caja",
        datos_originales=jsonlib.dumps({
            "FECHA": "01/05/2026",
            "Tipo de Operación": "Cobranza",
            "MONTO": "100",
        }),
        estado="pendiente",
    )
    s.add(caso)
    s.commit()
    cid = caso.id
    s.close()

    r = client.get(f"/api/casos-revisar/{cid}/sugerencias-caja")
    assert r.status_code == 200
    data = r.json()
    sug = data["sugerencias"]
    nombres = [x["nombre_display"] for x in sug]
    # cl primero (5 usos), después lemon (1 uso). VIEJA archivada no aparece.
    assert "CAJA LOCAL" in nombres
    assert "LEMON" in nombres
    assert "VIEJA" not in nombres
    assert nombres[0] == "CAJA LOCAL"
    # CAJA LOCAL siempre como caja_destino → direccion=entrada
    cl = next(x for x in sug if x["nombre_display"] == "CAJA LOCAL")
    assert cl["direccion"] == "entrada"
    assert cl["usos_destino"] == 5
    assert cl["usos_origen"] == 0


def test_sugerencias_caja_rechaza_caso_archivado(client):
    """Caso archivado no debe devolver sugerencias (HTTP 400)."""
    from app.models.caso_revisar import CasoRevisar
    s = client._session_factory()
    caso = CasoRevisar(
        fuente="movimientos_caja", motivo_codigo="sin_caja",
        motivo_descripcion="t", datos_originales="{}", estado="pendiente",
        archivado_at=datetime.utcnow(),
    )
    s.add(caso)
    s.commit()
    cid = caso.id
    s.close()

    r = client.get(f"/api/casos-revisar/{cid}/sugerencias-caja")
    assert r.status_code == 400
    assert "archivado" in r.json()["detail"].lower()


def test_sugerencias_caja_rechaza_caso_no_pendiente(client):
    """Casos descartado/corregido no admiten sugerencias (HTTP 400)."""
    from app.models.caso_revisar import CasoRevisar
    s = client._session_factory()
    caso = CasoRevisar(
        fuente="movimientos_caja", motivo_codigo="sin_caja",
        motivo_descripcion="t", datos_originales="{}", estado="descartado",
    )
    s.add(caso)
    s.commit()
    cid = caso.id
    s.close()

    r = client.get(f"/api/casos-revisar/{cid}/sugerencias-caja")
    assert r.status_code == 400
    assert "descartado" in r.json()["detail"].lower()


def test_sugerencias_caja_no_movimientos_devuelve_vacio(client):
    """Caso de fuente distinta a movimientos_caja: lista vacía con razón."""
    from app.models.caso_revisar import CasoRevisar
    s = client._session_factory()
    caso = CasoRevisar(
        fuente="ventas", motivo_codigo="x", motivo_descripcion="t",
        datos_originales="{}", estado="pendiente",
    )
    s.add(caso)
    s.commit()
    cid = caso.id
    s.close()

    r = client.get(f"/api/casos-revisar/{cid}/sugerencias-caja")
    assert r.status_code == 200
    data = r.json()
    assert data["sugerencias"] == []
    assert "movimientos_caja" in data["razon"]


def test_cierres_cerrar_rechaza_caja_archivada(client):
    """No se puede registrar un cierre contra una caja archivada."""
    s = client._session_factory()
    s.add(Caja(
        nombre_normalizado="arch", nombre_display="ARCH", tipo="operativa",
        archivado_at=datetime.utcnow(),
    ))
    s.commit()
    s.close()

    r = client.post("/api/cierres", json={
        "fecha": "2026-04-01",
        "caja": "arch",
        "saldo_cierre": 1000.0,
    })
    assert r.status_code == 400
    assert "archivada" in r.json()["detail"].lower()
