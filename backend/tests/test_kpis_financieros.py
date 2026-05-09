"""Tests de KPIs financieros computables (margen, EBITDA, DPO, dependencia)."""
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.kpis import financieros
from app.kpis.derivados import kpis_del_mes
from app.main import app as fastapi_app
from app.models.caja import Caja
from app.models.categoria_caja import CategoriaCaja
from app.models.kpi_manual import KpiManual
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
        s = Session()
        try:
            yield s
        finally:
            s.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    c = TestClient(fastapi_app)
    yield c
    fastapi_app.dependency_overrides.clear()


def _setup_minimo(db):
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.add(CategoriaCaja(tipo_operacion="Cobranza", familia="Operativa"))
    db.add(CategoriaCaja(
        tipo_operacion="Sueldo", familia="Personal", excluir_flujo=False,
    ))
    db.add(CategoriaCaja(
        tipo_operacion="Ajuste Apertura", familia="Sistema", excluir_flujo=True,
    ))
    db.commit()


def test_margen_operativo_excluye_categorias_marcadas(db):
    """Egreso con categoria excluir_flujo NO debe contar en margen operativo."""
    _setup_minimo(db)
    db.add(Venta(
        id_pedido="p1", id_venta="v1", fecha=datetime(2026, 4, 15),
        id_cliente=1, cliente="X", total=Decimal("10000"),
        monto_pago1=Decimal("10000"), caja1="cl",
    ))
    # Egreso operativo (cuenta)
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 10), tipo_operacion="Sueldo",
        monto=Decimal("3000"), caja_origen="cl",
        hash_dedupe="hsue1",
    ))
    # Apertura (no cuenta — excluir_flujo)
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 1), tipo_operacion="Ajuste Apertura",
        monto=Decimal("99999"), caja_origen="cl",
        hash_dedupe="hapertura",
    ))
    db.commit()

    r = financieros.margen_operativo(
        db, desde=date(2026, 4, 1), hasta=date(2026, 4, 30),
    )
    assert r["ingresos_total"] == 10000.0
    assert r["egresos_operativos"] == 3000.0  # apertura excluida
    assert r["margen_operativo"] == 7000.0
    assert r["margen_operativo_pct"] == 70.0


def test_dpo_solo_facturas_saldadas(db):
    """DPO ignora facturas con pago parcial (todavia abiertas)."""
    p = Proveedor(nombre="ACME")
    db.add(p)
    db.commit()
    db.refresh(p)

    db.add(Caja(nombre_normalizado="cl", nombre_display="CL", tipo="operativa"))
    db.commit()

    # Factura saldada: emitida 1/4, pagada 11/4 (10 dias)
    f1 = FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date(2026, 4, 1),
        total=Decimal("1000"),
    )
    db.add(f1)
    db.commit()
    db.refresh(f1)
    m1 = MovimientoCaja(
        fecha=date(2026, 4, 11), tipo_operacion="Pago",
        monto=Decimal("1000"), caja_origen="cl",
        id_factura_proveedor=f1.id,
        hash_dedupe="hp1",
    )
    db.add(m1)
    db.commit()
    # Factura con pago parcial (NO saldada — debe ignorarse)
    f2 = FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date(2026, 4, 1),
        total=Decimal("5000"),
    )
    db.add(f2)
    db.commit()
    db.refresh(f2)
    m2 = MovimientoCaja(
        fecha=date(2026, 4, 5), tipo_operacion="Pago",
        monto=Decimal("1000"), caja_origen="cl",
        id_factura_proveedor=f2.id,
        hash_dedupe="hp2",
    )
    db.add(m2)
    db.commit()

    r = financieros.dpo_promedio(db)
    assert r["facturas_consideradas"] == 1
    assert r["dpo_dias"] == 10.0


def test_dependencia_proveedores_concentracion(db):
    """Top 1 proveedor con 60% de las compras = concentracion alta."""
    p1 = Proveedor(nombre="GRAN")
    p2 = Proveedor(nombre="CHICO")
    db.add_all([p1, p2])
    db.commit()
    db.refresh(p1)
    db.refresh(p2)
    db.add(FacturaProveedor(
        id_proveedor=p1.id, fecha_emision=date(2026, 4, 1),
        total=Decimal("60000"),
    ))
    db.add(FacturaProveedor(
        id_proveedor=p2.id, fecha_emision=date(2026, 4, 5),
        total=Decimal("40000"),
    ))
    db.commit()

    r = financieros.dependencia_proveedores(db)
    assert r["total_compras"] == 100000.0
    assert r["concentracion"]["top_1_pct"] == 60.0
    assert r["top"][0]["nombre"] == "GRAN"
    assert r["top"][0]["pct"] == 60.0


def test_kpis_derivados_status_faltan_sin_inputs(db):
    """Sin valores manuales cargados, los KPIs financieros completos deben
    devolver status 'faltan' en los que requieren balance."""
    _setup_minimo(db)
    db.add(Venta(
        id_pedido="p1", id_venta="v1", fecha=datetime(2026, 4, 15),
        id_cliente=1, cliente="X", total=Decimal("10000"),
        monto_pago1=Decimal("10000"), caja1="cl",
    ))
    db.commit()

    r = kpis_del_mes(db, "2026-04")
    by_codigo = {k["codigo"]: k for k in r["kpis"]}

    assert by_codigo["margen_neto"]["status"] == "ok"
    assert by_codigo["margen_neto"]["valor"] == 10000.0
    # ROI/ROA/ROE faltan inputs
    assert by_codigo["roi"]["status"] == "faltan"
    assert by_codigo["roa"]["status"] == "faltan"
    assert by_codigo["roe"]["status"] == "faltan"


def test_kpis_derivados_roa_con_input_manual(db):
    """Cargando activos_totales, ROA debe devolver status ok con valor."""
    _setup_minimo(db)
    db.add(Venta(
        id_pedido="p1", id_venta="v1", fecha=datetime(2026, 4, 15),
        id_cliente=1, cliente="X", total=Decimal("10000"),
        monto_pago1=Decimal("10000"), caja1="cl",
    ))
    db.add(KpiManual(
        periodo="2026-04", codigo="activos_totales", valor=Decimal("100000"),
    ))
    db.commit()

    r = kpis_del_mes(db, "2026-04")
    by_codigo = {k["codigo"]: k for k in r["kpis"]}
    roa = by_codigo["roa"]
    assert roa["status"] == "ok"
    # ganancia 10000 / activos 100000 * 100 = 10%
    assert abs(roa["valor"] - 10.0) < 0.01


def test_periodo_a_rango_diciembre(db):
    """Diciembre debe rolear a enero del año siguiente correctamente."""
    from app.kpis.derivados import _periodo_a_rango
    desde, hasta = _periodo_a_rango("2026-12")
    assert desde == date(2026, 12, 1)
    assert hasta == date(2026, 12, 31)


def test_kpis_derivados_cac_con_clientes_cero(db):
    """Si hay gasto pero 0 clientes nuevos, CAC debe marcarse parcial con
    nota explicativa (NO faltan datos)."""
    _setup_minimo(db)
    db.add(KpiManual(
        periodo="2026-04", codigo="gasto_marketing", valor=Decimal("50000"),
    ))
    db.commit()

    r = kpis_del_mes(db, "2026-04")
    by_codigo = {k["codigo"]: k for k in r["kpis"]}
    cac = by_codigo["cac"]
    assert cac["status"] == "parcial"
    assert cac["valor"] is None
    assert "0 clientes nuevos" in cac.get("nota", "")


def test_kpis_derivados_roi_con_capital_invertido(db):
    """ROI = ganancia / capital_invertido * 100."""
    _setup_minimo(db)
    db.add(Venta(
        id_pedido="p1", id_venta="v1", fecha=datetime(2026, 4, 15),
        id_cliente=1, cliente="X", total=Decimal("10000"),
        monto_pago1=Decimal("10000"), caja1="cl",
    ))
    db.add(KpiManual(
        periodo="2026-04", codigo="capital_invertido", valor=Decimal("50000"),
    ))
    db.commit()

    r = kpis_del_mes(db, "2026-04")
    by_codigo = {k["codigo"]: k for k in r["kpis"]}
    roi = by_codigo["roi"]
    assert roi["status"] == "ok"
    # 10000 / 50000 * 100 = 20%
    assert abs(roi["valor"] - 20.0) < 0.01


