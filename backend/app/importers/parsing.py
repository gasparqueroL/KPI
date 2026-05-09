"""Parsers tolerantes para los formatos del export del sistema."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation


def parse_monto(v) -> Decimal | None:
    """Parsea montos tolerando es-AR ('$156.249,80') y en-US ('1,234.56').

    Cuando aparecen ambos separadores, el último presente es el decimal
    (regla universal). Si solo hay coma, se aplica la misma heurística
    de "3 dígitos = miles" que se usa para el punto solitario.
    """
    if v is None:
        return None
    s = str(v).strip().replace("$", "").replace(" ", "").replace("\xa0", "")
    if s == "" or s.lower() == "nan":
        return None

    has_comma = "," in s
    has_dot = "." in s

    if has_comma and has_dot:
        # El último separador es el decimal. Discrimina es-AR vs en-US
        # por posición real, no por suposición de formato.
        if s.rfind(",") > s.rfind("."):
            # es-AR: punto = miles, coma = decimal
            s = s.replace(".", "").replace(",", ".")
        else:
            # en-US: coma = miles, punto = decimal
            s = s.replace(",", "")
    elif has_comma:
        # Misma heurística que con punto solitario:
        # un solo grupo de 3 dígitos a la derecha y parte entera >= 1
        # se trata como miles ("1,234" -> 1234). Caso contrario decimal.
        #
        # EXCEPCIÓN: si la parte izquierda tiene 4+ dígitos, tratar como
        # decimal SIEMPRE — porque AR estricto formatearía "10.234,xx"
        # con punto de miles. Sin punto de miles, "10234,xxx" implica que
        # la fuente exportó el entero sin formatear y la parte después
        # de la coma es decimal, no thousands. Caso real: source export
        # de cst con precisión variable: "1003057,923" = $1.003.057,923
        # NO es $1.003.057.923 (mil millones, absurdo para cost line).
        partes = s.split(",")
        if len(partes) > 2:
            # múltiples comas: miles ("1,234,567")
            s = s.replace(",", "")
        elif len(partes[-1]) == 3 and partes[0]:
            try:
                ent_abs = len(partes[0].lstrip("-+"))
                if ent_abs >= 4:
                    # Parte izquierda >= 4 dígitos → decimal (ver comentario).
                    s = s.replace(",", ".")
                elif abs(int(partes[0])) >= 1:
                    s = s.replace(",", "")
                else:
                    s = s.replace(",", ".")
            except ValueError:
                s = s.replace(",", ".")
        else:
            s = s.replace(",", ".")
    elif has_dot:
        # Determinar si el punto es decimal o miles.
        # Misma excepción de "parte izquierda 4+ dígitos → decimal" para
        # el caso simétrico (formato US-style sin thousand sep).
        partes = s.split(".")
        if len(partes) > 2:
            # múltiples puntos: típicamente miles (ej. "1.234.567")
            s = s.replace(".", "")
        elif len(partes[-1]) == 3 and partes[0]:
            try:
                ent_abs = len(partes[0].lstrip("-+"))
                if ent_abs >= 4:
                    # decimal por la regla de arriba — no tocar.
                    pass
                elif abs(int(partes[0])) >= 1:
                    s = s.replace(".", "")
            except ValueError:
                pass
        # else: punto = decimal, no hacer nada

    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_datetime_es(v) -> datetime | None:
    """Acepta '30/4/2026 20:27:17', '01/05/2026', etc."""
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return None
    formatos = [
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    for f in formatos:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    return None


def parse_date_es(v) -> date | None:
    dt = parse_datetime_es(v)
    return dt.date() if dt else None


def parse_bool(v) -> bool:
    if v is None:
        return False
    s = str(v).strip().upper()
    return s in ("TRUE", "VERDADERO", "1", "SI", "SÍ", "YES", "T", "Y")


def normalize_str(v) -> str:
    """Trim + colapsa whitespace consecutivo. Devuelve '' para None/NaN."""
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() == "nan":
        return ""
    return " ".join(s.split())
