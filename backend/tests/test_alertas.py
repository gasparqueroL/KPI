"""Tests del detector de alertas. Solo cubre las reglas nuevas
(facturas_vencidas, facturas_por_vencer, clientes_morosos) — las preexistentes
ya están cubiertas indirectamente por los tests de los módulos que consultan."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.kpis.alertas import evaluar_alertas
from app.models.caja import Caja
from app.models.movimiento_caja import MovimientoCaja
from app.models.proveedor import FacturaProveedor, Proveedor
from app.models.venta import Venta


def _codigos(alertas):
    return {a["codigo"] for a in alertas}


def _setup_caja(db):
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.commit()


def test_factura_vencida_dispara_alerta_critica(db):
    _setup_caja(db)
    p = Proveedor(nombre="Prov V")
    db.add(p)
    db.commit()
    db.refresh(p)
    # Vencida hace 5 días
    db.add(FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date.today() - timedelta(days=30),
        fecha_vencimiento=date.today() - timedelta(days=5),
        total=Decimal("10000"),
    ))
    db.commit()

    alertas = evaluar_alertas(db)
    fv = next((a for a in alertas if a["codigo"] == "facturas_vencidas"), None)
    assert fv is not None
    assert fv["severidad"] == "critica"
    assert fv["valor"] == 1
    assert "Prov V" in fv["detalle"]
    # Deep link al proveedor afectado.
    assert fv["link"] == f"/proveedores?proveedor={p.id}"


def test_facturas_vencidas_link_apunta_al_de_mayor_pendiente(db):
    """Con varios proveedores vencidos, el link va al que tiene mayor monto
    pendiente (más urgente para renegociar/pagar)."""
    _setup_caja(db)
    p1 = Proveedor(nombre="Prov Chico")
    p2 = Proveedor(nombre="Prov Grande")
    db.add_all([p1, p2])
    db.commit()
    db.refresh(p1)
    db.refresh(p2)
    # p1: factura chica vencida
    db.add(FacturaProveedor(
        id_proveedor=p1.id, fecha_emision=date.today() - timedelta(days=20),
        fecha_vencimiento=date.today() - timedelta(days=10),
        total=Decimal("5000"),
    ))
    # p2: factura grande vencida (la peor)
    db.add(FacturaProveedor(
        id_proveedor=p2.id, fecha_emision=date.today() - timedelta(days=15),
        fecha_vencimiento=date.today() - timedelta(days=2),
        total=Decimal("100000"),
    ))
    db.commit()

    alertas = evaluar_alertas(db)
    fv = next((a for a in alertas if a["codigo"] == "facturas_vencidas"), None)
    assert fv is not None
    assert fv["link"] == f"/proveedores?proveedor={p2.id}"


def test_factura_por_vencer_proxima_dispara_atencion(db):
    _setup_caja(db)
    p = Proveedor(nombre="Prov P")
    db.add(p)
    db.commit()
    db.refresh(p)
    # Vence en 3 días (dentro del ventana de 7)
    db.add(FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date.today(),
        fecha_vencimiento=date.today() + timedelta(days=3),
        total=Decimal("5000"),
    ))
    db.commit()

    alertas = evaluar_alertas(db)
    fp = next((a for a in alertas if a["codigo"] == "facturas_por_vencer"), None)
    assert fp is not None
    assert fp["severidad"] == "atencion"


def test_factura_anulada_no_dispara_vencimiento(db):
    _setup_caja(db)
    p = Proveedor(nombre="Prov A")
    db.add(p)
    db.commit()
    db.refresh(p)
    db.add(FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date.today() - timedelta(days=30),
        fecha_vencimiento=date.today() - timedelta(days=5),
        total=Decimal("10000"), anulada=True,
    ))
    db.commit()

    alertas = evaluar_alertas(db)
    assert "facturas_vencidas" not in _codigos(alertas)


def test_cliente_moroso_dispara_alerta(db):
    """Cliente con saldo +90d sobre el umbral genera alerta clientes_morosos."""
    _setup_caja(db)
    # Venta sin cobro hace 100 días → cae en bucket_90_mas
    db.add(Venta(
        id_pedido="P-OLD-1", id_venta="V-OLD-1",
        id_cliente=42,
        cliente="Cliente Moroso SA",
        fecha=datetime.combine(date.today() - timedelta(days=100), datetime.min.time()),
        total=Decimal("80000"),  # > UMBRAL_MOROSIDAD (50_000)
        es_cuenta_corriente=True,
        vendedor="V1",
    ))
    db.commit()

    alertas = evaluar_alertas(db)
    cm = next((a for a in alertas if a["codigo"] == "clientes_morosos"), None)
    assert cm is not None
    assert cm["severidad"] == "atencion"
    assert "Cliente Moroso SA" in cm["detalle"]
    # Deep link al cliente top moroso — la dueña hace click y va directo
    # al ledger en vez de la página genérica.
    assert cm["link"] == "/cuentas-corrientes?cliente=42"


def test_cliente_moroso_fallback_link_si_id_ausente(db, monkeypatch):
    """Defensa: si por alguna razón aging['items'] devuelve un item sin
    id_cliente (rama improbable hoy pero potencial si el modelo cambia),
    el link cae al path genérico en lugar de quedar `?cliente=undefined`.
    Test mockea `aging_cobros` para forzar el shape sin id."""
    _setup_caja(db)
    # Mock que devuelve un moroso sin id_cliente.
    def aging_mock(_db):
        return {
            "totales": {"bucket_0_30": 0, "bucket_31_60": 0, "bucket_61_90": 0, "bucket_90_mas": 100000, "total": 100000},
            "items": [{
                "cliente": "Anónimo SA",
                # SIN id_cliente
                "bucket_0_30": 0, "bucket_31_60": 0, "bucket_61_90": 0,
                "bucket_90_mas": 100000, "total": 100000,
            }],
            "con_credito": [],
        }
    from app.kpis import alertas as alertas_mod
    monkeypatch.setattr(alertas_mod.kpi_cc, "aging_cobros", aging_mock)

    alertas = evaluar_alertas(db)
    cm = next((a for a in alertas if a["codigo"] == "clientes_morosos"), None)
    assert cm is not None
    # Sin id → path genérico, no `?cliente=undefined` ni crash.
    assert cm["link"] == "/cuentas-corrientes"


def test_cliente_moroso_link_apunta_al_peor_no_al_primero(db):
    """Cuando hay varios morosos, el link va al que MÁS debe en bucket 90+."""
    _setup_caja(db)
    # Cliente A: $60k en 100 días (peor por antigüedad pero menor monto)
    db.add(Venta(
        id_pedido="P-MA-A", id_venta="V-MA-A",
        id_cliente=10, cliente="Moroso A",
        fecha=datetime.combine(date.today() - timedelta(days=100), datetime.min.time()),
        total=Decimal("60000"),
        es_cuenta_corriente=True, vendedor="V1",
    ))
    # Cliente B: $200k en 95 días (mayor monto)
    db.add(Venta(
        id_pedido="P-MA-B", id_venta="V-MA-B",
        id_cliente=20, cliente="Moroso B",
        fecha=datetime.combine(date.today() - timedelta(days=95), datetime.min.time()),
        total=Decimal("200000"),
        es_cuenta_corriente=True, vendedor="V1",
    ))
    db.commit()

    alertas = evaluar_alertas(db)
    cm = next((a for a in alertas if a["codigo"] == "clientes_morosos"), None)
    assert cm is not None
    # El sort interno ordena por bucket_90_mas desc → top es B con $200k.
    assert cm["link"] == "/cuentas-corrientes?cliente=20"


def test_cliente_moroso_sin_cobro_y_sin_marca_ctacte_dispara(db):
    """Rama 2 del predicado de aging_cobros: venta NO marcada como cta cte
    pero sin cobro (monto_pago1+2 = 0). El sistema la considera 'probable
    cta cte mal etiquetada' y debería entrar al aging — si supera umbral
    en 90+, también debe disparar la alerta."""
    _setup_caja(db)
    db.add(Venta(
        id_pedido="P-OLD-3", id_venta="V-OLD-3",
        id_cliente=44,
        cliente="Sin Marca SA",
        fecha=datetime.combine(date.today() - timedelta(days=120), datetime.min.time()),
        total=Decimal("90000"),  # > UMBRAL_MOROSIDAD
        es_cuenta_corriente=False,  # NO marcada — pero sin pagos
        monto_pago1=Decimal("0"),
        monto_pago2=Decimal("0"),
        vendedor="V1",
    ))
    db.commit()

    alertas = evaluar_alertas(db)
    cm = next((a for a in alertas if a["codigo"] == "clientes_morosos"), None)
    assert cm is not None
    assert "Sin Marca SA" in cm["detalle"]


def _cobranza_cliente(id_cliente, monto, dias_atras=5, sufijo=""):
    """Helper: movimiento_caja que representa una cobranza cliente-nivel.
    caja_destino IS NOT NULL + caja_origen IS NULL = ingreso operativo
    (no transferencia interna). hash_dedupe único por test/cliente."""
    return MovimientoCaja(
        fecha=date.today() - timedelta(days=dias_atras),
        tipo_operacion="cobranza",
        detalle=f"cobranza cliente {id_cliente}",
        monto=Decimal(str(monto)),
        caja_destino="cl",
        caja_origen=None,
        id_cliente_relacionado=id_cliente,
        hash_dedupe=f"hcrd-{id_cliente}{sufijo}",
    )


def test_clientes_con_credito_dispara_si_total_supera_umbral(db, monkeypatch):
    """Cliente que pagó MÁS de lo que debe queda con saldo a favor; si la
    suma total de créditos supera UMBRAL_CREDITO_AFAVOR_ARS dispara la
    alerta info."""
    monkeypatch.setenv("UMBRAL_CREDITO_AFAVOR_ARS", "30000")
    _setup_caja(db)
    # Venta cta cte de $50k, cobranza de $90k → cliente queda con $40k a favor.
    db.add(Venta(
        id_pedido="P-CRD-1", id_venta="V-CRD-1",
        id_cliente=101, cliente="Cliente Adelantado SA",
        fecha=datetime.combine(date.today() - timedelta(days=10), datetime.min.time()),
        total=Decimal("50000"),
        es_cuenta_corriente=True,
        vendedor="V1",
    ))
    db.add(_cobranza_cliente(101, 90000))
    db.commit()

    alertas = evaluar_alertas(db)
    cc = next((a for a in alertas if a["codigo"] == "clientes_con_credito"), None)
    assert cc is not None
    assert cc["severidad"] == "info"
    # _to_float devuelve float — explícito 40000.0 para no depender de
    # coerción int<->float silenciosa.
    assert cc["valor"] == 40000.0  # crédito total
    assert "Cliente Adelantado SA" in cc["detalle"]
    # Decisión deliberada: clientes_con_credito NO deep-linkea — la alerta
    # es sobre el conjunto de clientes con sobrepagos, no un single entity.
    # Linkear a un cliente específico sería arbitrario. Si en el futuro
    # alguien introduce un deep link, este test los hace pensarlo.
    assert cc["link"] == "/cuentas-corrientes"


def test_clientes_con_credito_no_dispara_bajo_umbral(db, monkeypatch):
    """Si el total de créditos a favor es menor al umbral (ruido de
    centavitos), la alerta no aparece — evita spam por redondeos."""
    monkeypatch.setenv("UMBRAL_CREDITO_AFAVOR_ARS", "30000")
    _setup_caja(db)
    # Venta de $50k cobrada por $51k → solo $1k de crédito (< 30k).
    db.add(Venta(
        id_pedido="P-CRD-2", id_venta="V-CRD-2",
        id_cliente=102, cliente="Cliente Centavos SA",
        fecha=datetime.combine(date.today() - timedelta(days=10), datetime.min.time()),
        total=Decimal("50000"),
        es_cuenta_corriente=True,
        vendedor="V1",
    ))
    db.add(_cobranza_cliente(102, 51000))
    db.commit()

    alertas = evaluar_alertas(db)
    assert "clientes_con_credito" not in _codigos(alertas)


def test_clientes_con_credito_acumula_multiples_clientes(db, monkeypatch):
    """3 clientes con $15k cada uno suman $45k > umbral $30k → dispara
    aunque ninguno individual supere el umbral. Detalle incluye los 3 nombres."""
    monkeypatch.setenv("UMBRAL_CREDITO_AFAVOR_ARS", "30000")
    _setup_caja(db)
    for i, nombre in enumerate(["Cliente A", "Cliente B", "Cliente C"], start=200):
        db.add(Venta(
            id_pedido=f"P-CRD-{i}", id_venta=f"V-CRD-{i}",
            id_cliente=i, cliente=nombre,
            fecha=datetime.combine(date.today() - timedelta(days=10), datetime.min.time()),
            total=Decimal("10000"),
            es_cuenta_corriente=True,
            vendedor="V1",
        ))
        db.add(_cobranza_cliente(i, 25000))  # paga 25k de 10k → 15k a favor
    db.commit()

    alertas = evaluar_alertas(db)
    cc = next((a for a in alertas if a["codigo"] == "clientes_con_credito"), None)
    assert cc is not None
    assert cc["valor"] == 45000.0
    # Los 3 nombres deben estar listados (no truncados con "+N más" porque son <=3).
    assert "Cliente A" in cc["detalle"]
    assert "Cliente B" in cc["detalle"]
    assert "Cliente C" in cc["detalle"]
    # Match específico al patrón "(+N más)" — un literal "+" suelto en
    # otro contexto (ej: "$X+ acumulado") no debería romper este test.
    assert "(+" not in cc["detalle"]


def test_clientes_con_credito_trunca_top3_con_n_mas(db, monkeypatch):
    """Con >3 clientes con crédito, el detalle muestra top3 + (+N más)."""
    monkeypatch.setenv("UMBRAL_CREDITO_AFAVOR_ARS", "10000")
    _setup_caja(db)
    for i in range(5):
        cli_id = 300 + i
        db.add(Venta(
            id_pedido=f"P-CRD-T{i}", id_venta=f"V-CRD-T{i}",
            id_cliente=cli_id, cliente=f"Cliente T{i}",
            fecha=datetime.combine(date.today() - timedelta(days=5), datetime.min.time()),
            total=Decimal("1000"),
            es_cuenta_corriente=True,
            vendedor="V1",
        ))
        db.add(_cobranza_cliente(cli_id, 5000))  # 4k a favor por cliente
    db.commit()

    alertas = evaluar_alertas(db)
    cc = next((a for a in alertas if a["codigo"] == "clientes_con_credito"), None)
    assert cc is not None
    assert "(+2 más)" in cc["detalle"]  # 5 clientes - top3 = 2 truncados


def _venta_simple(id_pedido, id_cliente, cliente, total, dias_atras=10):
    return Venta(
        id_pedido=id_pedido, id_venta=f"V-{id_pedido}",
        id_cliente=id_cliente, cliente=cliente,
        fecha=datetime.combine(date.today() - timedelta(days=dias_atras), datetime.min.time()),
        total=Decimal(str(total)),
        es_cuenta_corriente=False,
        monto_pago1=Decimal(str(total)),  # cobrada — no entra al aging
        caja1="cl",
    )


def test_concentracion_top1_critico_dispara_critica(db):
    """1 cliente acumula >=50% de las ventas → severidad crítica."""
    _setup_caja(db)
    db.add_all([
        _venta_simple("P1", 1, "Mega Cliente SA", 800_000),
        _venta_simple("P2", 2, "Otro 1", 50_000),
        _venta_simple("P3", 3, "Otro 2", 50_000),
        _venta_simple("P4", 4, "Otro 3", 50_000),
        _venta_simple("P5", 5, "Otro 4", 50_000),
    ])
    db.commit()

    alertas = evaluar_alertas(db)
    cv = next((a for a in alertas if a["codigo"] == "concentracion_ventas"), None)
    assert cv is not None
    assert cv["severidad"] == "critica"
    assert "Mega Cliente SA" in cv["titulo"]
    # Deep link al top1 (Mega Cliente, id_cliente=1).
    assert cv["link"] == "/cuentas-corrientes?cliente=1"


def test_concentracion_top1_moderado_dispara_atencion(db):
    """top1 entre 30 y 50% → atención."""
    _setup_caja(db)
    db.add_all([
        _venta_simple("P1", 1, "Cliente A", 350_000),  # 35%
        _venta_simple("P2", 2, "Cliente B", 200_000),
        _venta_simple("P3", 3, "Cliente C", 200_000),
        _venta_simple("P4", 4, "Cliente D", 150_000),
        _venta_simple("P5", 5, "Cliente E", 100_000),
    ])
    db.commit()

    alertas = evaluar_alertas(db)
    cv = next((a for a in alertas if a["codigo"] == "concentracion_ventas"), None)
    assert cv is not None
    assert cv["severidad"] == "atencion"
    # Top1 atención también deep-linkea (Cliente A, id=1).
    assert cv["link"] == "/cuentas-corrientes?cliente=1"


def test_clientes_perdidos_deep_linkea_al_top(db, monkeypatch):
    """Cliente con >=3 pedidos históricos sin actividad en 90+ días genera
    alerta clientes_perdidos. El link va al peor (mayor monto histórico)."""
    # Reducimos DIAS_INACT y PEDIDOS_MIN para evitar setup muy verboso.
    monkeypatch.setenv("UMBRAL_DIAS_INACTIVIDAD", "60")
    monkeypatch.setenv("UMBRAL_PEDIDOS_MIN_HISTORICOS", "2")
    _setup_caja(db)
    # Cliente A: 3 pedidos históricos por $30k cada uno (total $90k), último
    # hace 90 días → es perdido.
    for i in range(3):
        db.add(Venta(
            id_pedido=f"PA-{i}", id_venta=f"VA-{i}",
            id_cliente=11, cliente="Perdido Mayor SA",
            fecha=datetime.combine(date.today() - timedelta(days=90 + i * 30), datetime.min.time()),
            total=Decimal("30000"),
            es_cuenta_corriente=False,
            monto_pago1=Decimal("30000"), caja1="cl",
            vendedor="V1",
        ))
    # Cliente B: 2 pedidos por $5k cada uno, último hace 70 días → también
    # perdido pero monto menor → NO debería ser el del deep link.
    for i in range(2):
        db.add(Venta(
            id_pedido=f"PB-{i}", id_venta=f"VB-{i}",
            id_cliente=22, cliente="Perdido Menor SRL",
            fecha=datetime.combine(date.today() - timedelta(days=70 + i * 30), datetime.min.time()),
            total=Decimal("5000"),
            es_cuenta_corriente=False,
            monto_pago1=Decimal("5000"), caja1="cl",
            vendedor="V1",
        ))
    db.commit()

    alertas = evaluar_alertas(db)
    cp = next((a for a in alertas if a["codigo"] == "clientes_perdidos"), None)
    assert cp is not None
    # Link al cliente con mayor monto histórico (Perdido Mayor SA, id=11).
    assert cp["link"] == "/cuentas-corrientes?cliente=11"


def test_concentracion_top3_alto_dispara_atencion(db):
    """top1 < 30 pero top3 >= 60% → atención por concentración."""
    _setup_caja(db)
    db.add_all([
        _venta_simple("P1", 1, "Cliente A", 250_000),  # 25%
        _venta_simple("P2", 2, "Cliente B", 220_000),
        _venta_simple("P3", 3, "Cliente C", 200_000),  # top3 = 67%
        _venta_simple("P4", 4, "Cliente D", 150_000),
        _venta_simple("P5", 5, "Cliente E", 100_000),
        _venta_simple("P6", 6, "Cliente F", 80_000),
    ])
    db.commit()

    alertas = evaluar_alertas(db)
    cv = next((a for a in alertas if a["codigo"] == "concentracion_ventas"), None)
    assert cv is not None
    assert cv["severidad"] == "atencion"
    assert "Top 3" in cv["titulo"]
    # Branch top3 NO deep-linkea — concentración colectiva, no entity individual.
    assert cv["link"] == "/comercial"


def test_concentracion_top1_exactamente_50_dispara_critica(db):
    """Caso borde: top1 == 50% exacto. La condición usa `>=`, así que
    debe disparar crítica (50% es el umbral por default)."""
    _setup_caja(db)
    db.add_all([
        _venta_simple("P1", 1, "Mitad SA", 500_000),  # 50%
        _venta_simple("P2", 2, "Otro 1", 250_000),
        _venta_simple("P3", 3, "Otro 2", 250_000),
    ])
    db.commit()

    alertas = evaluar_alertas(db)
    cv = next((a for a in alertas if a["codigo"] == "concentracion_ventas"), None)
    assert cv is not None
    assert cv["severidad"] == "critica"
    assert "Mitad SA" in cv["titulo"]


def test_concentracion_top1_exactamente_30_dispara_atencion(db):
    """Caso borde: top1 == 30% exacto. Branch atención usa `>=` → dispara."""
    _setup_caja(db)
    db.add_all([
        _venta_simple("P1", 1, "Treintipor SA", 300_000),  # 30%
        _venta_simple("P2", 2, "Otro 1", 200_000),
        _venta_simple("P3", 3, "Otro 2", 200_000),
        _venta_simple("P4", 4, "Otro 3", 150_000),
        _venta_simple("P5", 5, "Otro 4", 150_000),
    ])
    db.commit()

    alertas = evaluar_alertas(db)
    cv = next((a for a in alertas if a["codigo"] == "concentracion_ventas"), None)
    assert cv is not None
    assert cv["severidad"] == "atencion"
    assert "Treintipor SA" in cv["titulo"]


def test_concentracion_top1_29_pct_no_cae_en_top1_atencion(db):
    """Caso borde inverso: top1 == 29% NO dispara branch top1_atencion (que
    requiere >= 30%). Cae al chequeo de top3 — si top3 también está bajo
    umbral, no hay alerta. Documenta que las branches son `if/elif/elif`."""
    _setup_caja(db)
    db.add_all([
        _venta_simple("P1", 1, "Vientinueve SA", 290_000),  # 29%
        _venta_simple("P2", 2, "Otro 1", 200_000),
        _venta_simple("P3", 3, "Otro 2", 150_000),
        # Top3 = 290+200+150 = 640k = 64% del total $1M. Top3 dispara (>= 60%).
        _venta_simple("P4", 4, "Otro 3", 120_000),
        _venta_simple("P5", 5, "Otro 4", 120_000),
        _venta_simple("P6", 6, "Otro 5", 120_000),
    ])
    db.commit()

    alertas = evaluar_alertas(db)
    cv = next((a for a in alertas if a["codigo"] == "concentracion_ventas"), None)
    # Top1 atención no se disparó (29 < 30); top3 (64%) sí.
    assert cv is not None
    assert "Top 3" in cv["titulo"]  # branch top3, no top1
    assert cv["severidad"] == "atencion"


def test_concentracion_diversificada_no_dispara(db):
    """Cartera bien repartida → ninguna alerta."""
    _setup_caja(db)
    db.add_all([
        _venta_simple(f"P{i}", i, f"Cliente {i}", 100_000)
        for i in range(1, 11)
    ])
    db.commit()

    alertas = evaluar_alertas(db)
    assert "concentracion_ventas" not in _codigos(alertas)


def test_concentracion_sin_ventas_no_dispara(db):
    _setup_caja(db)
    alertas = evaluar_alertas(db)
    assert "concentracion_ventas" not in _codigos(alertas)


def test_cada_alerta_tiene_dominio(db):
    """Toda alerta emitida debe tener el campo `dominio`. Si una alerta
    nueva se agrega sin entry en el mapa DOMINIOS, cae a 'datos' por default
    (no rompe). Test guarda contra el bug de "alerta sin agrupar"."""
    _setup_caja(db)
    p = Proveedor(nombre="X")
    db.add(p)
    db.commit()
    db.refresh(p)
    db.add(FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date.today() - timedelta(days=10),
        fecha_vencimiento=date.today() - timedelta(days=2),
        total=Decimal("1000"),
    ))
    db.commit()

    alertas = evaluar_alertas(db)
    for a in alertas:
        assert "dominio" in a, f"alerta {a['codigo']} sin dominio"
        assert a["dominio"] in {"comercial", "cobranza", "caja", "datos"}, (
            f"dominio inválido: {a['dominio']} en {a['codigo']}"
        )


def test_dominios_inventario_estatico():
    """Inventario explícito: si alguien agrega una alerta nueva debe agregar
    su código a DOMINIOS o este test falla (recordatorio explícito en lugar
    del fallback silencioso a 'datos'). Si el código se renombra o elimina,
    también detecta el drift."""
    from app.kpis.alertas import DOMINIOS
    codigos_esperados = {
        # Comercial
        "caida_ventas", "caida_margen", "productos_perdida",
        "productos_dormidos", "clientes_perdidos", "concentracion_ventas",
        # Cobranza
        "cobertura_baja", "clientes_morosos", "clientes_con_credito",
        "facturas_vencidas", "facturas_por_vencer",
        # Caja
        "caja_saldo_negativo", "movimientos_atipicos", "cierres_con_diff",
        # Datos
        "casos_pendientes", "categorias_sin_familia",
        # Objetivos KPI
        "objetivo_no_cumple",
    }
    actual = set(DOMINIOS.keys())
    assert actual == codigos_esperados, (
        f"DOMINIOS desincronizado.\n"
        f"Faltan: {codigos_esperados - actual}\n"
        f"Sobran: {actual - codigos_esperados}"
    )


def test_dominios_alertas_segun_mapa(db):
    """Tipos representativos van al dominio correcto."""
    _setup_caja(db)
    # Trigger facturas vencidas (cobranza)
    p = Proveedor(nombre="X")
    db.add(p)
    db.commit()
    db.refresh(p)
    db.add(FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date.today() - timedelta(days=10),
        fecha_vencimiento=date.today() - timedelta(days=2),
        total=Decimal("5000"),
    ))
    db.commit()

    alertas = evaluar_alertas(db)
    fv = next((a for a in alertas if a["codigo"] == "facturas_vencidas"), None)
    assert fv is not None
    assert fv["dominio"] == "cobranza"


def test_cliente_moroso_bajo_umbral_no_dispara(db):
    _setup_caja(db)
    db.add(Venta(
        id_pedido="P-OLD-2", id_venta="V-OLD-2",
        id_cliente=43,
        cliente="Pequeño Deudor",
        fecha=datetime.combine(date.today() - timedelta(days=100), datetime.min.time()),
        total=Decimal("10000"),  # < UMBRAL_MOROSIDAD
        es_cuenta_corriente=True,
        vendedor="V1",
    ))
    db.commit()

    alertas = evaluar_alertas(db)
    assert "clientes_morosos" not in _codigos(alertas)