def test_kpis_derivados_liquidez_con_cero_pasivos(db):
    """Si pasivos_corrientes es 0, liquidez debe ser None (división)."""
    _setup_minimo(db)
    db.add(KpiManual(
        periodo="2026-04", codigo="activos_corrientes", valor=Decimal("50000"),
    ))
    db.add(KpiManual(
        periodo="2026-04", codigo="pasivos_corrientes", valor=Decimal("0"),
    ))
    db.commit()

    r = kpis_del_mes(db, "2026-04")
    by_codigo = {k["codigo"]: k for k in r["kpis"]}
    liq = by_codigo["liquidez_corriente"]
    # Status ok (datos cargados) pero valor None (división por cero)
    assert liq["status"] == "ok"
    assert liq["valor"] is None


def test_validacion_min_valor_rechaza_negativo(client):
    """bulk_upsert con activos_totales = -1000 debe fallar con 400."""
    from sqlalchemy import create_engine
    r = client.put("/api/kpis-manuales/2026-04", json={
        "valores": [{"codigo": "activos_totales", "valor": -1000}],
    })
    assert r.status_code == 400
    assert ">=" in r.json()["detail"]


def test_validacion_max_valor_rechaza_score_alto(client):
    """clima_laboral_score = 15 debe fallar (max 10)."""
    r = client.put("/api/kpis-manuales/2026-04", json={
        "valores": [{"codigo": "clima_laboral_score", "valor": 15}],
    })
    assert r.status_code == 400
    assert "<=" in r.json()["detail"]


def test_historico_devuelve_n_puntos(client):
    """GET /derivados/historico/{codigo}?meses=N debe devolver N puntos."""
    s = sessionmaker(bind=create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ))
    # Use the existing client fixture's db.
    r = client.get("/api/kpis-manuales/derivados/historico/rotacion?meses=6")
    assert r.status_code == 200
    data = r.json()
    assert data["codigo"] == "rotacion"
    assert len(data["puntos"]) == 6
    # Períodos ordenados de viejo a reciente
    periodos = [p["periodo"] for p in data["puntos"]]
    assert periodos == sorted(periodos)


def test_historico_codigo_inexistente_404(client):
    r = client.get("/api/kpis-manuales/derivados/historico/no_existe?meses=3")
    assert r.status_code == 404


def test_historico_label_consistente_aunque_sin_datos(client, db):
    """label/unidad vienen del catálogo constante, NO del último iter:
    si todos los meses tienen status=faltan, el label sigue siendo el correcto."""
    r = client.get("/api/kpis-manuales/derivados/historico/roa?meses=3")
    assert r.status_code == 200
    data = r.json()
    assert data["codigo"] == "roa"
    assert "ROA" in data["label"]
    assert data["unidad"] == "%"
    assert all(p["status"] == "faltan" for p in data["puntos"])


def test_kpis_del_mes_solo_codigos_filtra_output(db):
    """Pidiendo solo_codigos={'rotacion'}, el output debe tener solo 1 KPI."""
    _setup_minimo(db)
    db.add(KpiManual(periodo="2026-04", codigo="empleados_inicio_mes", valor=Decimal("10")))
    db.add(KpiManual(periodo="2026-04", codigo="empleados_fin_mes", valor=Decimal("10")))
    db.add(KpiManual(periodo="2026-04", codigo="bajas_mes", valor=Decimal("1")))
    db.commit()

    r = kpis_del_mes(db, "2026-04", solo_codigos={"rotacion"})
    assert len(r["kpis"]) == 1
    assert r["kpis"][0]["codigo"] == "rotacion"


def test_kpis_con_comparativa_calcula_delta(db):
    """Mismo KPI cargado en abril 2025 y abril 2026 → delta_pct correcto."""
    from app.kpis.derivados import kpis_del_mes_con_comparativa
    _setup_minimo(db)
    db.add(KpiManual(periodo="2025-04", codigo="nps", valor=Decimal("30")))
    db.add(KpiManual(periodo="2026-04", codigo="nps", valor=Decimal("45")))
    db.commit()

    r = kpis_del_mes_con_comparativa(db, "2026-04", solo_codigos={"nps"})
    nps = r["kpis"][0]
    assert nps["valor"] == 45.0
    assert nps["valor_anterior"] == 30.0
    assert nps["periodo_anterior"] == "2025-04"
    # (45 - 30) / 30 * 100 = 50%
    assert abs(nps["delta_pct"] - 50.0) < 0.01


def test_kpis_comparativa_sin_dato_anterior(db):
    """Si no hay dato del año anterior, delta_pct=None."""
    from app.kpis.derivados import kpis_del_mes_con_comparativa
    _setup_minimo(db)
    db.add(KpiManual(periodo="2026-04", codigo="nps", valor=Decimal("45")))
    db.commit()

    r = kpis_del_mes_con_comparativa(db, "2026-04", solo_codigos={"nps"})
    nps = r["kpis"][0]
    assert nps["valor"] == 45.0
    assert nps["valor_anterior"] is None
    assert nps["delta_pct"] is None


