"""Tests del helper de formato de monto AR.

La meta de estos tests es congelar la convención AR (puntos como miles,
sin decimales por default) y prevenir regresiones — el frontend espera
exactamente este formato vía `fmtMoney` con Intl.NumberFormat("es-AR")."""
import math
from decimal import Decimal

import pytest

from app.core.formato import fmt_money_ar


def test_formato_basico_miles_con_punto():
    """1234567 → $1.234.567 (formato AR canónico)."""
    assert fmt_money_ar(1234567) == "$1.234.567"


def test_numero_chico_sin_separador():
    assert fmt_money_ar(123) == "$123"


def test_redondea_a_cero_decimales():
    """Importes operativos UI no muestran centavos por convención del proyecto."""
    assert fmt_money_ar(1234.78) == "$1.235"
    assert fmt_money_ar(1234.49) == "$1.234"


def test_decimal_funciona_igual_que_float():
    """Decimal es lo que devuelve el ORM para campos monetarios — debe
    formatear idéntico a float sin perder precisión."""
    assert fmt_money_ar(Decimal("12345.67")) == "$12.346"


def test_negativo_signo_antes_del_simbolo_excel_style():
    """Convención AR Excel-style: signo ANTES del $, no entre $ y dígitos.
    Excel es-AR muestra `-$5.000` por default, alineado con el resto del UI."""
    assert fmt_money_ar(-5000) == "-$5.000"
    assert fmt_money_ar(-1234567) == "-$1.234.567"
    assert fmt_money_ar(Decimal("-99.50")) == "-$100"


@pytest.mark.parametrize("valor", [None, 0, 0.0, Decimal("0")])
def test_default_strict_false_devuelve_vacio_para_none_y_cero(valor):
    """Default UX: una celda con valor 0 o None se muestra vacía para
    no recargar visualmente. Si se quiere `$0` explícito, usar strict=True."""
    assert fmt_money_ar(valor) == ""


@pytest.mark.parametrize("valor,esperado", [
    (0, "$0"),
    (0.0, "$0"),
    (Decimal("0"), "$0"),
])
def test_strict_true_para_cero_genuino_devuelve_dolar_cero(valor, esperado):
    """Cero genuino con strict → "$0" (informativo: 'medimos, da cero')."""
    assert fmt_money_ar(valor, strict=True) == esperado


def test_strict_true_para_none_devuelve_dash_no_dolar_cero():
    """None con strict → "-" (semántica: 'valor desconocido', distinto de
    cero genuino). Útil en tablas KPI donde 'sin dato' ≠ 'cero medido'."""
    assert fmt_money_ar(None, strict=True) == "-"


def test_millones_y_billones():
    assert fmt_money_ar(1_000_000) == "$1.000.000"
    assert fmt_money_ar(1_500_000_000) == "$1.500.000.000"


@pytest.mark.parametrize("valor", [
    float("inf"),
    float("-inf"),
    float("nan"),
])
def test_inf_y_nan_no_surfacean_en_default(valor):
    """Valores no finitos vienen de bugs upstream (división por cero, agg
    rota). NO mostrar "$inf"/"$nan" en una alerta — devolvemos vacío y
    que se diagnostique por logs."""
    assert fmt_money_ar(valor) == ""


@pytest.mark.parametrize("valor", [
    float("inf"),
    float("-inf"),
    float("nan"),
])
def test_inf_y_nan_devuelven_dash_en_strict(valor):
    """Mismo principio en modo strict: placeholder neutral, no leak del bug."""
    assert fmt_money_ar(valor, strict=True) == "-"


def test_decimal_nan_se_normaliza_via_float():
    """Decimal('NaN') al convertir a float da nan — debe entrar en el path
    de no-finito, no propagar como string."""
    assert fmt_money_ar(Decimal("NaN")) == ""
