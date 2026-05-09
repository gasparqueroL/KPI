"""Reconcilia saldos teóricos (provistos por la dueña) vs computado del sistema.

Saldo computado por caja = sum(entradas) - sum(salidas) sobre todos los
movimientos. La dueña pasó saldos teóricos al 2026-05-08.

Output: tabla ordenada por |diff| descendente.
"""

from decimal import Decimal
from sqlalchemy import func

from app.db import SessionLocal
from app.models.caja import Caja
from app.models.movimiento_caja import MovimientoCaja
from app.models.venta import Venta


# Saldos teóricos al 2026-05-08 (provistos por la dueña).
# Display name → saldo Decimal.
TEORICOS_RAW = """
GERMAN EFECTIVO    $0,00
GERMAN MP    $0,00
GERMAN DEL SOL    $0,00
GERMAN GALICIA    $0,00
GERMAN PREX    $0,00
GERMAN UALA    $0,00
GERMAN BRUBANK    $0,00
GERMAN PERSONAL PAY    $0,00
GERMAN LEMON    $0,00
GERMAN NARANJA X    $0,00
GERMAN.ASTRO    $0,00
JOSE TARJETAS    $0,00
KATYA.FC    $0,00
YOLI.SIMINI.FC    $0,00
FEDE.G    $0,00
GASPAR EFECTIVO    $0,00
GASPAR YPF    $0,00
GASPAR CLAROPAY    $0,00
GASPAR BULLPAY    $0,00
GASPAR MERCADOPAGO    $0,00
GASPAR B.CORDOBA    $0,00
GASPAR CAJA GRANDE    $0,00
GASPAR BRUBANK    $1.619.156,21
GASPAR UALA    $341.363,02
GASPAR LEMON    $1.103.040,79
GASPAR P.PAY    $407.197,20
GASPAR NARANJAX    $2.762.404,51
GASPAR PREX    $1.326.646,68
GASPAR CENCOSUD    $958.767,75
GASPAR ASTROPAY    -$16.385,30
NATALIA PREX    $2.530.010,86
NATALIA NARANJA X    $565.483,01
NATALIA UALA    $1.620.466,00
NATALIA LEMON    $2.480.491,79
NATALIA PERSONAL PAY    $2.653.132,85
NATALIA ASTROPAY    $2.435.800,37
NICOLAS EFECTIVO    $3.050.000,00
NICOLAS UALA    $0,00
NICOLAS BRUBANK    $0,00
NICOLAS DEL SOL    $0,00
NICOLAS CREDICOOP    $0,00
NICOLAS PREX    $0,06
NICOLAS MERCADOPAGO    $0,00
NICOLAS PP    $0,00
NICOLAS LEMON    $1.624.492,09
NICO GALICIA    $0,00
NICO SANTANDER    $1.124.962,16
DIEGO.NICO    $0,00
NICO.A    $159.353,00
NICO.AN    $0,00
NICOLAS ASTRO    $0,00
JONA BRUBANK    $2.400.315,46
JONA MERCADOPAGO    $8.236.814,61
CAJA LOCAL    $670.873,40
FONDO GALPON    $2.240.237,95
KATYA.ETIQ    $7.712.690,10
NGG LABORATORIOS    $53.860.410,57
COUPER 1    $0,00
ED SERVICIOS    $0,00
CATALINA    $15.953.538,50
SERQUIM    $0,00
COUPER 2    $0,00
CLORO    $236.625,38
PROINSAL    $0,00
CITRATUS    -$531.472,81
MV.EMBALAJE    $0,00
TODODROGA    $0,00
SOLUCIONES QUIMICAS    $0,00
SUDAMERICANA    $32.989.142,21
ADECOLAB    $0,00
SUPOL    $0,00
FILM    $0,00
MULTIQUIMICA    $8.410.032,91
ACG    $0,00
RACK    $69.307,65
BIGQUIM    $0,00
GRASSEN    $7.050.407,45
COMPAÑIA DEL SUR    $0,00
CARI LEMON    $2.210.685,52
CARI PREX    $2.006.671,06
CARI PERSONAL    $2.168.006,12
CARI CENCOSUD    $1.872.377,24
CARI ASTROPAY    $2.227.745,07
LUCHO NARANJA X    $2.042.296,77
LUCHO PREX    $1.946.034,98
LUCHO BRUBANK    $1.941.513,64
LUCHO PERSONAL    $2.572.204,02
LUCHO UALA    $1.870.768,29
EMA NARANJA X    $817.712,09
EMA PREX    $3.160.216,59
EMA PERSONAL PAY    $2.786.000,61
EMA UALA    $2.016.845,80
EMA BRUBANK    $2.138.407,25
EMA TACA    $2.678.459,23
RUATTA    $2.518.278,41
FACUNDO.IMP    $0,00
BRICCHI    $0,00
ASTORGA    $0,00
CAJA GRANDE QUIMICA    -$52.804.788,68
RESERVAS DOLARES    $0,00
QUIMICA.K    $0,00
QUIMICA.M    $0,00
QUIMICA.R    $0,00
QUIMICA.S    $0,00
QUIMICA.SL    $0,00
QUIMICA.Q    $0,00
VESPA.PQ    $0,00
YASH.SA    $0,00
TEXTIL.Q    $0,00
SUDA.Q    $0,00
QUIMICA.A    $0,00
QUIMICA.SB    $0,00
QUIMICA.P    $924.419,62
MICA.FC    $178.085,79
SARA.FC    $226.402,17
PAULINA.FC    -$104.017,85
RHO.FC    $110.230,38
FLORENCIA.FC    -$6.314,62
PAOLO.FC    -$40.778,53
VIOLETA.FC    -$207.701,77
LUCHO.FC    -$30.268,94
ENZO.FC    -$100.514,33
GASTON.FC    -$1.069.000,00
GONZALO.FC    -$9.038,62
ANGEL.FC    -$50.137,25
ESTEBAN.FC    -$120.057,83
MAURI.FC    -$201.253,78
MAXI.FC    -$65.717,37
ELIAS.FC    -$114.282,67
EMA.FC    $116.021,09
CRISTIAN.FC    -$108.439,31
JONA.FC    -$2.438.861,67
EZEQUIEL.CC    $260.908,00
NADIA.CC    $87.034,37
ANDRADE.CC    $628.828,20
CORIA.CC    $20.036,72
MARIA.CC    $185.726,75
PABLO.FC    $0,00
ALAN.FC    $0,00
MATIAS.FC    $30.500,00
PABLO.FCN    $23.089,55
MAXI.FCN    $147.112,25
RODRI.FC    $0,00
ALDANA.FC    $100.376,05
EMANUEL.FC    $0,00
RODOLFO.FC    $0,00
"""