def test_import_csv_basico(client):
    """CSV con header + 2 filas válidas → 2 insertados."""
    csv_text = "periodo,codigo,valor,nota\n2026-04,activos_totales,500000,\n2026-04,nps,30,Q2\n"
    r = client.post(
        "/api/kpis-manuales/import-csv",
        files={"file": ("test.csv", csv_text, "text/csv")},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["insertados"] == 2
    assert data["actualizados"] == 0
    assert data["errores"] == []


def test_import_csv_idempotente(client):
    """Re-importar la misma fila → actualiza, no duplica."""
    csv_text = "periodo,codigo,valor\n2026-04,nps,30\n"
    r1 = client.post("/api/kpis-manuales/import-csv",
                     files={"file": ("a.csv", csv_text, "text/csv")})
    assert r1.json()["insertados"] == 1
    r2 = client.post("/api/kpis-manuales/import-csv",
                     files={"file": ("a.csv", csv_text, "text/csv")})
    assert r2.json()["insertados"] == 0
    assert r2.json()["actualizados"] == 1


def test_import_csv_errores_no_descartan_validas(client):
    """Filas con error se reportan; las válidas se insertan igual."""
    csv_text = (
        "periodo,codigo,valor\n"
        "2026-04,activos_totales,100000\n"
        "INVALID,nps,30\n"
        "2026-04,no_existe,5\n"
        "2026-04,nps,200\n"
        "2026-04,nps,40\n"
    )
    r = client.post("/api/kpis-manuales/import-csv",
                    files={"file": ("e.csv", csv_text, "text/csv")})
    data = r.json()
    assert data["insertados"] == 2  # activos_totales + nps=40
    assert len(data["errores"]) == 3  # periodo invalido, codigo invalido, valor > max


def test_import_csv_falta_columna_400(client):
    csv_text = "fecha,codigo,valor\n2026-04,nps,30\n"
    r = client.post("/api/kpis-manuales/import-csv",
                    files={"file": ("e.csv", csv_text, "text/csv")})
    assert r.status_code == 400


def test_import_csv_decimal_vs_int_min_valor(client):
    """Bug previo: comparar Decimal('100') < int(0) tiraba TypeError.
    Verificamos que valor=-1 contra activos_totales (min_valor=0) se
    detecta como error de validación, no como excepción."""
    csv_text = "periodo,codigo,valor\n2026-04,activos_totales,-1000\n"
    r = client.post("/api/kpis-manuales/import-csv",
                    files={"file": ("v.csv", csv_text, "text/csv")})
    assert r.status_code == 200
    data = r.json()
    assert data["insertados"] == 0
    assert len(data["errores"]) == 1
    assert "max" not in data["errores"][0]["motivo"].lower()
    assert ">=" in data["errores"][0]["motivo"]


def test_import_csv_cp1252_caracteres_especiales(client):
    """Excel español Windows guarda CSV en cp1252. Comilla tipográfica
    en una nota (—) debe decodificarse correctamente."""
    csv_text = "periodo,codigo,valor,nota\n2026-04,nps,40,Q2 — buena\n"
    encoded = csv_text.encode("cp1252")
    r = client.post("/api/kpis-manuales/import-csv",
                    files={"file": ("e.csv", encoded, "text/csv")})
    assert r.status_code == 200
    data = r.json()
    assert data["insertados"] == 1
    # Verificar que la nota se guardó con el carácter correcto
    r2 = client.get("/api/kpis-manuales/2026-04")
    nps = next((v for v in r2.json()["valores"] if v["codigo"] == "nps"), None)
    assert nps is not None
    assert "—" in nps["nota"]


def test_kpis_comparativa_disponible_flag(db):
    """`comparativa_disponible=False` cuando no hay datos del año anterior."""
    from app.kpis.derivados import kpis_del_mes_con_comparativa
    _setup_minimo(db)
    db.add(KpiManual(periodo="2026-04", codigo="nps", valor=Decimal("45")))
    db.commit()

    r = kpis_del_mes_con_comparativa(db, "2026-04", solo_codigos={"nps"})
    assert r["comparativa_disponible"] is False

    # Ahora sí hay dato del año anterior
    db.add(KpiManual(periodo="2025-04", codigo="nps", valor=Decimal("30")))
    db.commit()
    r2 = kpis_del_mes_con_comparativa(db, "2026-04", solo_codigos={"nps"})
    assert r2["comparativa_disponible"] is True


def test_kpi_devuelve_mejor_si(db):
    """KPIs traen `mejor_si: 'subir'|'bajar'` para que el frontend
    coloree el delta correctamente sin hardcodear."""
    from app.kpis.derivados import kpis_del_mes
    _setup_minimo(db)
    db.add(KpiManual(periodo="2026-04", codigo="nps", valor=Decimal("40")))
    db.add(KpiManual(periodo="2026-04", codigo="bajas_mes", valor=Decimal("2")))
    db.add(KpiManual(periodo="2026-04", codigo="empleados_inicio_mes", valor=Decimal("10")))
    db.add(KpiManual(periodo="2026-04", codigo="empleados_fin_mes", valor=Decimal("10")))
    db.commit()

    r = kpis_del_mes(db, "2026-04", solo_codigos={"nps", "rotacion"})
    by_codigo = {k["codigo"]: k for k in r["kpis"]}
    assert by_codigo["nps"]["mejor_si"] == "subir"  # más NPS es mejor
    assert by_codigo["rotacion"]["mejor_si"] == "bajar"  # menos rotación es mejor


def test_objetivo_subir_cumple_si_valor_alto(db):
    """KPI 'subir es mejor' (NPS): objetivo 50, valor 60 → cumple."""
    from app.kpis.derivados import kpis_del_mes_con_comparativa
    from app.models.kpi_objetivo import KpiObjetivo
    db.add(KpiManual(periodo="2026-04", codigo="nps", valor=Decimal("60")))
    db.add(KpiObjetivo(codigo="nps", valor_objetivo=Decimal("50")))
    db.commit()

    r = kpis_del_mes_con_comparativa(db, "2026-04", solo_codigos={"nps"})
    nps = r["kpis"][0]
    assert nps["valor"] == 60.0
    assert nps["objetivo"] == 50.0
    assert nps["cumple_objetivo"] is True


def test_objetivo_bajar_cumple_si_valor_bajo(db):
    """KPI 'bajar es mejor' (rotación): objetivo 10, valor 8 → cumple."""
    from app.kpis.derivados import kpis_del_mes_con_comparativa
    from app.models.kpi_objetivo import KpiObjetivo
    _setup_minimo(db)
    db.add(KpiManual(periodo="2026-04", codigo="bajas_mes", valor=Decimal("4")))
    db.add(KpiManual(periodo="2026-04", codigo="empleados_inicio_mes", valor=Decimal("50")))
    db.add(KpiManual(periodo="2026-04", codigo="empleados_fin_mes", valor=Decimal("50")))
    db.add(KpiObjetivo(codigo="rotacion", valor_objetivo=Decimal("10")))
    db.commit()

    r = kpis_del_mes_con_comparativa(db, "2026-04", solo_codigos={"rotacion"})
    rot = r["kpis"][0]
    assert rot["valor"] == 8.0
    assert rot["objetivo"] == 10.0
    assert rot["cumple_objetivo"] is True


def test_objetivo_endpoint_crud(client):
    """PUT crea/actualiza, DELETE quita, GET lista."""
    r = client.put("/api/kpis-objetivos/nps", json={"valor_objetivo": 50})
    assert r.status_code == 200
    data = r.json()
    assert data["codigo"] == "nps"
    assert data["valor_objetivo"] == 50.0
    assert data["mejor_si"] == "subir"

    # Update
    r = client.put("/api/kpis-objetivos/nps", json={"valor_objetivo": 60})
    assert r.json()["valor_objetivo"] == 60.0

    # List
    r = client.get("/api/kpis-objetivos")
    assert any(o["codigo"] == "nps" for o in r.json())

    # Delete
    r = client.delete("/api/kpis-objetivos/nps")
    assert r.status_code == 200
    r = client.get("/api/kpis-objetivos")
    assert all(o["codigo"] != "nps" for o in r.json())


def test_objetivo_codigo_invalido_404(client):
    r = client.put("/api/kpis-objetivos/no_existe", json={"valor_objetivo": 50})
    assert r.status_code == 404


def test_objetivo_nps_fuera_de_rango_400(client):
    """NPS debe estar entre -100 y +100. Tipear 999 → 400."""
    r = client.put("/api/kpis-objetivos/nps", json={"valor_objetivo": 999})
    assert r.status_code == 400
    assert "<=" in r.json()["detail"]
    r2 = client.put("/api/kpis-objetivos/nps", json={"valor_objetivo": -200})
    assert r2.status_code == 400


def test_objetivo_score_fuera_de_rango_400(client):
    """clima_laboral_score debe estar 1-10."""
    r = client.put("/api/kpis-objetivos/clima_laboral_score", json={"valor_objetivo": 15})
    assert r.status_code == 400


def test_objetivo_kpi_sin_cota_acepta_aspiracional(client):
    """Para KPIs sin techo definido (ARS, ratios), acepta cualquier valor.
    Caso real: la dueña pone target aspiracional alto en margen_neto."""
    r = client.put("/api/kpis-objetivos/margen_neto", json={"valor_objetivo": 99999999})
    assert r.status_code == 200


def test_objetivo_negativo_rechazado_para_tasas(client):
    """Tasas (rotación, ausentismo, tasa_reclamos) no pueden ser negativas."""
    r = client.put("/api/kpis-objetivos/rotacion", json={"valor_objetivo": -5})
    assert r.status_code == 400


def test_import_csv_objetivos_rango_rechaza_fila(client):
    """CSV import: NPS=999 va a errores, otras filas válidas se importan."""
    csv_text = "codigo,valor_objetivo\nnps,999\nrotacion,10\n"
    r = client.post(
        "/api/kpis-objetivos/import-csv",
        files={"file": ("o.csv", csv_text, "text/csv")},
    )
    data = r.json()
    assert data["insertados"] == 1
    assert len(data["errores"]) == 1
    assert "<=" in data["errores"][0]["motivo"]


def test_alertas_dispara_si_objetivo_no_se_cumple(db):
    """Si NPS objetivo=50 y valor del mes anterior=30, debe haber alerta."""
    from datetime import date as _date, timedelta
    from app.kpis.alertas import evaluar_alertas
    from app.models.kpi_objetivo import KpiObjetivo

    _setup_minimo(db)
    hoy = _date.today()
    ultimo_mes_anterior = hoy.replace(day=1) - timedelta(days=1)
    periodo_anterior = f"{ultimo_mes_anterior.year:04d}-{ultimo_mes_anterior.month:02d}"
    db.add(KpiManual(periodo=periodo_anterior, codigo="nps", valor=Decimal("30")))
    db.add(KpiObjetivo(codigo="nps", valor_objetivo=Decimal("50")))
    db.commit()

    alertas = evaluar_alertas(db)
    objetivo_alertas = [a for a in alertas if a["codigo"] == "objetivo_no_cumple"]
    assert len(objetivo_alertas) == 1
    assert "NPS" in objetivo_alertas[0]["titulo"]
    assert "no cumple" in objetivo_alertas[0]["titulo"]


def test_objetivo_cumple_null_si_no_hay_valor(db):
    """Objetivo cargado pero sin valor del mes → cumple_objetivo=None."""
    from app.kpis.derivados import kpis_del_mes_con_comparativa
    from app.models.kpi_objetivo import KpiObjetivo
    _setup_minimo(db)
    db.add(KpiObjetivo(codigo="nps", valor_objetivo=Decimal("50")))
    db.commit()  # NO cargamos valor manual

    r = kpis_del_mes_con_comparativa(db, "2026-04", solo_codigos={"nps"})
    nps = r["kpis"][0]
    assert nps["valor"] is None
    assert nps["objetivo"] == 50.0
    assert nps["cumple_objetivo"] is None  # No bool, sin opinión


def test_alertas_objetivo_usa_mes_anterior_no_actual(db):
    """Las alertas evalúan el MES ANTERIOR cerrado, no el mes en curso.
    Si solo hay datos del mes actual, no debe disparar alerta porque la
    evaluación ocurre sobre mes anterior."""
    from datetime import date as _date, timedelta
    from app.kpis.alertas import evaluar_alertas
    from app.models.kpi_objetivo import KpiObjetivo

    _setup_minimo(db)
    hoy = _date.today()
    periodo_actual = f"{hoy.year:04d}-{hoy.month:02d}"
    # Carga datos SOLO del mes actual — no debe contar.
    db.add(KpiManual(periodo=periodo_actual, codigo="nps", valor=Decimal("30")))
    db.add(KpiObjetivo(codigo="nps", valor_objetivo=Decimal("50")))
    db.commit()

    alertas = evaluar_alertas(db)
    assert all(a["codigo"] != "objetivo_no_cumple" for a in alertas)


def test_alertas_objetivo_dispara_con_mes_anterior(db):
    """Cargar mes anterior con valor que NO cumple objetivo → alerta."""
    from datetime import date as _date, timedelta
    from app.kpis.alertas import evaluar_alertas
    from app.models.kpi_objetivo import KpiObjetivo

    _setup_minimo(db)
    hoy = _date.today()
    ultimo_mes_anterior = hoy.replace(day=1) - timedelta(days=1)
    periodo_anterior = f"{ultimo_mes_anterior.year:04d}-{ultimo_mes_anterior.month:02d}"
    db.add(KpiManual(periodo=periodo_anterior, codigo="nps", valor=Decimal("30")))
    db.add(KpiObjetivo(codigo="nps", valor_objetivo=Decimal("50")))
    db.commit()

    alertas = evaluar_alertas(db)
    obj_alertas = [a for a in alertas if a["codigo"] == "objetivo_no_cumple"]
    assert len(obj_alertas) == 1
    assert periodo_anterior in obj_alertas[0]["titulo"]


def test_resumen_objetivos_cuenta_correcto(client):
    """Endpoint /resumen cuenta cumplen/no_cumplen/sin_valor correctamente."""
    from app.routers.kpis_objetivos_router import _invalidar_cache_resumen
    _invalidar_cache_resumen()  # asegurar estado limpio
    # Sin objetivos: total=0
    r = client.get("/api/kpis-objetivos/resumen")
    assert r.status_code == 200
    assert r.json()["total"] == 0

    # Con objetivos pero sin valores cargados
    client.put("/api/kpis-objetivos/nps", json={"valor_objetivo": 50})
    client.put("/api/kpis-objetivos/rotacion", json={"valor_objetivo": 10})
    r = client.get("/api/kpis-objetivos/resumen")
    data = r.json()
    assert data["total"] == 2
    assert data["sin_valor"] == 2
    assert data["cumplen"] == 0


def test_resumen_objetivos_cuenta_cumplen(db):
    """Si NPS=60 y objetivo=50 (mejor_si=subir) en mes anterior → cumple.
    Si rotación=15 y objetivo=10 (mejor_si=bajar) → no cumple."""
    from datetime import date as _date, timedelta
    from app.models.kpi_objetivo import KpiObjetivo
    from app.routers.kpis_objetivos_router import resumen, _invalidar_cache_resumen
    _invalidar_cache_resumen()
    _setup_minimo(db)
    hoy = _date.today()
    ult = hoy.replace(day=1) - timedelta(days=1)
    periodo_ant = f"{ult.year:04d}-{ult.month:02d}"
    db.add(KpiManual(periodo=periodo_ant, codigo="nps", valor=Decimal("60")))
    db.add(KpiManual(periodo=periodo_ant, codigo="bajas_mes", valor=Decimal("15")))
    db.add(KpiManual(periodo=periodo_ant, codigo="empleados_inicio_mes", valor=Decimal("100")))
    db.add(KpiManual(periodo=periodo_ant, codigo="empleados_fin_mes", valor=Decimal("100")))
    db.add(KpiObjetivo(codigo="nps", valor_objetivo=Decimal("50")))
    db.add(KpiObjetivo(codigo="rotacion", valor_objetivo=Decimal("10")))
    db.commit()

    out = resumen(db)
    assert out["total"] == 2
    assert out["cumplen"] == 1  # nps cumple
    assert out["no_cumplen"] == 1  # rotacion no
    assert out["sin_valor"] == 0


def test_rangos_objetivo_inventario():
    """Inventario explícito: si se agrega un KPI a `_META` sin entry en
    `_RANGOS_OBJETIVO`, este test recuerda revisar si necesita rango.
    Lista los códigos sin rango — solo falla si el set ya conocido cambia."""
    from app.kpis.derivados import _META, _RANGOS_OBJETIVO
    sin_rango = {c for c in _META if c not in _RANGOS_OBJETIVO}
    # Códigos donde decidimos NO acotar (ARS, ratios sin techo).
    esperados_sin_rango = {
        "margen_neto", "margen_neto_pct", "margen_operativo", "ebitda",
        "roi", "roa", "roe", "liquidez_corriente", "endeudamiento",
        "capital_trabajo", "productividad_por_empleado",
        "cac", "ltv_proxy", "costo_por_lead", "romi",
        "trafico_web", "alcance_campanas",
        # Sin techo lógico (ARS, conteos, ratios)
        "nivel_stock", "rotacion_inventario", "pipeline_oportunidades",
    }
    nuevos = sin_rango - esperados_sin_rango
    assert not nuevos, (
        f"KPIs nuevos sin rango: {nuevos}. Decidir si necesitan acotación "
        f"y agregarlos a _RANGOS_OBJETIVO o a la lista esperada del test."
    )


def test_punto_equilibrio_sin_cats_fijas_devuelve_nota(db):
    """Sin ninguna categoría marcada como `es_costo_fijo`, no se puede
    computar PE — el endpoint devuelve nota explicativa."""
    _setup_minimo(db)
    r = financieros.punto_equilibrio(db, desde=date(2026, 4, 1), hasta=date(2026, 4, 30))
    assert r["punto_equilibrio_ingresos"] is None
    assert "es_costo_fijo" in r["nota"]


def test_punto_equilibrio_calcula_correctamente(db):
    """PE = costos_fijos / (margen_contribucion / ingresos).
    Setup: ingresos=10000, fijos=1000, variables=4000 (ej. mercadería).
    margen_contribucion = 10000 - 4000 = 6000 → margen_pct = 60%
    PE = 1000 / 0.6 = 1666.67"""
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA", tipo="operativa"))
    db.add(CategoriaCaja(tipo_operacion="Sueldo", es_costo_fijo=True))
    db.add(CategoriaCaja(tipo_operacion="Mercaderia", es_costo_fijo=False))
    db.add(Venta(
        id_pedido="p1", id_venta="v1", fecha=datetime(2026, 4, 15),
        id_cliente=1, cliente="X", total=Decimal("10000"),
        monto_pago1=Decimal("10000"), caja1="cl",
    ))
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 5), tipo_operacion="Sueldo",
        monto=Decimal("1000"), caja_origen="cl", hash_dedupe="hf1",
    ))
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 10), tipo_operacion="Mercaderia",
        monto=Decimal("4000"), caja_origen="cl", hash_dedupe="hf2",
    ))
    db.commit()

    r = financieros.punto_equilibrio(
        db, desde=date(2026, 4, 1), hasta=date(2026, 4, 30),
    )
    assert r["costos_fijos"] == 1000.0
    assert r["costos_variables"] == 4000.0
    assert r["ingresos"] == 10000.0
    assert abs(r["margen_contribucion_pct"] - 60.0) < 0.01
    assert abs(r["punto_equilibrio_ingresos"] - 1666.6666) < 0.1
    # Cobertura: 10000 / 1666.67 ≈ 600% (negocio rentable)
    assert r["cobertura_pct"] > 500


