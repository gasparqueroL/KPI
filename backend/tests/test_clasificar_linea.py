"""Tests de la heurística que clasifica detalle_ventas en mercaderia/envio/bonificacion."""

from decimal import Decimal

from app.importers.detalle_ventas import clasificar_linea


def test_envio_a_domicilio_es_envio():
    assert clasificar_linea("ENVIO A DOMICILIO", Decimal("22000")) == "envio"


def test_envio_gratis_es_envio_aunque_negativo():
    # Sin la regla "ENVIO en nombre", caería como bonificacion por precio < 0
    assert clasificar_linea("ENVIO GRATIS", Decimal("-15000")) == "envio"


def test_bonificacion_explicita_es_bonificacion():
    assert clasificar_linea("BONIFICACION DE JARRA Y EMBUDO", Decimal("-5300")) == "bonificacion"


def test_precio_negativo_sin_etiqueta_es_bonificacion():
    assert clasificar_linea("PRODUCTO RANDOM", Decimal("-100")) == "bonificacion"


def test_producto_normal_es_mercaderia():
    assert clasificar_linea("JABON LIQUIDO SKIP CLASICO", Decimal("636")) == "mercaderia"


def test_acepta_acentos():
    assert clasificar_linea("ENVÍO LOGISTICO", Decimal("100")) == "envio"
    assert clasificar_linea("BONIFICACIÓN ESPECIAL", Decimal("-50")) == "bonificacion"


def test_precio_none_es_mercaderia():
    assert clasificar_linea("PRODUCTO X", None) == "mercaderia"
