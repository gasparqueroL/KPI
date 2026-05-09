"""Migra cajas problematicas + carga saldo de apertura al 2024-12-31.

Pasos:
1. Migra '$623,62' (movimiento con destino corrupto): destino -> NULL.
2. Merge 'JONA MERCADOOAGO' -> 'JONA MERCADOPAGO'.
3. Merge 'FONDO GALPON.OLD' -> 'FONDO GALPON'.
4. Crea categoria 'Ajuste Apertura' con excluir_flujo=True.
5. Para cada caja con |teorico - saldo_actual| >= UMBRAL, crea
   movimiento al 2024-12-31 (caja_destino si diff>0, caja_origen si diff<0).
"""
from datetime import date
from decimal import Decimal
import hashlib

from sqlalchemy import func

from app.db import SessionLocal
from app.models.caja import Caja
from app.models.categoria_caja import CategoriaCaja
from app.models.movimiento_caja import MovimientoCaja
from app.models.venta import Venta
from scripts.reconciliar_cajas import parse_teoricos, computar_saldos_sistema

UMBRAL = Decimal("1.00")  # Ignora diffs por debajo de $1 (redondeo)
FECHA_APERTURA = date(2024, 12, 31)
TIPO_OPERACION = "Ajuste Apertura"


def _hash(*parts) -> str:
    s = "|".join(str(p) for p in parts)
    return hashlib.sha256(s.encode()).hexdigest()[:32]


def migrar_problemas(db) -> dict:
    """Migra las 3 cajas problematicas. Devuelve resumen."""
    resumen = {}

    # 1. $623,62 — mov con destino corrupto
    norm_corrupto = Caja.normalizar("$623,62")
    movs_destino = db.query(MovimientoCaja).filter(
        MovimientoCaja.caja_destino == norm_corrupto
    ).all()
    for m in movs_destino:
        m.caja_destino = None
    n_dollarcaja = len(movs_destino)
    caja = db.query(Caja).filter(Caja.nombre_normalizado == norm_corrupto).first()
    if caja:
        db.delete(caja)
    resumen["$623,62"] = {"movs_destino_nulleados": n_dollarcaja, "caja_borrada": bool(caja)}

    # 2. JONA MERCADOOAGO -> JONA MERCADOPAGO
    src = Caja.normalizar("JONA MERCADOOAGO")
    dst = Caja.normalizar("JONA MERCADOPAGO")
    n_org = db.query(MovimientoCaja).filter(MovimientoCaja.caja_origen == src).update(
        {MovimientoCaja.caja_origen: dst}, synchronize_session=False
    )
    n_dst = db.query(MovimientoCaja).filter(MovimientoCaja.caja_destino == src).update(
        {MovimientoCaja.caja_destino: dst}, synchronize_session=False
    )
    n_v1 = db.query(Venta).filter(Venta.caja1 == src).update(
        {Venta.caja1: dst}, synchronize_session=False
    )
    n_v2 = db.query(Venta).filter(Venta.caja2 == src).update(
        {Venta.caja2: dst}, synchronize_session=False
    )
    caja_typo = db.query(Caja).filter(Caja.nombre_normalizado == src).first()
    if caja_typo:
        db.delete(caja_typo)
    resumen["JONA MERCADOOAGO->JONA MERCADOPAGO"] = {
        "movs_origen": n_org, "movs_destino": n_dst,
        "ventas_c1": n_v1, "ventas_c2": n_v2, "caja_borrada": bool(caja_typo),
    }

    # 3. FONDO GALPON.OLD -> FONDO GALPON
    src = Caja.normalizar("FONDO GALPON.OLD")
    dst = Caja.normalizar("FONDO GALPON")
    n_org = db.query(MovimientoCaja).filter(MovimientoCaja.caja_origen == src).update(
        {MovimientoCaja.caja_origen: dst}, synchronize_session=False
    )
    n_dst = db.query(MovimientoCaja).filter(MovimientoCaja.caja_destino == src).update(
        {MovimientoCaja.caja_destino: dst}, synchronize_session=False
    )
    n_v1 = db.query(Venta).filter(Venta.caja1 == src).update(
        {Venta.caja1: dst}, synchronize_session=False
    )
    n_v2 = db.query(Venta).filter(Venta.caja2 == src).update(
        {Venta.caja2: dst}, synchronize_session=False
    )
    caja_old = db.query(Caja).filter(Caja.nombre_normalizado == src).first()
    if caja_old:
        db.delete(caja_old)
    resumen["FONDO GALPON.OLD->FONDO GALPON"] = {
        "movs_origen": n_org, "movs_destino": n_dst,
        "ventas_c1": n_v1, "ventas_c2": n_v2, "caja_borrada": bool(caja_old),
    }

    db.flush()
    return resumen