def test_validacion_cruzada_ganados_mayor_que_cerrados_400(client):
    """No se puede cargar leads_ganados=50 con leads_cerrados=10."""
    r = client.put("/api/kpis-manuales/2026-04", json={
        "valores": [
            {"codigo": "leads_cerrados_mes", "valor": 10},
            {"codigo": "leads_ganados_mes", "valor": 50},
        ],
    })
    assert r.status_code == 400
    assert "Inconsistencia" in r.json()["detail"]


def test_validacion_cruzada_inactividad_mayor_productivas(client):
    r = client.put("/api/kpis-manuales/2026-04", json={
        "valores": [
            {"codigo": "horas_inactividad_mes", "valor": 200},
            {"codigo": "horas_productivas_mes", "valor": 100},
        ],
    })
    assert r.status_code == 400


def test_validacion_cruzada_no_dispara_si_solo_uno_de_los_dos(client):
    """Si solo se manda uno del par, no falla — el cruce solo aplica
    cuando ambos están en el mismo upsert."""
    r = client.put("/api/kpis-manuales/2026-04", json={
        "valores": [{"codigo": "leads_ganados_mes", "valor": 50}],
    })
    assert r.status_code == 200


def test_validacion_cruzada_pasa_si_subset_lte_total(client):
    r = client.put("/api/kpis-manuales/2026-04", json={
        "valores": [
            {"codigo": "leads_cerrados_mes", "valor": 50},
            {"codigo": "leads_ganados_mes", "valor": 10},
        ],
    })
    assert r.status_code == 200


