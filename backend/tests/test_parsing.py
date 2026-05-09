"""Tests de los parsers tolerantes (formato es-AR)."""

from datetime import date, datetime
from decimal import Decimal

from app.importers.parsing import (
    normalize_str,
    parse_bool,
    parse_date_es,
    parse_datetime_es,
    parse_monto,
)


class TestParseMonto:
    def test_formato_es_completo(self):
        assert parse_monto("$156.249,80") == Decimal("156249.80")

    def test_solo_signo_y_decimal(self):
        assert parse_monto("$636") == Decimal("636")

    def test_solo_decimal_coma(self):
        assert parse_monto("14708,77648") == Decimal("14708.77648")

    def test_punto_como_miles(self):
        assert parse_monto("$31.782") == Decimal("31782")

    def test_string_vacio(self):
        assert parse_monto("") is None
        assert parse_monto(None) is None
        assert parse_monto("nan") is None

    def test_valor_invalido(self):
        assert parse_monto("abc") is None

    def test_negativo(self):
        assert parse_monto("$-5.300,00") == Decimal("-5300.00")

    def test_punto_decimal_simple(self):
        # "1.5" debe ser 1.5, no 15
        assert parse_monto("1.5") == Decimal("1.5")

    def test_punto_decimal_centavos(self):
        # "0.50" debe ser 0.50, no 50
        assert parse_monto("0.50") == Decimal("0.50")

    def test_punto_miles_sin_decimales(self):
        # "$31.782" en es-AR es 31782, sin coma -> miles
        assert parse_monto("$31.782") == Decimal("31782")

    def test_punto_decimal_dos_digitos(self):
        # "10.50" es 10.50 (decimal), NO 1050 (miles)
        assert parse_monto("10.50") == Decimal("10.50")

    def test_negativo_con_punto_sin_coma(self):
        # "-31.782" sin coma debe interpretarse como miles negativos
        assert parse_monto("-31.782") == Decimal("-31782")

    def test_millones_formato_es(self):
        # Múltiples puntos = todos miles (es-AR)
        assert parse_monto("$1.234.567,89") == Decimal("1234567.89")

    def test_cero_punto_centena(self):
        # "0.500" debe ser decimal (parte entera = 0)
        assert parse_monto("0.500") == Decimal("0.500")

    def test_en_us_con_miles_y_decimal(self):
        # "1,234.56" en en-US: coma = miles, punto = decimal
        assert parse_monto("1,234.56") == Decimal("1234.56")

    def test_en_us_solo_miles(self):
        # "1,234" — heurística simétrica: 3 dígitos derecha y entero >= 1 → miles
        assert parse_monto("1,234") == Decimal("1234")

    def test_en_us_millones(self):
        # "1,234,567.89" → en-US claro
        assert parse_monto("1,234,567.89") == Decimal("1234567.89")

    def test_coma_decimal_corta(self):
        # "1,5" — un dígito a la derecha → decimal (no miles)
        assert parse_monto("1,5") == Decimal("1.5")

    def test_cero_coma_centena(self):
        # "0,500" — parte entera = 0 → decimal (no miles)
        assert parse_monto("0,500") == Decimal("0.500")

    # ===== Tests de regresión: bug de margen bruto -$44M =====
    # Source CSV exportaba `cst` con coma decimal sin separador de miles.
    # Valores como "1003057,923" (= $1.003.057,923 unit cost) eran
    # interpretados como AR-thousands literal → $1.003.057.923 (mil
    # millones), 1000× más alto. Cuando hay solo coma/punto y la parte
    # izquierda tiene 4+ dígitos, asumimos decimal (AR estricto SIEMPRE
    # incluye separador de miles cuando aplica).

    def test_coma_decimal_parte_izq_4_digitos(self):
        # "1234,567" — 4 dígitos izq + 3 derecha → decimal, no thousands.
        # Antes del fix: 1234567. Ahora: 1234.567.
        assert parse_monto("1234,567") == Decimal("1234.567")

    def test_coma_decimal_parte_izq_5_digitos(self):
        # "10234,567" — 5 dígitos izq → decimal.
        assert parse_monto("10234,567") == Decimal("10234.567")

    def test_coma_decimal_parte_izq_7_digitos_caso_real(self):
        # Caso real del bug: cst exportado como "1003057,923" debe ser
        # $1.003.057,923 — antes daba $1.003.057.923 (mil millones).
        assert parse_monto("1003057,923") == Decimal("1003057.923")

    def test_punto_decimal_parte_izq_4_digitos(self):
        # Simétrico: "1234.567" con 4 dígitos izq → decimal.
        # Antes del fix: 1234567 (US thousands). Ahora: 1234.567.
        assert parse_monto("1234.567") == Decimal("1234.567")

    def test_coma_thousands_3_digitos_izq_se_preserva(self):
        # Sanity: la regla nueva NO debe romper AR thousands con parte
        # izq de 1-3 dígitos. "123,456" sigue siendo 123456.
        assert parse_monto("123,456") == Decimal("123456")
        assert parse_monto("12,345") == Decimal("12345")
        assert parse_monto("1,234") == Decimal("1234")

    def test_punto_thousands_3_digitos_izq_se_preserva(self):
        # Sanity simétrico: "123.456" AR thousands sigue siendo 123456.
        assert parse_monto("123.456") == Decimal("123456")
        assert parse_monto("12.345") == Decimal("12345")
        assert parse_monto("$1.047") == Decimal("1047")

    def test_ar_thousands_4_digitos_izq_no_es_expresable_sin_separador(self):
        # Decisión deliberada: "1234,567" sin punto de miles se interpreta
        # como decimal (1234.567), NO como AR thousands ($1.234,567).
        # Razón: AR estricto SIEMPRE incluye separador de miles cuando
        # aplica ("$1.234,567" o "$1.234.567"). Si alguien quiere expresar
        # "$1.234,567" debe escribirlo con el punto de miles. Sin punto, la
        # heurística asume decimal — el caso real de cst con precisión
        # variable que llevó al fix.
        # Con punto + coma: parser AR clásico funciona OK.
        assert parse_monto("$1.234,567") == Decimal("1234.567")
        # Sin punto de miles, parte izquierda 4+ dígitos → decimal.
        assert parse_monto("$1234,567") == Decimal("1234.567")
        # Coincidencia agradable: ambos formatos dan el mismo número, así
        # que el caller que envíe data ambigua igual obtiene el mismo
        # resultado interpretado consistentemente.