def _parse_monto_ar(s: str) -> Decimal:
    """Parsea '$1.234.567,89' o '-$1.234,56' a Decimal."""
    s = s.strip().replace("$", "").replace(".", "").replace(",", ".")
    return Decimal(s)


def parse_teoricos() -> dict[str, Decimal]:
    """Devuelve {nombre_normalizado: saldo}."""
    out = {}
    for linea in TEORICOS_RAW.strip().splitlines():
        if not linea.strip():
            continue
        # split por tabulación o múltiples espacios
        partes = [p for p in linea.split("    ") if p.strip()]
        if len(partes) != 2:
            # fallback: split por última secuencia de espacios
            partes = linea.rsplit(None, 1)
            # esto separa mal nombres con espacios — uso tabulación
            print(f"WARN no parseado: {linea!r}")
            continue
        nombre = partes[0].strip()
        saldo = _parse_monto_ar(partes[1])
        out[Caja.normalizar(nombre)] = (nombre, saldo)
    return out


def computar_saldos_sistema(db) -> dict[str, dict]:
    """Misma fórmula que app.kpis.caja.saldos_por_caja:
    saldo = ventas_caja1 + ventas_caja2 + ingresos_mov - egresos_mov.
    Devuelve por caja: {ventas, ingresos_mov, egresos_mov, saldo}.
    """
    ventas_c1 = dict(
        db.query(Venta.caja1, func.coalesce(func.sum(Venta.monto_pago1), 0))
        .filter(Venta.caja1.isnot(None))
        .group_by(Venta.caja1)
        .all()
    )
    ventas_c2 = dict(
        db.query(Venta.caja2, func.coalesce(func.sum(Venta.monto_pago2), 0))
        .filter(Venta.caja2.isnot(None))
        .group_by(Venta.caja2)
        .all()
    )
    entradas = dict(
        db.query(MovimientoCaja.caja_destino, func.sum(MovimientoCaja.monto))
        .filter(MovimientoCaja.caja_destino.isnot(None))
        .group_by(MovimientoCaja.caja_destino)
        .all()
    )
    salidas = dict(
        db.query(MovimientoCaja.caja_origen, func.sum(MovimientoCaja.monto))
        .filter(MovimientoCaja.caja_origen.isnot(None))
        .group_by(MovimientoCaja.caja_origen)
        .all()
    )
    todas = set(ventas_c1) | set(ventas_c2) | set(entradas) | set(salidas)
    out = {}
    for c in todas:
        v = Decimal(ventas_c1.get(c, 0)) + Decimal(ventas_c2.get(c, 0))
        ing = Decimal(entradas.get(c, 0))
        egr = Decimal(salidas.get(c, 0))
        out[c] = {
            "ventas": v,
            "ingresos_mov": ing,
            "egresos_mov": egr,
            "saldo": v + ing - egr,
        }
    return out