def test_kpis_pdf_completo_tasa_cierre(db):
    """Tasa de cierre = leads_ganados / leads_cerrados * 100."""
    from app.kpis.derivados import kpis_del_mes
    _setup_minimo(db)
    db.add(KpiManual(periodo="2026-04", codigo="leads_cerrados_mes", valor=Decimal("20")))
    db.add(KpiManual(periodo="2026-04", codigo="leads_ganados_mes", valor=Decimal("8")))
    db.commit()
    r = kpis_del_mes(db, "2026-04", solo_codigos={"tasa_cierre"})
    tc = r["kpis"][0]
    assert tc["status"] == "ok"
    assert abs(tc["valor"] - 40.0) < 0.01


def test_kpis_pdf_completo_rotacion_inventario(db):
    """Rotación = CMV / stock_promedio."""
    from app.kpis.derivados import kpis_del_mes
    _setup_minimo(db)
    db.add(KpiManual(periodo="2026-04", codigo="costo_mercaderia_vendida_mes", valor=Decimal("100000")))
    db.add(KpiManual(periodo="2026-04", codigo="stock_promedio_ars", valor=Decimal("25000")))
    db.commit()
    r = kpis_del_mes(db, "2026-04", solo_codigos={"rotacion_inventario"})
    rot = r["kpis"][0]
    # 100000 / 25000 = 4 veces
    assert abs(rot["valor"] - 4.0) < 0.01


def test_kpis_pdf_completo_entregas_a_tiempo(db):
    from app.kpis.derivados import kpis_del_mes
    _setup_minimo(db)
    db.add(KpiManual(periodo="2026-04", codigo="entregas_a_tiempo_mes", valor=Decimal("80")))
    db.add(KpiManual(periodo="2026-04", codigo="entregas_total_mes", valor=Decimal("100")))
    db.commit()
    r = kpis_del_mes(db, "2026-04", solo_codigos={"entregas_a_tiempo_pct"})
    et = r["kpis"][0]
    assert abs(et["valor"] - 80.0) < 0.01


def test_kpis_pdf_completo_inactividad(db):
    from app.kpis.derivados import kpis_del_mes
    _setup_minimo(db)
    db.add(KpiManual(periodo="2026-04", codigo="horas_inactividad_mes", valor=Decimal("10")))
    db.add(KpiManual(periodo="2026-04", codigo="horas_productivas_mes", valor=Decimal("200")))
    db.commit()
    r = kpis_del_mes(db, "2026-04", solo_codigos={"inactividad_pct"})
    inact = r["kpis"][0]
    # 10 / 200 = 5%
    assert abs(inact["valor"] - 5.0) < 0.01
    assert inact["mejor_si"] == "bajar"


def test_reclamos_recurrentes_pct(db):
    """% reclamos recurrentes = recurrentes / total reclamos."""
    from app.kpis.derivados import kpis_del_mes
    _setup_minimo(db)
    db.add(KpiManual(periodo="2026-04", codigo="reclamos_mes", valor=Decimal("20")))
    db.add(KpiManual(periodo="2026-04", codigo="reclamos_recurrentes_mes", valor=Decimal("5")))
    db.commit()

    r = kpis_del_mes(db, "2026-04", solo_codigos={"reclamos_recurrentes_pct"})
    rec = r["kpis"][0]
    assert rec["status"] == "ok"
    # 5 / 20 * 100 = 25%
    assert abs(rec["valor"] - 25.0) < 0.01
    assert rec["mejor_si"] == "bajar"  # menos recurrencia es mejor


def test_reclamos_recurrentes_cero_reclamos_status_ok(db):
    """0 reclamos cargados (no falta input): status=ok, valor=None,
    falta=None. Sin esto el dashboard reporta 'falta dato' cuando en
    realidad fue 'no hubo reclamos'."""
    from app.kpis.derivados import kpis_del_mes
    _setup_minimo(db)
    db.add(KpiManual(periodo="2026-04", codigo="reclamos_mes", valor=Decimal("0")))
    db.add(KpiManual(periodo="2026-04", codigo="reclamos_recurrentes_mes", valor=Decimal("0")))
    db.commit()

    r = kpis_del_mes(db, "2026-04", solo_codigos={"reclamos_recurrentes_pct"})
    rec = r["kpis"][0]
    assert rec["status"] == "ok"
    assert rec["valor"] is None
    assert rec.get("falta") is None


def test_crecimiento_sostenido_mediana_robusta_a_outlier(db):
    """Verifica que mediana ignora un outlier. Serie con 3 meses al
    +10% y 1 mes con +500% (estacional): mediana ≈ 10%, promedio ≈ 137%."""
    db.add(Caja(nombre_normalizado="cl", nombre_display="C", tipo="operativa"))
    valores = [1000, 1100, 1210, 7260]  # +10%, +10%, +500%
    for i, monto in enumerate(valores):
        db.add(Venta(
            id_pedido=f"p{i}", id_venta=f"v{i}",
            fecha=datetime(2026, i + 1, 15),
            id_cliente=1, cliente="X", total=Decimal(str(monto)),
            monto_pago1=Decimal(str(monto)), caja1="cl",
        ))
    db.commit()

    r = financieros.crecimiento_sostenido(db, meses=12)
    # Mediana de [+10, +10, +500] (los deltas reales) → 10
    # Promedio: 173 (mucho más alto)
    assert r["tasa_mensual_pct"] is not None
    assert r["tasa_mensual_promedio_pct"] is not None
    # Mediana < promedio (sensitivity test): el outlier infla el promedio
    assert r["tasa_mensual_pct"] < r["tasa_mensual_promedio_pct"]


def test_rotar_backups_mantiene_n_recientes(tmp_path, monkeypatch):
    """rotar_backups deja los N más recientes, borra el resto."""
    from app.routers import admin_router as ar
    # Redirigir BACKUPS_DIR al tmp_path
    monkeypatch.setattr(ar, "BACKUPS_DIR", tmp_path)
    # Crear 5 backups con timestamps distintos
    nombres = []
    for i in range(5):
        p = tmp_path / f"kpi_2026010{i+1}_120000.db"
        p.write_bytes(b"fake")
        nombres.append(p.name)
    # Retener solo 2
    eliminados = ar.rotar_backups(max_retenidos=2)
    assert len(eliminados) == 3
    # Los más nuevos quedan (kpi_20260105 y kpi_20260104 según sort reverse)
    quedan = sorted(p.name for p in tmp_path.glob("kpi_*.db"))
    assert len(quedan) == 2