class TestParseDatetime:
    def test_formato_completo(self):
        assert parse_datetime_es("30/4/2026 20:27:17") == datetime(2026, 4, 30, 20, 27, 17)

    def test_solo_fecha(self):
        assert parse_datetime_es("01/05/2026") == datetime(2026, 5, 1)

    def test_iso(self):
        assert parse_datetime_es("2026-05-01") == datetime(2026, 5, 1)

    def test_invalido(self):
        assert parse_datetime_es("no es fecha") is None
        assert parse_datetime_es("") is None
        assert parse_datetime_es(None) is None


class TestParseDate:
    def test_devuelve_date(self):
        assert parse_date_es("01/05/2026") == date(2026, 5, 1)


class TestParseBool:
    def test_true(self):
        assert parse_bool("TRUE") is True
        assert parse_bool("true") is True
        assert parse_bool("1") is True
        assert parse_bool("SI") is True

    def test_false(self):
        assert parse_bool("FALSE") is False
        assert parse_bool("") is False
        assert parse_bool(None) is False
        assert parse_bool("0") is False


class TestNormalizeStr:
    def test_trim_y_colapsa_espacios(self):
        assert normalize_str("  EMA   TACA  ") == "EMA TACA"

    def test_vacio(self):
        assert normalize_str("") == ""
        assert normalize_str(None) == ""
        assert normalize_str("nan") == ""
