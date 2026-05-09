"""Tests de KPIs comerciales — foco en drill-down clientes_de_producto."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.kpis.comerciales import (
    analisis_abc_productos,
    clientes_de_producto,
    clientes_perdidos,
    productos_a_perdida,
    productos_sin_venta_reciente,
    proyeccion_mes_actual,
    top_vendedores,
)
from app.models.caja import Caja
from app.models.venta import DetalleVenta, Venta


def _setup(db):
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.commit()


def test_clientes_de_producto_agrupa_por_cliente(db):
    """Un cliente con 2 compras del mismo producto suma cantidad y monto."""
    _setup(db)
    db.add_all([
        Venta(id_pedido="P1", id_venta="V1", id_cliente=1, cliente="Acme",
              fecha=datetime(2026, 4, 1), total=Decimal("500")),
        Venta(id_pedido="P2", id_venta="V2", id_cliente=1, cliente="Acme",
              fecha=datetime(2026, 4, 10), total=Decimal("800")),
        Venta(id_pedido="P3", id_venta="V3", id_cliente=2, cliente="Otro",
              fecha=datetime(2026, 4, 5), total=Decimal("200")),
    ])
    db.add_all([
        DetalleVenta(id_venta="V1", fecha=datetime(2026, 4, 1), linea_num=1,
                     producto="Detergente x5L", cantidad=Decimal("3"),
                     precio_unitario=Decimal("100"), subtotal=Decimal("300")),
        DetalleVenta(id_venta="V2", fecha=datetime(2026, 4, 10), linea_num=1,
                     producto="Detergente x5L", cantidad=Decimal("2"),
                     precio_unitario=Decimal("100"), subtotal=Decimal("200")),
        DetalleVenta(id_venta="V3", fecha=datetime(2026, 4, 5), linea_num=1,
                     producto="Detergente x5L", cantidad=Decimal("1"),
                     precio_unitario=Decimal("100"), subtotal=Decimal("100")),
        DetalleVenta(id_venta="V3", fecha=datetime(2026, 4, 5), linea_num=2,
                     producto="Otro Producto", cantidad=Decimal("1"),
                     precio_unitario=Decimal("100"), subtotal=Decimal("100")),
    ])
    db.commit()

    out = clientes_de_producto(db, producto="Detergente x5L")
    assert len(out) == 2
    # Acme: 3+2 = 5 cantidad, 300+200 = 500 monto, 2 pedidos
    acme = next(c for c in out if c["cliente"] == "Acme")
    assert acme["cantidad_total"] == 5.0
    assert acme["monto_total"] == 500.0
    assert acme["pedidos"] == 2
    assert acme["ultima_compra"].startswith("2026-04-10")
    # Otro: 1 cantidad, 100 monto, 1 pedido
    otro = next(c for c in out if c["cliente"] == "Otro")
    assert otro["cantidad_total"] == 1.0
    assert otro["monto_total"] == 100.0


def test_clientes_de_producto_orden_por_monto_desc(db):
    """Resultado ordenado por monto_total desc — Acme arriba."""
    _setup(db)
    db.add_all([
        Venta(id_pedido="P1", id_venta="V1", id_cliente=1, cliente="Acme",
              fecha=datetime(2026, 4, 1), total=Decimal("500")),
        Venta(id_pedido="P2", id_venta="V2", id_cliente=2, cliente="Otro",
              fecha=datetime(2026, 4, 1), total=Decimal("100")),
    ])
    db.add_all([
        DetalleVenta(id_venta="V1", fecha=datetime(2026, 4, 1), linea_num=1,
                     producto="X", cantidad=Decimal("5"),
                     precio_unitario=Decimal("100"), subtotal=Decimal("500")),
        DetalleVenta(id_venta="V2", fecha=datetime(2026, 4, 1), linea_num=1,
                     producto="X", cantidad=Decimal("1"),
                     precio_unitario=Decimal("100"), subtotal=Decimal("100")),
    ])
    db.commit()

    out = clientes_de_producto(db, producto="X")
    assert out[0]["cliente"] == "Acme"
    assert out[1]["cliente"] == "Otro"


def test_clientes_de_producto_filtra_por_fecha(db):
    """Filtro desde/hasta excluye compras fuera del rango."""
    _setup(db)
    db.add_all([
        Venta(id_pedido="P1", id_venta="V1", id_cliente=1, cliente="Acme",
              fecha=datetime(2026, 3, 1), total=Decimal("500")),  # antes
        Venta(id_pedido="P2", id_venta="V2", id_cliente=1, cliente="Acme",
              fecha=datetime(2026, 4, 15), total=Decimal("800")),  # dentro
    ])
    db.add_all([
        DetalleVenta(id_venta="V1", fecha=datetime(2026, 3, 1), linea_num=1,
                     producto="X", cantidad=Decimal("1"),
                     precio_unitario=Decimal("500"), subtotal=Decimal("500")),
        DetalleVenta(id_venta="V2", fecha=datetime(2026, 4, 15), linea_num=1,
                     producto="X", cantidad=Decimal("2"),
                     precio_unitario=Decimal("400"), subtotal=Decimal("800")),
    ])
    db.commit()

    out = clientes_de_producto(db, producto="X",
                                desde=date(2026, 4, 1), hasta=date(2026, 4, 30))
    assert len(out) == 1
    assert out[0]["monto_total"] == 800.0
    assert out[0]["cantidad_total"] == 2.0


def test_clientes_de_producto_sin_match_devuelve_vacio(db):
    _setup(db)
    out = clientes_de_producto(db, producto="No Existe")
    assert out == []


def test_clientes_de_producto_excluye_id_cliente_null(db):
    """Compras de mostrador (id_cliente=None) no son atribuibles."""
    _setup(db)
    db.add(Venta(id_pedido="P1", id_venta="V1", id_cliente=None, cliente="Mostrador",
                 fecha=datetime(2026, 4, 1), total=Decimal("500")))
    db.add(DetalleVenta(id_venta="V1", fecha=datetime(2026, 4, 1), linea_num=1,
                        producto="X", cantidad=Decimal("1"),
                        precio_unitario=Decimal("500"), subtotal=Decimal("500")))
    db.commit()

    out = clientes_de_producto(db, producto="X")
    assert out == []


# ===== Tests de clientes_perdidos =====

def _venta_dias_atras(id_pedido, id_cliente, cliente, dias, total=Decimal("100")):
    """Helper: venta con fecha = today - dias."""
    return Venta(
        id_pedido=id_pedido, id_venta=f"V-{id_pedido}",
        id_cliente=id_cliente, cliente=cliente,
        fecha=datetime.combine(date.today() - timedelta(days=dias),
                                datetime.min.time()),
        total=total,
    )


def test_clientes_perdidos_detecta_caso_clasico(db):
    """Cliente con 4 pedidos en últimos 6 meses, ninguno hace 100+ días → perdido."""
    _setup(db)
    db.add_all([
        _venta_dias_atras("P1", 42, "Cliente Inactivo", 200),  # > 90d
        _venta_dias_atras("P2", 42, "Cliente Inactivo", 180),
        _venta_dias_atras("P3", 42, "Cliente Inactivo", 150),
        _venta_dias_atras("P4", 42, "Cliente Inactivo", 100),  # > 90d
    ])
    db.commit()

    out = clientes_perdidos(db, dias_inactividad=90, pedidos_minimos=3)
    assert len(out) == 1
    assert out[0]["id_cliente"] == 42
    assert out[0]["pedidos_en_ventana"] == 4
    assert out[0]["dias_sin_comprar"] == 100


def test_clientes_perdidos_excluye_si_compro_recientemente(db):
    """Cliente con 4 pedidos viejos pero 1 reciente NO es perdido."""
    _setup(db)
    db.add_all([
        _venta_dias_atras("P1", 42, "Cliente Activo", 200),
        _venta_dias_atras("P2", 42, "Cliente Activo", 150),
        _venta_dias_atras("P3", 42, "Cliente Activo", 100),
        _venta_dias_atras("P4", 42, "Cliente Activo", 30),  # reciente
    ])
    db.commit()

    out = clientes_perdidos(db, dias_inactividad=90, pedidos_minimos=3)
    assert out == []


def test_clientes_perdidos_excluye_clientes_ocasionales(db):
    """Cliente con solo 2 pedidos en histórico no califica (umbral default 3)."""
    _setup(db)
    db.add_all([
        _venta_dias_atras("P1", 42, "Comprador Ocasional", 200),
        _venta_dias_atras("P2", 42, "Comprador Ocasional", 150),
    ])
    db.commit()

    out = clientes_perdidos(db, dias_inactividad=90, pedidos_minimos=3)
    assert out == []  # solo 2 pedidos, no llega al umbral


def test_clientes_perdidos_orden_por_monto_desc(db):
    """Clientes perdidos ordenados por monto histórico — el de mayor impacto arriba."""
    _setup(db)
    # Cliente chico
    db.add_all([
        _venta_dias_atras("P1", 1, "Cliente Chico", 200, Decimal("100")),
        _venta_dias_atras("P2", 1, "Cliente Chico", 180, Decimal("100")),
        _venta_dias_atras("P3", 1, "Cliente Chico", 150, Decimal("100")),
    ])
    # Cliente grande
    db.add_all([
        _venta_dias_atras("P4", 2, "Cliente Grande", 200, Decimal("5000")),
        _venta_dias_atras("P5", 2, "Cliente Grande", 180, Decimal("5000")),
        _venta_dias_atras("P6", 2, "Cliente Grande", 150, Decimal("5000")),
    ])
    db.commit()

    out = clientes_perdidos(db, dias_inactividad=90, pedidos_minimos=3)
    assert len(out) == 2
    assert out[0]["cliente"] == "Cliente Grande"  # mayor monto primero
    assert out[1]["cliente"] == "Cliente Chico"


def test_clientes_perdidos_excluye_id_cliente_null(db):
    """Compras de mostrador no se cuentan."""
    _setup(db)
    db.add_all([
        _venta_dias_atras("P1", None, "Mostrador", 200),
        _venta_dias_atras("P2", None, "Mostrador", 180),
        _venta_dias_atras("P3", None, "Mostrador", 150),
    ])
    db.commit()

    out = clientes_perdidos(db, dias_inactividad=90, pedidos_minimos=3)
    assert out == []


# ===== Tests de productos_sin_venta_reciente =====

def _detalle_dias_atras(id_pedido, producto, dias, monto=Decimal("100")):
    """Helper: línea de detalle con fecha = today - dias."""
    return DetalleVenta(
        id_venta=f"V-{id_pedido}",
        fecha=datetime.combine(date.today() - timedelta(days=dias),
                                datetime.min.time()),
        linea_num=1,
        producto=producto,
        cantidad=Decimal("1"),
        precio_unitario=monto,
        subtotal=monto,
    )


def test_productos_dormidos_caso_clasico(db):
    """Producto con 6 ventas en últimos 7m, ninguna en últimos 70 días."""
    _setup(db)
    db.add_all([
        Venta(id_pedido=f"P{i}", id_venta=f"V-P{i}",
              fecha=datetime.combine(date.today() - timedelta(days=d),
                                      datetime.min.time()),
              total=Decimal("100"))
        for i, d in enumerate([200, 180, 160, 140, 120, 100], start=1)
    ])
    db.add_all([
        _detalle_dias_atras(f"P{i}", "Producto Inactivo", d)
        for i, d in enumerate([200, 180, 160, 140, 120, 100], start=1)
    ])
    db.commit()

    out = productos_sin_venta_reciente(db, dias_inactividad=60, ventas_minimas=5)
    assert len(out) == 1
    assert out[0]["producto"] == "Producto Inactivo"
    assert out[0]["ventas_en_ventana"] == 6


def test_productos_dormidos_excluye_si_se_vendio_reciente(db):
    """Producto con ventas viejas pero 1 reciente NO es dormido."""
    _setup(db)
    db.add_all([
        Venta(id_pedido=f"P{i}", id_venta=f"V-P{i}",
              fecha=datetime.combine(date.today() - timedelta(days=d),
                                      datetime.min.time()),
              total=Decimal("100"))
        for i, d in enumerate([200, 180, 160, 140, 120, 30], start=1)
    ])
    db.add_all([
        _detalle_dias_atras(f"P{i}", "Producto Activo", d)
        for i, d in enumerate([200, 180, 160, 140, 120, 30], start=1)
    ])
    db.commit()

    out = productos_sin_venta_reciente(db, dias_inactividad=60, ventas_minimas=5)
    assert out == []


def test_productos_dormidos_excluye_si_pocas_ventas_historicas(db):
    """Producto con solo 3 ventas en histórico — no llega a umbral 5."""
    _setup(db)
    db.add_all([
        Venta(id_pedido=f"P{i}", id_venta=f"V-P{i}",
              fecha=datetime.combine(date.today() - timedelta(days=d),
                                      datetime.min.time()),
              total=Decimal("100"))
        for i, d in enumerate([200, 180, 160], start=1)
    ])
    db.add_all([
        _detalle_dias_atras(f"P{i}", "Producto Ocasional", d)
        for i, d in enumerate([200, 180, 160], start=1)
    ])
    db.commit()

    out = productos_sin_venta_reciente(db, dias_inactividad=60, ventas_minimas=5)
    assert out == []


def test_productos_dormidos_orden_por_monto_desc(db):
    """Productos dormidos ordenados por monto histórico desc."""
    _setup(db)
    fechas = [200, 180, 160, 140, 120, 100]
    db.add_all([
        Venta(id_pedido=f"P{i}", id_venta=f"V-P{i}",
              fecha=datetime.combine(date.today() - timedelta(days=d),
                                      datetime.min.time()),
              total=Decimal("100"))
        for i, d in enumerate(fechas + fechas, start=1)
    ])
    db.add_all([
        _detalle_dias_atras(f"P{i}", "Producto Chico", d, Decimal("50"))
        for i, d in enumerate(fechas, start=1)
    ])
    db.add_all([
        _detalle_dias_atras(f"P{i}", "Producto Grande", d, Decimal("5000"))
        for i, d in enumerate(fechas, start=7)
    ])
    db.commit()

    out = productos_sin_venta_reciente(db, dias_inactividad=60, ventas_minimas=5)
    assert len(out) == 2
    assert out[0]["producto"] == "Producto Grande"
    assert out[1]["producto"] == "Producto Chico"


# ===== Tests de analisis_abc_productos =====

def _detalle_mercaderia(id_pedido, producto, ingreso, costo):
    """Helper: crea línea de detalle clasificada como mercadería con CST."""
    return DetalleVenta(
        id_venta=f"V-{id_pedido}",
        fecha=datetime(2026, 4, 1),
        linea_num=1,
        producto=producto,
        cantidad=Decimal("1"),
        precio_unitario=Decimal(str(ingreso)),
        subtotal=Decimal(str(ingreso)),
        cst=Decimal(str(costo)),
        categoria_linea="mercaderia",
    )


def test_abc_clasifica_pareto_clasico(db):
    """Top product genera 80% del margen → A. Resto distribuido en B/C."""
    _setup(db)
    # Producto A: $800 de margen (80%)
    db.add(Venta(id_pedido="P1", id_venta="V-P1", id_cliente=1,
                 fecha=datetime(2026, 4, 1), total=Decimal("1000")))
    db.add(_detalle_mercaderia("P1", "Estrella", 1000, 200))  # margen 800
    # Producto B: $150 de margen (15%)
    db.add(Venta(id_pedido="P2", id_venta="V-P2", id_cliente=2,
                 fecha=datetime(2026, 4, 1), total=Decimal("200")))
    db.add(_detalle_mercaderia("P2", "Mediano", 200, 50))  # margen 150
    # Producto C: $50 de margen (5%)
    db.add(Venta(id_pedido="P3", id_venta="V-P3", id_cliente=3,
                 fecha=datetime(2026, 4, 1), total=Decimal("100")))
    db.add(_detalle_mercaderia("P3", "Chico", 100, 50))  # margen 50
    db.commit()

    out = analisis_abc_productos(db)
    productos = out["productos"]
    assert len(productos) == 3
    # Orden por margen desc
    assert productos[0]["producto"] == "Estrella"
    assert productos[0]["categoria_abc"] == "A"
    # 80% acumulado → todavía está dentro de A (umbral 80 inclusive)
    assert productos[1]["producto"] == "Mediano"
    assert productos[1]["categoria_abc"] == "B"  # 95% acum → B
    assert productos[2]["producto"] == "Chico"
    assert productos[2]["categoria_abc"] == "C"  # >95% → C
    assert out["totales"]["a"] == 1
    assert out["totales"]["b"] == 1
    assert out["totales"]["c"] == 1


def test_abc_dataset_vacio_devuelve_estructura(db):
    _setup(db)
    out = analisis_abc_productos(db)
    assert out["totales"]["productos"] == 0
    assert out["productos"] == []


def test_abc_excluye_lineas_no_mercaderia(db):
    """Solo cuenta líneas con `categoria_linea = mercaderia` y CST cargado.
    Mismo criterio que top_productos para no contaminar con descuentos/recargos."""
    _setup(db)
    db.add(Venta(id_pedido="P1", id_venta="V-P1", id_cliente=1,
                 fecha=datetime(2026, 4, 1), total=Decimal("100")))
    # Línea de descuento (no mercadería)
    db.add(DetalleVenta(
        id_venta="V-P1", fecha=datetime(2026, 4, 1), linea_num=1,
        producto="Descuento", cantidad=Decimal("1"),
        precio_unitario=Decimal("-50"), subtotal=Decimal("-50"),
        cst=Decimal("0"), categoria_linea="descuento",
    ))
    db.commit()

    out = analisis_abc_productos(db)
    assert out["productos"] == []


def test_abc_acumulado_pct_consistente(db):
    """El último producto debe llegar a ~100% acumulado."""
    _setup(db)
    for i, m in enumerate([500, 300, 200], start=1):
        db.add(Venta(id_pedido=f"P{i}", id_venta=f"V-P{i}", id_cliente=i,
                     fecha=datetime(2026, 4, 1), total=Decimal(str(m * 2))))
        db.add(_detalle_mercaderia(f"P{i}", f"Prod{i}", m * 2, m))
    db.commit()

    out = analisis_abc_productos(db)
    # Último producto debe tener acumulado ≈ 100% (con tolerancia de redondeo)
    ultimo = out["productos"][-1]
    assert 99.0 <= ultimo["margen_acumulado_pct"] <= 100.5


def test_abc_producto_unico_es_A(db):
    """Caso borde: catálogo con 1 solo producto. 100% acumulado > 80
    pero forzamos a A porque ESE producto es el negocio."""
    _setup(db)
    db.add(Venta(id_pedido="P1", id_venta="V-P1", id_cliente=1,
                 fecha=datetime(2026, 4, 1), total=Decimal("1000")))
    db.add(_detalle_mercaderia("P1", "Único Producto", 1000, 200))
    db.commit()

    out = analisis_abc_productos(db)
    assert len(out["productos"]) == 1
    assert out["productos"][0]["categoria_abc"] == "A"
    assert out["totales"]["a"] == 1


def test_abc_margen_total_negativo_no_clasifica(db):
    """Si todos los productos van a pérdida (margen total ≤ 0), la clasificación
    Pareto no tiene sentido — devolvemos categoria_abc = None en lugar de
    inventar un Pareto inexistente."""
    _setup(db)
    db.add(Venta(id_pedido="P1", id_venta="V-P1", id_cliente=1,
                 fecha=datetime(2026, 4, 1), total=Decimal("100")))
    # Producto vendido a costo: ingreso 100, costo 150 → margen -50
    db.add(_detalle_mercaderia("P1", "Perdedor", 100, 150))
    db.commit()

    out = analisis_abc_productos(db)
    assert len(out["productos"]) == 1
    assert out["productos"][0]["categoria_abc"] is None
    assert out["totales"]["a"] == 0
    assert out["totales"]["b"] == 0
    assert out["totales"]["c"] == 0


def test_abc_orden_estable_en_empates(db):
    """Dos productos con margen idéntico → orden alfabético (tiebreaker
    determinista). Sin esto la clasificación A/B podía flipar entre runs."""
    _setup(db)
    # 3 productos con margen igual: 100 cada uno (acum 33%, 67%, 100%)
    for i, prod in enumerate(["Charlie", "Alpha", "Bravo"], start=1):
        db.add(Venta(id_pedido=f"P{i}", id_venta=f"V-P{i}", id_cliente=i,
                     fecha=datetime(2026, 4, 1), total=Decimal("200")))
        db.add(_detalle_mercaderia(f"P{i}", prod, 200, 100))
    db.commit()

    out = analisis_abc_productos(db)
    productos = out["productos"]
    # Tiebreaker alfabético: Alpha < Bravo < Charlie
    assert productos[0]["producto"] == "Alpha"
    assert productos[1]["producto"] == "Bravo"
    assert productos[2]["producto"] == "Charlie"


# ===== Tests de proyeccion_mes_actual =====

def test_proyeccion_mes_estructura_basica(db):
    """La función devuelve siempre las claves clave aunque no haya datos."""
    _setup(db)
    out = proyeccion_mes_actual(db)
    for k in ("mes", "dias_transcurridos", "dias_totales",
              "ventas_a_la_fecha", "pedidos_a_la_fecha",
              "proyectado_cierre", "anio_anterior_mismo_mes"):
        assert k in out, f"falta {k}"
    # mes debería tener formato YYYY-MM
    assert len(out["mes"]) == 7 and out["mes"][4] == "-"


def test_proyeccion_mes_extrapolacion_lineal(db, monkeypatch):
    """Día 15 de abril, 15 ventas de $1000 → proyectado ≈ $30000 (30 días×$1k).

    Mockeamos `hoy_ar` para fijar la fecha y eliminar el skip silencioso
    que antes hacía que el test "pasara" sin verificar nada cuando corría
    en los primeros 2 días del mes.
    """
    _setup(db)
    fecha_fija = date(2026, 4, 15)
    monkeypatch.setattr("app.kpis.comerciales.hoy_ar", lambda: fecha_fija)

    primer_dia = fecha_fija.replace(day=1)
    for i in range(fecha_fija.day):
        f = primer_dia + timedelta(days=i)
        db.add(Venta(
            id_pedido=f"P-PR-{i}", id_venta=f"V-PR-{i}",
            id_cliente=1, cliente="X",
            fecha=datetime.combine(f, datetime.min.time()),
            total=Decimal("1000"),
        ))
    db.commit()

    out = proyeccion_mes_actual(db)
    assert out["proyectado_cierre"] is not None
    assert out["dias_transcurridos"] == 15
    assert out["dias_totales"] == 30  # abril
    # Con tasa $1000/día, proyectado = $1000 × 30 = $30.000
    esperado = 1000.0 * 30
    assert abs(out["proyectado_cierre"] - esperado) < esperado * 0.01


def test_proyeccion_mes_recien_empezado_no_proyecta(db, monkeypatch):
    """Día 1 del mes: la función devuelve proyectado_cierre=None para no
    proyectar con base ruidosa (1 solo día observado)."""
    _setup(db)
    monkeypatch.setattr("app.kpis.comerciales.hoy_ar", lambda: date(2026, 4, 1))

    out = proyeccion_mes_actual(db)
    assert out["proyectado_cierre"] is None
    assert out["dias_transcurridos"] == 1


def test_proyeccion_mes_ultimo_dia_si_proyecta(db, monkeypatch):
    """Último día del mes (30/abril): la condición `<=` permite que el día 30
    entre y la proyección termine siendo igual a las ventas reales."""
    _setup(db)
    monkeypatch.setattr("app.kpis.comerciales.hoy_ar", lambda: date(2026, 4, 30))

    primer_dia = date(2026, 4, 1)
    for i in range(30):
        f = primer_dia + timedelta(days=i)
        db.add(Venta(
            id_pedido=f"P-UD-{i}", id_venta=f"V-UD-{i}",
            id_cliente=1, cliente="X",
            fecha=datetime.combine(f, datetime.min.time()),
            total=Decimal("500"),
        ))
    db.commit()

    out = proyeccion_mes_actual(db)
    # 30 días × $500 = $15.000 ventas reales = proyección.
    assert out["proyectado_cierre"] is not None
    assert abs(out["proyectado_cierre"] - 15000.0) < 0.01
    assert out["dias_transcurridos"] == 30


# ===== Tests de productos_a_perdida =====
# Detector crítico de safety: productos vendidos por debajo del costo (margen
# agregado negativo). Antes solo testeado indirecto vía alertas — agregamos
# tests directos para fijar el contrato del KPI.

def _detalle_perdida(id_pedido, producto, ingreso, costo, **extra):
    """Helper: detalle de mercadería con CST. ingreso < costo = pérdida."""
    return DetalleVenta(
        id_venta=f"V-{id_pedido}",
        fecha=datetime(2026, 4, 1),
        linea_num=1,
        producto=producto,
        cantidad=Decimal(str(extra.get("cantidad", "1"))),
        precio_unitario=Decimal(str(ingreso)),
        subtotal=Decimal(str(ingreso)),
        cst=Decimal(str(costo)),
        categoria_linea="mercaderia",
    )


def test_productos_a_perdida_detecta_caso_clasico(db):
    """Producto vendido a $80 con costo $100 → margen -$20 detectado."""
    _setup(db)
    db.add(Venta(id_pedido="P1", id_venta="V-P1", id_cliente=1, cliente="X",
                 fecha=datetime(2026, 4, 1), total=Decimal("80")))
    db.add(_detalle_perdida("P1", "Producto Loss", 80, 100))
    db.commit()

    out = productos_a_perdida(db)
    assert len(out) == 1
    assert out[0]["producto"] == "Producto Loss"
    assert out[0]["margen"] == -20.0
    assert out[0]["ingresos"] == 80.0
    assert out[0]["costo"] == 100.0


def test_productos_a_perdida_excluye_margen_positivo(db):
    """Producto rentable (ingreso > costo) NO aparece en el listado."""
    _setup(db)
    db.add(Venta(id_pedido="P1", id_venta="V-P1", id_cliente=1, cliente="X",
                 fecha=datetime(2026, 4, 1), total=Decimal("150")))
    db.add(_detalle_perdida("P1", "Producto OK", 150, 100))  # margen +50
    db.commit()

    out = productos_a_perdida(db)
    assert out == []


def test_productos_a_perdida_excluye_margen_cero(db):
    """Margen exactamente 0 NO entra (la condición es estrictamente < 0).

    Decisión de jurado adversarial:
    - Conservador (gana): "pérdida" semánticamente = ROJO; vender al costo
      es práctica deliberada de PyMEs (combos, retención); diluir el alert
      con neutros pierde señal de pérdida real.
    - Pragmático (pierde, pero argumenta válido): vender al costo no cubre
      overhead, es prelude a negativo si sube costo.
    - Síntesis: si se necesita señal "sin rentabilidad", crear alert SEPARADO
      (`productos_sin_margen`), NO mezclar con éste.
    """
    _setup(db)
    db.add(Venta(id_pedido="P1", id_venta="V-P1", id_cliente=1, cliente="X",
                 fecha=datetime(2026, 4, 1), total=Decimal("100")))
    db.add(_detalle_perdida("P1", "Break-even", 100, 100))  # margen 0
    db.commit()

    out = productos_a_perdida(db)
    assert out == []


def test_productos_a_perdida_tiebreaker_nombre_alfabetico(db):
    """Empate de margen → tiebreaker alfabético por producto. Sin esto, el
    orden depende del optimizador SQLite y puede flickear entre runs."""
    _setup(db)
    # Dos productos con margen exactamente -10 cada uno.
    db.add(Venta(id_pedido="P1", id_venta="V-P1", id_cliente=1, cliente="X",
                 fecha=datetime(2026, 4, 1), total=Decimal("90")))
    db.add(_detalle_perdida("P1", "Pan", 90, 100))
    db.add(Venta(id_pedido="P2", id_venta="V-P2", id_cliente=1, cliente="X",
                 fecha=datetime(2026, 4, 1), total=Decimal("90")))
    db.add(_detalle_perdida("P2", "Leche", 90, 100))
    db.add(Venta(id_pedido="P3", id_venta="V-P3", id_cliente=1, cliente="X",
                 fecha=datetime(2026, 4, 1), total=Decimal("90")))
    db.add(_detalle_perdida("P3", "Azúcar", 90, 100))
    db.commit()

    out = productos_a_perdida(db)
    # Margen igual → orden alfabético ASC: Azúcar, Leche, Pan
    assert [p["producto"] for p in out] == ["Azúcar", "Leche", "Pan"]


def test_productos_a_perdida_agrega_multiple_ventas_del_mismo_producto(db):
    """Mismo producto en 3 ventas: 2 a pérdida, 1 a ganancia. Si la suma
    es negativa, el producto aparece. Crucial para casos donde una venta
    a precio promo tira el margen aunque otras compensen parcialmente."""
    _setup(db)
    # Venta 1: -$30 margen
    db.add(Venta(id_pedido="P1", id_venta="V-P1", id_cliente=1, cliente="X",
                 fecha=datetime(2026, 4, 1), total=Decimal("70")))
    db.add(_detalle_perdida("P1", "Producto Mix", 70, 100))
    # Venta 2: -$30 margen
    db.add(Venta(id_pedido="P2", id_venta="V-P2", id_cliente=1, cliente="X",
                 fecha=datetime(2026, 4, 2), total=Decimal("70")))
    db.add(_detalle_perdida("P2", "Producto Mix", 70, 100))
    # Venta 3: +$20 margen
    db.add(Venta(id_pedido="P3", id_venta="V-P3", id_cliente=1, cliente="X",
                 fecha=datetime(2026, 4, 3), total=Decimal("120")))
    db.add(_detalle_perdida("P3", "Producto Mix", 120, 100))
    db.commit()

    out = productos_a_perdida(db)
    assert len(out) == 1
    # Suma: 70+70+120 = 260 ingresos, 100+100+100 = 300 costo, margen -40
    assert out[0]["margen"] == -40.0
    assert out[0]["ingresos"] == 260.0


def test_productos_a_perdida_excluye_categoria_no_mercaderia(db):
    """Líneas no-mercadería (ej: descuento, flete) NO entran en el cálculo
    de margen — solo productos físicos vendidos."""
    _setup(db)
    db.add(Venta(id_pedido="P1", id_venta="V-P1", id_cliente=1, cliente="X",
                 fecha=datetime(2026, 4, 1), total=Decimal("50")))
    # Línea NO mercaderia con margen negativo: NO debe aparecer.
    db.add(DetalleVenta(
        id_venta="V-P1",
        fecha=datetime(2026, 4, 1),
        linea_num=1,
        producto="Descuento",
        cantidad=Decimal("1"),
        precio_unitario=Decimal("50"),
        subtotal=Decimal("50"),
        cst=Decimal("100"),  # costo > ingreso, sería negativo si entrara
        categoria_linea="descuento",
    ))
    db.commit()

    out = productos_a_perdida(db)
    assert out == []


def test_productos_a_perdida_excluye_sin_cst(db):
    """Detalle sin costo (cst=NULL) no se puede evaluar margen — se ignora.
    Hace falta cst para calcular pérdida, sino no se puede afirmar nada."""
    _setup(db)
    db.add(Venta(id_pedido="P1", id_venta="V-P1", id_cliente=1, cliente="X",
                 fecha=datetime(2026, 4, 1), total=Decimal("50")))
    db.add(DetalleVenta(
        id_venta="V-P1",
        fecha=datetime(2026, 4, 1),
        linea_num=1,
        producto="Producto Sin Costo",
        cantidad=Decimal("1"),
        precio_unitario=Decimal("50"),
        subtotal=Decimal("50"),
        cst=None,  # NULL — no se puede saber si hay pérdida
        categoria_linea="mercaderia",
    ))
    db.commit()

    out = productos_a_perdida(db)
    assert out == []


def test_productos_a_perdida_orden_peor_primero(db):
    """Orden por margen ASC (negativos crecientes en magnitud) — el peor
    arriba. La dueña ve primero el producto que MÁS le hace perder."""
    _setup(db)
    # Producto A: margen -$10
    db.add(Venta(id_pedido="PA", id_venta="V-PA", id_cliente=1, cliente="X",
                 fecha=datetime(2026, 4, 1), total=Decimal("90")))
    db.add(_detalle_perdida("PA", "Pérdida Chica", 90, 100))
    # Producto B: margen -$50 (peor)
    db.add(Venta(id_pedido="PB", id_venta="V-PB", id_cliente=1, cliente="X",
                 fecha=datetime(2026, 4, 1), total=Decimal("50")))
    db.add(_detalle_perdida("PB", "Pérdida Grande", 50, 100))
    # Producto C: margen -$25
    db.add(Venta(id_pedido="PC", id_venta="V-PC", id_cliente=1, cliente="X",
                 fecha=datetime(2026, 4, 1), total=Decimal("75")))
    db.add(_detalle_perdida("PC", "Pérdida Media", 75, 100))
    db.commit()

    out = productos_a_perdida(db)
    # Orden esperado: B (-50), C (-25), A (-10)
    assert [p["producto"] for p in out] == [
        "Pérdida Grande", "Pérdida Media", "Pérdida Chica",
    ]


def test_productos_a_perdida_respeta_limite(db):
    """Limite=2 corta a top 2 (los peores). Default es 50."""
    _setup(db)
    for i in range(5):
        db.add(Venta(id_pedido=f"P{i}", id_venta=f"V-P{i}", id_cliente=1, cliente="X",
                     fecha=datetime(2026, 4, 1), total=Decimal("50")))
        # Cada uno con margen -10*(i+1): -10, -20, -30, -40, -50
        db.add(_detalle_perdida(f"P{i}", f"Prod{i}", 50, 50 + 10 * (i + 1)))
    db.commit()

    out = productos_a_perdida(db, limite=2)
    assert len(out) == 2
    # Los 2 peores: Prod4 (-50), Prod3 (-40)
    assert out[0]["producto"] == "Prod4"
    assert out[1]["producto"] == "Prod3"


def test_productos_a_perdida_sin_ventas_devuelve_vacio(db):
    """Caso default sin datos: array vacío, no error."""
    _setup(db)
    out = productos_a_perdida(db)
    assert out == []


def test_productos_a_perdida_filtra_por_fecha(db):
    """Producto a pérdida fuera del rango desde/hasta NO aparece."""
    _setup(db)
    # Venta DENTRO del rango (abril): margen -20
    db.add(Venta(id_pedido="P-IN", id_venta="V-P-IN", id_cliente=1, cliente="X",
                 fecha=datetime(2026, 4, 15), total=Decimal("80")))
    db.add(DetalleVenta(
        id_venta="V-P-IN", fecha=datetime(2026, 4, 15), linea_num=1,
        producto="In", cantidad=Decimal("1"),
        precio_unitario=Decimal("80"), subtotal=Decimal("80"),
        cst=Decimal("100"), categoria_linea="mercaderia",
    ))
    # Venta FUERA (mayo): margen -30
    db.add(Venta(id_pedido="P-OUT", id_venta="V-P-OUT", id_cliente=1, cliente="X",
                 fecha=datetime(2026, 5, 1), total=Decimal("70")))
    db.add(DetalleVenta(
        id_venta="V-P-OUT", fecha=datetime(2026, 5, 1), linea_num=1,
        producto="Out", cantidad=Decimal("1"),
        precio_unitario=Decimal("70"), subtotal=Decimal("70"),
        cst=Decimal("100"), categoria_linea="mercaderia",
    ))
    db.commit()

    out = productos_a_perdida(db, desde=date(2026, 4, 1), hasta=date(2026, 4, 30))
    assert len(out) == 1
    assert out[0]["producto"] == "In"


# ===== Tests de top_vendedores =====
# KPI usado en /comercial dashboard. Tiene lógica no trivial:
# - LEFT JOIN con DetalleVenta para margen (solo mercadería con cst)
# - Sort por ventas DESC
# - Clientes únicos via distinct
# - Vendedor NULL excluido

def _venta_vendedor(id_pedido, vendedor, total, id_cliente=1, fecha=None):
    return Venta(
        id_pedido=id_pedido, id_venta=f"V-{id_pedido}",
        id_cliente=id_cliente, cliente=f"Cliente{id_cliente}",
        vendedor=vendedor,
        fecha=fecha or datetime(2026, 4, 1),
        total=Decimal(str(total)),
    )


def test_top_vendedores_caso_basico(db):
    """1 vendedor con 1 venta → estructura completa correcta."""
    _setup(db)
    db.add(_venta_vendedor("P1", "Ana", 1000, id_cliente=1))
    db.add(_detalle_mercaderia("P1", "Producto", 1000, 600))  # margen 400
    db.commit()

    out = top_vendedores(db)
    assert len(out) == 1
    v = out[0]
    assert v["vendedor"] == "Ana"
    assert v["pedidos"] == 1
    assert v["ventas"] == 1000.0
    assert v["clientes"] == 1
    assert v["ticket_promedio"] == 1000.0
    assert v["margen"] == 400.0


def test_top_vendedores_orden_por_ventas_desc(db):
    """Múltiples vendedores → orden por ventas DESC, top primero."""
    _setup(db)
    # Ana: $300, Beto: $1000 (top), Carla: $500
    db.add_all([
        _venta_vendedor("P1", "Ana", 300, id_cliente=1),
        _venta_vendedor("P2", "Beto", 1000, id_cliente=2),
        _venta_vendedor("P3", "Carla", 500, id_cliente=3),
    ])
    db.commit()

    out = top_vendedores(db)
    assert [v["vendedor"] for v in out] == ["Beto", "Carla", "Ana"]


def test_top_vendedores_clientes_unicos_no_duplica(db):
    """Vendedor vende 3 veces al MISMO cliente → clientes_unicos=1, no 3."""
    _setup(db)
    db.add_all([
        _venta_vendedor("P1", "Ana", 100, id_cliente=42),
        _venta_vendedor("P2", "Ana", 200, id_cliente=42),
        _venta_vendedor("P3", "Ana", 300, id_cliente=42),
    ])
    db.commit()

    out = top_vendedores(db)
    assert out[0]["clientes"] == 1
    assert out[0]["pedidos"] == 3


def test_top_vendedores_ticket_promedio_correcto(db):
    """Ticket promedio = sum(total) / count(pedidos)."""
    _setup(db)
    db.add_all([
        _venta_vendedor("P1", "Ana", 100, id_cliente=1),
        _venta_vendedor("P2", "Ana", 200, id_cliente=2),
        _venta_vendedor("P3", "Ana", 300, id_cliente=3),
    ])
    db.commit()

    out = top_vendedores(db)
    # Ventas=600, pedidos=3, ticket=200
    assert out[0]["ticket_promedio"] == 200.0


def test_top_vendedores_margen_solo_mercaderia_con_cst(db):
    """Margen suma SOLO líneas categoria_linea='mercaderia' con cst NOT NULL.
    Líneas de descuento o sin cst NO entran al margen."""
    _setup(db)
    db.add(_venta_vendedor("P1", "Ana", 1000, id_cliente=1))
    # Línea válida: mercadería con cst → margen 400
    db.add(_detalle_mercaderia("P1", "ProdReal", 1000, 600))
    # Línea descuento: NO entra al margen.
    db.add(DetalleVenta(
        id_venta="V-P1", fecha=datetime(2026, 4, 1), linea_num=2,
        producto="Descuento", cantidad=Decimal("1"),
        precio_unitario=Decimal("-100"), subtotal=Decimal("-100"),
        cst=Decimal("0"), categoria_linea="descuento",
    ))
    # Línea sin cst: NO entra al margen.
    db.add(DetalleVenta(
        id_venta="V-P1", fecha=datetime(2026, 4, 1), linea_num=3,
        producto="ProdSinCsto", cantidad=Decimal("1"),
        precio_unitario=Decimal("100"), subtotal=Decimal("100"),
        cst=None, categoria_linea="mercaderia",
    ))
    db.commit()

    out = top_vendedores(db)
    # Solo cuenta el margen de la línea válida.
    assert out[0]["margen"] == 400.0


def test_top_vendedores_excluye_vendedor_null(db):
    """Ventas sin vendedor (vendedor=NULL) NO aparecen en el listado."""
    _setup(db)
    db.add_all([
        _venta_vendedor("P1", "Ana", 100, id_cliente=1),
        _venta_vendedor("P2", None, 500, id_cliente=2),  # NULL
    ])
    db.commit()

    out = top_vendedores(db)
    assert len(out) == 1
    assert out[0]["vendedor"] == "Ana"


def test_top_vendedores_respeta_limite(db):
    """limite=2 corta a top 2 (los de mayor ventas)."""
    _setup(db)
    for i in range(5):
        db.add(_venta_vendedor(f"P{i}", f"V{i}", 100 * (i + 1), id_cliente=i + 1))
    db.commit()

    out = top_vendedores(db, limite=2)
    assert len(out) == 2
    # Top 2 por ventas: V4 ($500), V3 ($400)
    assert [v["vendedor"] for v in out] == ["V4", "V3"]


def test_top_vendedores_filtra_por_fecha(db):
    """Ventas fuera del rango desde/hasta NO entran."""
    _setup(db)
    db.add_all([
        _venta_vendedor("P-IN", "Ana", 500, id_cliente=1, fecha=datetime(2026, 4, 15)),
        _venta_vendedor("P-OUT", "Beto", 1000, id_cliente=2, fecha=datetime(2026, 5, 1)),
    ])
    db.commit()

    out = top_vendedores(db, desde=date(2026, 4, 1), hasta=date(2026, 4, 30))
    assert len(out) == 1
    assert out[0]["vendedor"] == "Ana"


def test_top_vendedores_sin_mercaderia_margen_cero(db):
    """Vendedor con ventas pero NINGUNA línea mercadería con cst → margen=0
    (LEFT JOIN: el vendedor aparece pero su entry de margen es 0). Caso real:
    vendedor que solo vendió descuentos o productos sin cst cargado."""
    _setup(db)
    db.add(_venta_vendedor("P1", "Ana", 100, id_cliente=1))
    # NINGUNA línea mercadería con cst.
    db.add(DetalleVenta(
        id_venta="V-P1", fecha=datetime(2026, 4, 1), linea_num=1,
        producto="Solo Descuento", cantidad=Decimal("1"),
        precio_unitario=Decimal("100"), subtotal=Decimal("100"),
        cst=None, categoria_linea="mercaderia",
    ))
    db.commit()

    out = top_vendedores(db)
    assert len(out) == 1
    assert out[0]["vendedor"] == "Ana"
    assert out[0]["margen"] == 0.0
    assert out[0]["ventas"] == 100.0  # las ventas se cuentan igual


def test_top_vendedores_sin_datos_devuelve_vacio(db):
    """Sin ventas → array vacío, sin error."""
    _setup(db)
    out = top_vendedores(db)
    assert out == []


def test_top_vendedores_tiebreaker_nombre_alfabetico(db):
    """Empate de ventas → orden alfabético ASC. Sin esto, el orden depende
    del optimizador SQLite y flickea entre runs (Ana arriba un día, Beto
    otro). Mismo fix simétrico al de productos_a_perdida."""
    _setup(db)
    # 3 vendedores con ventas exactamente iguales (500).
    db.add_all([
        _venta_vendedor("P1", "Beto", 500, id_cliente=1),
        _venta_vendedor("P2", "Ana", 500, id_cliente=2),
        _venta_vendedor("P3", "Carla", 500, id_cliente=3),
    ])
    db.commit()

    out = top_vendedores(db)
    # Empate → orden alfabético ASC: Ana, Beto, Carla.
    assert [v["vendedor"] for v in out] == ["Ana", "Beto", "Carla"]


def test_top_vendedores_excluye_servicio_con_cst_del_margen(db):
    """Línea categoria_linea='servicio' (NO mercadería) con cst NOT NULL
    NO entra al margen. El filtro es estrictamente categoria='mercaderia',
    no solo 'cst NOT NULL'. Si alguien refactorea quitando el filtro de
    categoria, este test salta."""
    _setup(db)
    db.add(_venta_vendedor("P1", "Ana", 1000, id_cliente=1))
    # Línea de servicio CON cst — debería NO entrar al margen.
    db.add(DetalleVenta(
        id_venta="V-P1", fecha=datetime(2026, 4, 1), linea_num=1,
        producto="Flete", cantidad=Decimal("1"),
        precio_unitario=Decimal("200"), subtotal=Decimal("200"),
        cst=Decimal("50"),  # cst presente, pero categoria != mercaderia
        categoria_linea="servicio",
    ))
    # Para que el vendedor quede con margen 0 sin error, no agregamos
    # mercadería. El listado lo trae con margen=0 (LEFT JOIN behavior).
    db.commit()

    out = top_vendedores(db)
    assert len(out) == 1
    assert out[0]["vendedor"] == "Ana"
    # Servicio NO suma al margen, queda 0.
    assert out[0]["margen"] == 0.0