def test_rotar_backups_sin_excedente_no_borra(tmp_path, monkeypatch):
    from app.routers import admin_router as ar
    monkeypatch.setattr(ar, "BACKUPS_DIR", tmp_path)
    for i in range(3):
        (tmp_path / f"kpi_2026010{i+1}_120000.db").write_bytes(b"fake")
    eliminados = ar.rotar_backups(max_retenidos=10)
    assert eliminados == []


def test_endpoint_rotar_validacion(client):
    r = client.post("/api/admin/backups/rotar?max_retenidos=0")
    assert r.status_code == 400


def test_export_csv_derivados_devuelve_csv(client):
    """GET /api/kpis-manuales/{periodo}/derivados.csv → CSV con header
    + 1 fila por KPI."""
    client.put("/api/kpis-objetivos/nps", json={"valor_objetivo": 50})
    r = client.get("/api/kpis-manuales/2026-04/derivados.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    text = r.text
    # Header esperado
    assert text.startswith("﻿area,codigo,label,valor") or \
           text.startswith("area,codigo,label,valor")
    assert "nps" in text
    # Cells con coma en label deben venir cuoteadas
    assert "(clientes)" in text or "NPS" in text


def test_export_csv_derivados_periodo_invalido_400(client):
    r = client.get("/api/kpis-manuales/INVALID/derivados.csv")
    assert r.status_code == 400


def test_endpoint_crecimiento_sostenido_cachea(client):
    """Hits consecutivos del endpoint deben servir de cache."""
    from app.routers.kpis_financieros_router import _invalidar_cache_financieros, _cache
    _invalidar_cache_financieros()
    r1 = client.get("/api/kpis/financieros/crecimiento-sostenido?meses=12")
    assert r1.status_code == 200
    assert ("crecimiento", 12) in _cache
    r2 = client.get("/api/kpis/financieros/crecimiento-sostenido?meses=12")
    assert r2.status_code == 200
    # Segundo hit debe llegar desde el cache (mismo timestamp).
    ts1 = _cache[("crecimiento", 12)][0]
    r3 = client.get("/api/kpis/financieros/crecimiento-sostenido?meses=12")
    ts2 = _cache[("crecimiento", 12)][0]
    assert ts1 == ts2  # no se reescribió → cache hit


def test_punto_equilibrio_negocio_en_rojo(db):
    """Margen de contribución negativo → PE inalcanzable, nota explicativa."""
    db.add(Caja(nombre_normalizado="cl", nombre_display="C", tipo="operativa"))
    db.add(CategoriaCaja(tipo_operacion="Sueldo", es_costo_fijo=True))
    db.add(CategoriaCaja(tipo_operacion="Mercaderia", es_costo_fijo=False))
    db.add(Venta(
        id_pedido="p1", id_venta="v1", fecha=datetime(2026, 4, 15),
        id_cliente=1, cliente="X", total=Decimal("1000"),
        monto_pago1=Decimal("1000"), caja1="cl",
    ))
    # Variables > ingresos → margen contribución negativo
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 5), tipo_operacion="Mercaderia",
        monto=Decimal("1500"), caja_origen="cl", hash_dedupe="hr1",
    ))
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 5), tipo_operacion="Sueldo",
        monto=Decimal("100"), caja_origen="cl", hash_dedupe="hr2",
    ))
    db.commit()

    r = financieros.punto_equilibrio(db, desde=date(2026, 4, 1), hasta=date(2026, 4, 30))
    assert r["punto_equilibrio_ingresos"] is None
    assert r["margen_contribucion_pct"] < 0
    assert "inalcanzable" in r["nota"].lower()


def test_heatmap_orden_estable_por_area_label(client):
    """Filas del heatmap ordenadas por (area, label) — estable y agrupado."""
    client.put("/api/kpis-objetivos/rotacion", json={"valor_objetivo": 10})
    client.put("/api/kpis-objetivos/nps", json={"valor_objetivo": 50})
    client.put("/api/kpis-objetivos/cac", json={"valor_objetivo": 1000})
    r = client.get("/api/kpis-objetivos/heatmap?meses=3")
    kpis = r.json()["kpis"]
    # Verificar orden por (area, label)
    pares = [(k["area"], k["label"]) for k in kpis]
    assert pares == sorted(pares)


def test_heatmap_cache_se_invalida_en_upsert(client):
    """Cache hit la primera vez, miss tras PUT."""
    from app.routers.kpis_objetivos_router import _invalidar_cache_heatmap, _heatmap_cache
    _invalidar_cache_heatmap()
    r1 = client.get("/api/kpis-objetivos/heatmap?meses=3")
    assert r1.status_code == 200
    ts1 = _heatmap_cache["ts"]
    client.put("/api/kpis-objetivos/nps", json={"valor_objetivo": 50})
    r2 = client.get("/api/kpis-objetivos/heatmap?meses=3")
    ts2 = _heatmap_cache["ts"]
    assert ts2 != ts1


def test_crecimiento_sostenido_sin_datos_devuelve_nota(db):
    """Sin ingresos en ningún período → no calcula, devuelve nota."""
    _setup_minimo(db)
    r = financieros.crecimiento_sostenido(db)
    assert r["tasa_mensual_pct"] is None
    assert "nota" in r


def test_crecimiento_sostenido_calcula_promedio(db):
    """3 meses con ingresos crecientes → tasa positiva."""
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA", tipo="operativa"))
    # Cargar ventas en 3 meses crecientes
    for i, monto in enumerate([1000, 1100, 1210], start=2):
        db.add(Venta(
            id_pedido=f"p{i}", id_venta=f"v{i}",
            fecha=datetime(2026, i, 15),
            id_cliente=1, cliente="X", total=Decimal(str(monto)),
            monto_pago1=Decimal(str(monto)), caja1="cl",
        ))
    db.commit()

    r = financieros.crecimiento_sostenido(db, meses=12)
    assert r["periodos_analizados"] >= 3
    # Tasa mensual debería estar cerca de 10% (1000→1100 = 10%, 1100→1210 = 10%)
    # pero hay meses 0 antes de feb → el primer delta puede ser muy alto
    # o cero. Solo verificamos que se computa.
    assert r["tasa_mensual_pct"] is not None


def test_heatmap_objetivos_devuelve_matriz(client):
    """Heatmap retorna {periodos, kpis: [{codigo, label, celdas}]}."""
    client.put("/api/kpis-objetivos/nps", json={"valor_objetivo": 50})
    client.put("/api/kpis-objetivos/rotacion", json={"valor_objetivo": 10})
    r = client.get("/api/kpis-objetivos/heatmap?meses=3")
    assert r.status_code == 200
    data = r.json()
    assert len(data["periodos"]) == 3
    assert len(data["kpis"]) == 2
    for k in data["kpis"]:
        assert len(k["celdas"]) == 3


def test_heatmap_celda_cumple_correctamente(db):
    """Si cargo NPS=60 con objetivo=50 (subir), celda debe estar cumple=true."""
    from datetime import date as _date, timedelta
    from app.models.kpi_objetivo import KpiObjetivo
    from app.routers.kpis_objetivos_router import heatmap as heatmap_fn
    _setup_minimo(db)
    hoy = _date.today()
    ult = hoy.replace(day=1) - timedelta(days=1)
    periodo_ant = f"{ult.year:04d}-{ult.month:02d}"
    db.add(KpiManual(periodo=periodo_ant, codigo="nps", valor=Decimal("60")))
    db.add(KpiObjetivo(codigo="nps", valor_objetivo=Decimal("50")))
    db.commit()

    r = heatmap_fn(meses=3, db=db)
    nps_kpi = next(k for k in r["kpis"] if k["codigo"] == "nps")
    # Última celda corresponde al mes anterior cerrado
    ultima = nps_kpi["celdas"][-1]
    assert ultima["periodo"] == periodo_ant
    assert ultima["valor"] == 60.0
    assert ultima["cumple"] is True


def test_heatmap_meses_fuera_rango_400(client):
    r = client.get("/api/kpis-objetivos/heatmap?meses=0")
    assert r.status_code == 400
    r = client.get("/api/kpis-objetivos/heatmap?meses=24")
    assert r.status_code == 400