def main():
    db = SessionLocal()
    try:
        teoricos = parse_teoricos()
        sistema = computar_saldos_sistema(db)
        cajas_db = {c.nombre_normalizado: c.nombre_display
                    for c in db.query(Caja).all()}

        # Filas: (nombre_display, teorico, sistema, diff, status)
        filas = []
        nombres_unidos = set(teoricos) | set(sistema) | set(cajas_db)
        for norm in nombres_unidos:
            display_t = teoricos.get(norm, (None, None))[0]
            saldo_t = teoricos.get(norm, (None, Decimal(0)))[1]
            datos_s = sistema.get(norm, {"ventas": Decimal(0), "ingresos_mov": Decimal(0),
                                          "egresos_mov": Decimal(0), "saldo": Decimal(0)})
            saldo_s = datos_s["saldo"]
            display_db = cajas_db.get(norm)
            display = display_t or display_db or norm
            existe_db = norm in cajas_db
            tiene_teorico = norm in teoricos
            diff = saldo_s - saldo_t if tiene_teorico else None
            filas.append({
                "display": display,
                "norm": norm,
                "teorico": saldo_t,
                "sistema": saldo_s,
                "ventas": datos_s["ventas"],
                "ingresos_mov": datos_s["ingresos_mov"],
                "egresos_mov": datos_s["egresos_mov"],
                "diff": diff,
                "existe_db": existe_db,
                "tiene_teorico": tiene_teorico,
            })

        # 1. Las que NO existen en DB pero tienen teórico
        no_db = [f for f in filas if f["tiene_teorico"] and not f["existe_db"]]
        # 2. Las que sí matchean
        matched = [f for f in filas if f["tiene_teorico"] and f["existe_db"]]
        matched.sort(key=lambda f: abs(f["diff"]), reverse=True)
        # 3. Cajas en DB sin teórico
        sin_teorico = [f for f in filas if not f["tiene_teorico"] and f["existe_db"]]

        print("="*90)
        print(f"{'CAJA':<32} {'TEORICO':>15} {'SISTEMA':>15} {'DIFF':>15}")
        print("="*90)

        for f in matched:
            t = f["teorico"]
            s = f["sistema"]
            d = f["diff"]
            mark = " " if abs(d) < 1 else ("!" if abs(d) > 100000 else ".")
            print(f"{mark} {f['display']:<30} {t:>15,.2f} {s:>15,.2f} {d:>15,.2f}")

        if no_db:
            print("\n" + "="*90)
            print(f"CAJAS EN TEÓRICO QUE NO EXISTEN EN DB ({len(no_db)}):")
            print("="*90)
            for f in no_db:
                print(f"  {f['display']:<30} (norm={f['norm']!r}) teórico={f['teorico']:,.2f}")

        if sin_teorico:
            con_movs = [f for f in sin_teorico if f["sistema"] != 0]
            sin_movs = [f for f in sin_teorico if f["sistema"] == 0]
            if con_movs:
                print("\n" + "="*90)
                print(f"CAJAS EN DB SIN TEORICO Y CON MOVIMIENTOS ({len(con_movs)}):")
                print("="*90)
                con_movs.sort(key=lambda f: abs(f["sistema"]), reverse=True)
                for f in con_movs:
                    print(f"  {f['display']:<30} sistema={f['sistema']:>15,.2f}")
            if sin_movs:
                print(f"\n(+ {len(sin_movs)} cajas en DB sin teorico ni movimientos -- ignoradas)")

        # Totales
        total_t = sum(f["teorico"] for f in filas if f["tiene_teorico"])
        total_s_matched = sum(f["sistema"] for f in matched)
        total_s_all = sum(d["saldo"] for d in sistema.values())
        total_ventas = sum(d["ventas"] for d in sistema.values())
        total_ing_mov = sum(d["ingresos_mov"] for d in sistema.values())
        total_egr_mov = sum(d["egresos_mov"] for d in sistema.values())
        print("\n" + "="*90)
        print("TOTALES")
        print("="*90)
        print(f"Suma teoricos:                     {total_t:>20,.2f}")
        print(f"Suma sistema (solo matched):       {total_s_matched:>20,.2f}")
        print(f"Suma sistema (TODAS las cajas):    {total_s_all:>20,.2f}")
        print(f"Diff sistema-teorico (matched):    {total_s_matched - total_t:>20,.2f}")
        print()
        print("Desglose flujos (todas las cajas):")
        print(f"  + Ventas (caja1+caja2):          {total_ventas:>20,.2f}")
        print(f"  + Ingresos movimientos:          {total_ing_mov:>20,.2f}")
        print(f"  - Egresos movimientos:           {total_egr_mov:>20,.2f}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