def asegurar_categoria_apertura(db):
    cat = db.query(CategoriaCaja).filter(
        CategoriaCaja.tipo_operacion == TIPO_OPERACION
    ).first()
    if not cat:
        cat = CategoriaCaja(
            tipo_operacion=TIPO_OPERACION,
            familia="Sistema",
            excluir_flujo=True,
            es_transferencia=False,
            es_retiro=False,
            es_ingreso_operativo=False,
            descripcion="Saldo inicial de caja al 2024-12-31. Excluido de KPIs de flujo.",
        )
        db.add(cat)
        db.flush()
        return True
    return False


def _detectar_tipo(display: str) -> str:
    """.FC / .FCN -> fc_empleado, resto -> operativa."""
    up = display.upper()
    if up.endswith(".FC") or up.endswith(".FCN"):
        return "fc_empleado"
    return "operativa"


def crear_aperturas(db) -> dict:
    """Crea movimientos de apertura para cerrar el gap teorico vs sistema.
    Si la caja no existe en DB y el teorico es != 0, la crea con tipo
    detectado por sufijo (.FC/.FCN -> fc_empleado, resto -> operativa)."""
    teoricos_full = parse_teoricos()
    sistema = computar_saldos_sistema(db)

    creados = 0
    saltados_centavos = 0
    cajas_creadas = []
    detalles = []

    for norm, (display, saldo_teorico) in teoricos_full.items():
        saldo_sistema = sistema.get(norm, {"saldo": Decimal(0)})["saldo"]
        delta = saldo_teorico - saldo_sistema
        if abs(delta) < UMBRAL:
            saltados_centavos += 1
            continue

        # Verificar que la caja existe; si no, crearla
        caja_existe = db.query(Caja).filter(Caja.nombre_normalizado == norm).first()
        if not caja_existe:
            tipo = _detectar_tipo(display)
            nueva = Caja(
                nombre_normalizado=norm,
                nombre_display=display,
                tipo=tipo,
                activa=True,
            )
            db.add(nueva)
            db.flush()
            cajas_creadas.append((display, norm, tipo))

        # delta positivo -> ingreso de apertura (destino = caja)
        # delta negativo -> egreso de apertura (origen = caja)
        if delta > 0:
            origen = None
            destino = norm
            monto = delta
        else:
            origen = norm
            destino = None
            monto = -delta  # positivo

        h = _hash("apertura", norm, FECHA_APERTURA.isoformat(), str(monto))
        mov = MovimientoCaja(
            fecha=FECHA_APERTURA,
            tipo_operacion=TIPO_OPERACION,
            detalle=f"Saldo de apertura ({display})",
            monto=monto,
            caja_origen=origen,
            caja_destino=destino,
            hash_dedupe=h,
        )
        db.add(mov)
        creados += 1
        detalles.append((display, str(saldo_teorico), str(saldo_sistema), str(delta)))

    db.flush()
    return {
        "creados": creados,
        "saltados_centavos": saltados_centavos,
        "cajas_creadas": cajas_creadas,
        "detalles": detalles,
    }


def main():
    db = SessionLocal()
    try:
        print("="*70)
        print("PASO 1: Migrar cajas problematicas")
        print("="*70)
        resumen_migracion = migrar_problemas(db)
        for k, v in resumen_migracion.items():
            print(f"  {k}: {v}")

        print("\n" + "="*70)
        print("PASO 2: Asegurar categoria 'Ajuste Apertura'")
        print("="*70)
        creada = asegurar_categoria_apertura(db)
        print(f"  Categoria nueva creada: {creada}")

        print("\n" + "="*70)
        print("PASO 3: Crear movimientos de apertura al 2024-12-31")
        print("="*70)
        result = crear_aperturas(db)
        print(f"  Movimientos creados:           {result['creados']}")
        print(f"  Saltados (centavos < ${UMBRAL}):  {result['saltados_centavos']}")
        if result['cajas_creadas']:
            print(f"  Cajas nuevas creadas: {len(result['cajas_creadas'])}")
            for display, norm, tipo in result['cajas_creadas']:
                print(f"    + {display:<20} (tipo={tipo})")

        print("\n  Top 15 aperturas creadas (por |delta|):")
        result['detalles'].sort(key=lambda x: abs(Decimal(x[3])), reverse=True)
        for display, t, s, d in result['detalles'][:15]:
            t_d = Decimal(t)
            s_d = Decimal(s)
            d_d = Decimal(d)
            print(f"    {display:<28} teorico={t_d:>15,.2f} sistema={s_d:>15,.2f} apertura={d_d:>15,.2f}")

        # COMMIT
        db.commit()
        print("\n" + "="*70)
        print("COMMIT exitoso")
        print("="*70)

    except Exception as e:
        db.rollback()
        print(f"\nROLLBACK por excepcion: {e!r}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