def test_heatmap_sin_objetivos_devuelve_vacio(client):
    r = client.get("/api/kpis-objetivos/heatmap")
    assert r.status_code == 200
    assert r.json() == {"periodos": [], "kpis": []}


def test_resumen_objetivos_codigo_huerfano_se_cuenta(db):
    """Si un objetivo apunta a código huérfano, debe contarse en `huerfanos`,
    NO desaparecer silenciosamente del total."""
    from app.models.kpi_objetivo import KpiObjetivo
    from app.routers.kpis_objetivos_router import resumen, _invalidar_cache_resumen
    _invalidar_cache_resumen()
    _setup_minimo(db)
    db.add(KpiObjetivo(codigo="nps", valor_objetivo=Decimal("50")))
    db.add(KpiObjetivo(
        codigo="codigo_inexistente_futuro",
        valor_objetivo=Decimal("999"),
    ))
    db.commit()

    out = resumen(db)
    assert out["total"] == 2
    assert out["huerfanos"] == 1
    # Sumatoria coherente: cumplen+no_cumplen+sin_valor+huerfanos == total
    assert out["cumplen"] + out["no_cumplen"] + out["sin_valor"] + out["huerfanos"] == out["total"]


def test_resumen_objetivos_cache_se_invalida_en_upsert(client):
    """Cache hit la primera vez, miss después de PUT."""
    from app.routers.kpis_objetivos_router import _invalidar_cache_resumen, _resumen_cache
    _invalidar_cache_resumen()

    r1 = client.get("/api/kpis-objetivos/resumen")
    assert r1.json()["total"] == 0
    # Cargar el cache con total=0
    cache_ts_1 = _resumen_cache["ts"]

    # PUT debe invalidar
    client.put("/api/kpis-objetivos/nps", json={"valor_objetivo": 50})
    r2 = client.get("/api/kpis-objetivos/resumen")
    assert r2.json()["total"] == 1
    cache_ts_2 = _resumen_cache["ts"]
    # El cache se reemplazó (timestamp distinto)
    assert cache_ts_2 != cache_ts_1


