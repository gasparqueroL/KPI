"""Tests de la normalización de nombres de Caja."""

from app.models.caja import Caja


def test_normaliza_a_lowercase():
    assert Caja.normalizar("EMA TACA") == "emataca"


def test_colapsa_espacios():
    assert Caja.normalizar("  EMA   TACA  ") == "emataca"


def test_variantes_son_iguales():
    a = Caja.normalizar("EMA TACA")
    b = Caja.normalizar("ematac" + "a")
    c = Caja.normalizar("EmaTaca")
    d = Caja.normalizar(" EMA TACA ")
    assert a == b == c == d


def test_vacio():
    assert Caja.normalizar("") == ""
    assert Caja.normalizar(None) == ""


def test_punto_se_preserva():
    # PAOLO.FC tiene que mantener el punto que distingue cajas FC
    assert Caja.normalizar("PAOLO.FC") == "paolo.fc"
