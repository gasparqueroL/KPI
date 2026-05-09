"""Test de la lógica de período anterior — replica el cálculo del frontend.

Aunque la función vive en JS, replico el contrato para tener un check
contra regresiones cuando se toque el cálculo en el backend o se reuse.
"""

from datetime import date, timedelta


def periodo_anterior(desde: date, hasta: date) -> tuple[date, date]:
    """Período inmediatamente anterior de igual largo."""
    dias = (hasta - desde).days + 1
    hasta_prev = desde - timedelta(days=1)
    desde_prev = hasta_prev - timedelta(days=dias - 1)
    return desde_prev, hasta_prev


def test_un_mes_completo():
    # Abril tiene 30 días: el período anterior de igual largo termina el 31/3
    d, h = periodo_anterior(date(2026, 4, 1), date(2026, 4, 30))
    assert d == date(2026, 3, 2)
    assert h == date(2026, 3, 31)


def test_un_solo_dia():
    d, h = periodo_anterior(date(2026, 4, 15), date(2026, 4, 15))
    assert d == date(2026, 4, 14)
    assert h == date(2026, 4, 14)


def test_cruce_de_anio():
    # Enero tiene 31 días: anterior empieza el 1/12 (31 días que terminan el 31/12)
    d, h = periodo_anterior(date(2026, 1, 1), date(2026, 1, 31))
    assert d == date(2025, 12, 1)
    assert h == date(2025, 12, 31)


def test_largo_se_preserva():
    desde, hasta = date(2026, 3, 1), date(2026, 3, 15)
    dias_orig = (hasta - desde).days + 1
    d, h = periodo_anterior(desde, hasta)
    dias_prev = (h - d).days + 1
    assert dias_orig == dias_prev == 15