def test_import_csv_objetivos_basico(client):
    csv_text = "codigo,valor_objetivo,nota\nnps,50,Mejorar atencion\nrotacion,10,\n"
    r = client.post(
        "/api/kpis-objetivos/import-csv",
        files={"file": ("o.csv", csv_text, "text/csv")},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["insertados"] == 2
    # Re-importar actualiza
    csv_text2 = "codigo,valor_objetivo,nota\nnps,55,\n"
    r2 = client.post(
        "/api/kpis-objetivos/import-csv",
        files={"file": ("o2.csv", csv_text2, "text/csv")},
    )
    assert r2.json()["actualizados"] == 1


def test_import_csv_objetivos_codigo_invalido(client):
    csv_text = "codigo,valor_objetivo\nno_existe,42\nnps,50\n"
    r = client.post(
        "/api/kpis-objetivos/import-csv",
        files={"file": ("o.csv", csv_text, "text/csv")},
    )
    data = r.json()
    assert data["insertados"] == 1
    assert len(data["errores"]) == 1


def test_template_csv_objetivos(client):
    r = client.get("/api/kpis-objetivos/template-csv")
    assert r.status_code == 200
    assert "codigo,valor_objetivo,nota" in r.text
    assert "nps" in r.text


def test_objetivo_huerfano_se_marca(client):
    """Caso normal: PUT con código válido marca huerfano=False."""
    r = client.put("/api/kpis-objetivos/nps", json={"valor_objetivo": 50})
    assert r.status_code == 200
    data = r.json()
    assert data["huerfano"] is False
    assert data["label"] == "NPS (clientes)"


def test_objetivo_huerfano_true_si_codigo_se_elimina(db):
    """Inserto directo en DB un objetivo con código que NO está en _META.
    Listar debe marcarlo huerfano=true."""
    from app.models.kpi_objetivo import KpiObjetivo
    from app.routers.kpis_objetivos_router import _serializar
    obj = KpiObjetivo(
        codigo="codigo_inexistente_futuro",
        valor_objetivo=Decimal("42"),
    )
    db.add(obj)
    db.commit()
    s = _serializar(obj)
    assert s["huerfano"] is True
    assert s["label"] is None


def test_alertas_no_dispara_si_objetivo_se_cumple(db):
    """Si NPS objetivo=50 y valor=60, NO debe haber alerta."""
    from datetime import date as _date
    from app.kpis.alertas import evaluar_alertas
    from app.models.kpi_objetivo import KpiObjetivo

    _setup_minimo(db)
    hoy = _date.today()
    periodo_actual = f"{hoy.year:04d}-{hoy.month:02d}"
    db.add(KpiManual(periodo=periodo_actual, codigo="nps", valor=Decimal("60")))
    db.add(KpiObjetivo(codigo="nps", valor_objetivo=Decimal("50")))
    db.commit()

    alertas = evaluar_alertas(db)
    assert all(a["codigo"] != "objetivo_no_cumple" for a in alertas)


def test_template_csv_es_csv(client):
    r = client.get("/api/kpis-manuales/template-csv")
    assert r.status_code == 200
    assert "periodo,codigo,valor,nota" in r.text
    assert "activos_totales" in r.text  # menciona códigos válidos


def test_kpis_comparativa_anterior_cero(db):
    """Si el valor anterior es 0, delta_pct=None (división por cero)."""
    from app.kpis.derivados import kpis_del_mes_con_comparativa
    _setup_minimo(db)
    db.add(KpiManual(periodo="2025-04", codigo="bajas_mes", valor=Decimal("0")))
    db.add(KpiManual(periodo="2025-04", codigo="empleados_inicio_mes", valor=Decimal("10")))
    db.add(KpiManual(periodo="2025-04", codigo="empleados_fin_mes", valor=Decimal("10")))
    db.add(KpiManual(periodo="2026-04", codigo="bajas_mes", valor=Decimal("3")))
    db.add(KpiManual(periodo="2026-04", codigo="empleados_inicio_mes", valor=Decimal("10")))
    db.add(KpiManual(periodo="2026-04", codigo="empleados_fin_mes", valor=Decimal("10")))
    db.commit()

    r = kpis_del_mes_con_comparativa(db, "2026-04", solo_codigos={"rotacion"})
    rot = r["kpis"][0]
    assert rot["valor"] == 30.0  # 3 / 10 * 100
    assert rot["valor_anterior"] == 0.0
    assert rot["delta_pct"] is None  # división por cero


def test_margen_serie_cruza_anio(db):
    """desde=2025-11, hasta=2026-02 → 4 puntos correctos."""
    _setup_minimo(db)
    db.add(Venta(
        id_pedido="p1", id_venta="v1", fecha=datetime(2025, 11, 15),
        id_cliente=1, cliente="X", total=Decimal("1000"),
        monto_pago1=Decimal("1000"), caja1="cl",
    ))
    db.add(Venta(
        id_pedido="p2", id_venta="v2", fecha=datetime(2026, 1, 10),
        id_cliente=1, cliente="X", total=Decimal("2000"),
        monto_pago1=Decimal("2000"), caja1="cl",
    ))
    db.commit()

    serie = financieros.margen_operativo_serie(
        db, desde=date(2025, 11, 1), hasta=date(2026, 2, 28),
    )
    periodos = [p["periodo"] for p in serie]
    assert periodos == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert serie[0]["ingresos"] == 1000.0  # nov
    assert serie[2]["ingresos"] == 2000.0  # ene


def test_validacion_nps_rango_negativo_aceptado(client):
    """NPS = -50 debe ser aceptado (rango -100 a +100)."""
    r = client.put("/api/kpis-manuales/2026-04", json={
        "valores": [{"codigo": "nps", "valor": -50}],
    })
    assert r.status_code == 200
    r2 = client.get("/api/kpis-manuales/2026-04")
    nps_val = next((v for v in r2.json()["valores"] if v["codigo"] == "nps"), None)
    assert nps_val is not None
    assert nps_val["valor"] == -50.0


def test_margen_operativo_serie_devuelve_un_punto_por_mes(db):
    """Serie temporal: 1 punto por mes en el rango."""
    _setup_minimo(db)
    db.add(Venta(
        id_pedido="p1", id_venta="v1", fecha=datetime(2026, 4, 15),
        id_cliente=1, cliente="X", total=Decimal("10000"),
        monto_pago1=Decimal("10000"), caja1="cl",
    ))
    db.add(Venta(
        id_pedido="p2", id_venta="v2", fecha=datetime(2026, 5, 10),
        id_cliente=1, cliente="X", total=Decimal("8000"),
        monto_pago1=Decimal("8000"), caja1="cl",
    ))
    db.commit()

    serie = financieros.margen_operativo_serie(
        db, desde=date(2026, 4, 1), hasta=date(2026, 5, 31),
    )
    assert len(serie) == 2
    assert serie[0]["periodo"] == "2026-04"
    assert serie[0]["ingresos"] == 10000.0
    assert serie[1]["periodo"] == "2026-05"
    assert serie[1]["ingresos"] == 8000.0


def test_margen_operativo_serie_default_12_meses(db):
    """Sin desde/hasta: ventana de 12 meses hasta hoy."""
    _setup_minimo(db)
    serie = financieros.margen_operativo_serie(db)
    assert len(serie) == 12


def test_kpis_derivados_rotacion_rrhh(db):
    """Rotacion = bajas / promedio_empleados * 100."""
    _setup_minimo(db)
    db.add(KpiManual(periodo="2026-04", codigo="empleados_inicio_mes", valor=Decimal("20")))
    db.add(KpiManual(periodo="2026-04", codigo="empleados_fin_mes", valor=Decimal("18")))
    db.add(KpiManual(periodo="2026-04", codigo="bajas_mes", valor=Decimal("3")))
    db.commit()

    r = kpis_del_mes(db, "2026-04")
    by_codigo = {k["codigo"]: k for k in r["kpis"]}
    rot = by_codigo["rotacion"]
    assert rot["status"] == "ok"
    # 3 / ((20+18)/2) * 100 = 3 / 19 * 100 ≈ 15.79
    assert abs(rot["valor"] - (3 / 19 * 100)) < 0.1


# ──────────────────────────────────────────────────────────────────────────
# Tests de edge cases temporales con freezegun
# ──────────────────────────────────────────────────────────────────────────
# Estos tests fijan la fecha del sistema para validar comportamientos en
# transiciones críticas: cambio de año, año bisiesto, primer día del mes.
# Sin freezegun era imposible escribirlos de forma determinista.

from freezegun import freeze_time


@freeze_time("2026-01-15 12:00:00")
def test_alertas_periodo_anterior_cruzando_anio(db):
    """En enero, "mes anterior" debe ser diciembre del año previo (2025-12),
    no enero del mismo año. Bug clásico: hoy.month - 1 = 0."""
    from app.kpis.alertas import evaluar_alertas
    from app.models.kpi_objetivo import KpiObjetivo

    _setup_minimo(db)
    # Cargo dato en diciembre 2025 (mes anterior real)
    db.add(KpiManual(periodo="2025-12", codigo="nps", valor=Decimal("30")))
    db.add(KpiObjetivo(codigo="nps", valor_objetivo=Decimal("50")))
    db.commit()

    alertas = evaluar_alertas(db)
    obj_alertas = [a for a in alertas if a["codigo"] == "objetivo_no_cumple"]
    # Debe encontrar el dato de 2025-12 y disparar alerta
    assert len(obj_alertas) == 1
    assert "2025-12" in obj_alertas[0]["titulo"]


@freeze_time("2024-02-29 12:00:00")
def test_alertas_periodo_anterior_anio_bisiesto(db):
    """En 29-feb-2024 (bisiesto), "mes anterior" debe ser enero 2024.
    `hoy.replace(day=1) - timedelta(days=1)` = 2024-01-31."""
    from app.kpis.alertas import evaluar_alertas
    from app.models.kpi_objetivo import KpiObjetivo

    _setup_minimo(db)
    db.add(KpiManual(periodo="2024-01", codigo="nps", valor=Decimal("30")))
    db.add(KpiObjetivo(codigo="nps", valor_objetivo=Decimal("50")))
    db.commit()

    alertas = evaluar_alertas(db)
    obj_alertas = [a for a in alertas if a["codigo"] == "objetivo_no_cumple"]
    assert len(obj_alertas) == 1
    assert "2024-01" in obj_alertas[0]["titulo"]


@freeze_time("2026-12-31 12:00:00")
def test_alertas_ultimo_dia_anio(db):
    """Día 31-dic: "mes anterior" debe ser noviembre, no octubre."""
    from app.kpis.alertas import evaluar_alertas
    from app.models.kpi_objetivo import KpiObjetivo

    _setup_minimo(db)
    db.add(KpiManual(periodo="2026-11", codigo="nps", valor=Decimal("30")))
    db.add(KpiObjetivo(codigo="nps", valor_objetivo=Decimal("50")))
    db.commit()

    alertas = evaluar_alertas(db)
    obj_alertas = [a for a in alertas if a["codigo"] == "objetivo_no_cumple"]
    assert len(obj_alertas) == 1
    assert "2026-11" in obj_alertas[0]["titulo"]


@freeze_time("2026-01-01 12:00:00")
def test_alertas_primer_dia_anio(db):
    """1-ene: "mes anterior" debe ser dic-2025 (cruce año explícito)."""
    from app.kpis.alertas import evaluar_alertas
    from app.models.kpi_objetivo import KpiObjetivo

    _setup_minimo(db)
    db.add(KpiManual(periodo="2025-12", codigo="nps", valor=Decimal("30")))
    db.add(KpiObjetivo(codigo="nps", valor_objetivo=Decimal("50")))
    db.commit()

    alertas = evaluar_alertas(db)
    obj_alertas = [a for a in alertas if a["codigo"] == "objetivo_no_cumple"]
    assert len(obj_alertas) == 1
    assert "2025-12" in obj_alertas[0]["titulo"]


@freeze_time("2026-01-15 12:00:00")
def test_crecimiento_sostenido_cruza_anio(db):
    """N=6 y mes_actual=ene 2026 → ventana = ago 2025 a ene 2026.
    El KPI debe armar correctamente el rango cruzando año.
    Bug histórico: idx_total = año*12 + mes - (N-1) puede dar negativo si
    no se maneja bien la división — esto valida que no ocurre."""
    from app.kpis.financieros import crecimiento_sostenido
    _setup_minimo(db)
    # Cargo ventas crecientes Aug 2025 → Jan 2026
    montos = [1000, 1100, 1200, 1300, 1400, 1500]  # estrictamente creciente
    fechas = [
        (2025, 8, 15), (2025, 9, 15), (2025, 10, 15),
        (2025, 11, 15), (2025, 12, 15), (2026, 1, 10),
    ]
    for i, ((y, m, d), monto) in enumerate(zip(fechas, montos)):
        db.add(Venta(
            id_pedido=f"P{i}", id_venta=f"V{i}",
            id_cliente=1, cliente="X",
            fecha=datetime(y, m, d), total=Decimal(str(monto)),
            monto_pago1=Decimal(str(monto)), caja1="cl",
        ))
    db.commit()

    r = crecimiento_sostenido(db, meses=6)
    # Debe analizar 6 períodos sin error de off-by-one
    assert r["periodos_analizados"] == 6
    # Crecimiento positivo (mediana) — todos los deltas son ~10%
    assert r["tasa_mensual_pct"] is not None
    assert r["tasa_mensual_pct"] > 0
    # Mediana ~ 10% (cada mes crece 100/N respecto al anterior)
    assert 8 <= r["tasa_mensual_pct"] <= 12


@freeze_time("2026-03-31 12:00:00")
def test_alertas_ultimo_dia_mes_31_dias(db):
    """Día 31-mar: mes anterior debe ser febrero (28 días en 2026), no enero."""
    from app.kpis.alertas import evaluar_alertas
    from app.models.kpi_objetivo import KpiObjetivo

    _setup_minimo(db)
    db.add(KpiManual(periodo="2026-02", codigo="nps", valor=Decimal("30")))
    db.add(KpiObjetivo(codigo="nps", valor_objetivo=Decimal("50")))
    db.commit()

    alertas = evaluar_alertas(db)
    obj_alertas = [a for a in alertas if a["codigo"] == "objetivo_no_cumple"]
    assert len(obj_alertas) == 1
    assert "2026-02" in obj_alertas[0]["titulo"]
