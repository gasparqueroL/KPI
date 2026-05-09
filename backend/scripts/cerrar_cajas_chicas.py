"""Archiva cajas con saldo trivial (<= $5000 absoluto) y sin teórico
de la dueña. Las cajas con saldo material quedan para decisión manual.

Política: el saldo trivial (centavos a $5k) suele ser ruido contable
de cajas legacy/cerradas. Si la dueña no las incluyó en el teórico,
asumimos que no las trackea — archivarlas reduce ruido en /saldos sin
perder data (los movs siguen ahí, los puede desarchivar si necesita).
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func

from app.db import SessionLocal
from app.models.caja import Caja
from app.models.movimiento_caja import MovimientoCaja
from app.models.venta import Venta
from scripts.reconciliar_cajas import parse_teoricos

UMBRAL_TRIVIAL = Decimal("5000.00")


def main():
    db = SessionLocal()
    try:
        # Cajas con teórico — esas NO las tocamos.
        teoricos = parse_teoricos()
        cajas_con_teorico = set(teoricos.keys())

        # Computar saldos del sistema por caja (mismo cálculo que kpis.caja)
        ventas_c1 = dict(
            db.query(Venta.caja1, func.coalesce(func.sum(Venta.monto_pago1), 0))
            .filter(Venta.caja1.isnot(None))
            .group_by(Venta.caja1).all()
        )
        ventas_c2 = dict(
            db.query(Venta.caja2, func.coalesce(func.sum(Venta.monto_pago2), 0))
            .filter(Venta.caja2.isnot(None))
            .group_by(Venta.caja2).all()
        )
        entradas = dict(
            db.query(MovimientoCaja.caja_destino, func.sum(MovimientoCaja.monto))
            .filter(MovimientoCaja.caja_destino.isnot(None))
            .group_by(MovimientoCaja.caja_destino).all()
        )
        salidas = dict(
            db.query(MovimientoCaja.caja_origen, func.sum(MovimientoCaja.monto))
            .filter(MovimientoCaja.caja_origen.isnot(None))
            .group_by(MovimientoCaja.caja_origen).all()
        )

        # Solo cajas activas (no archivadas) sin teórico
        cajas_activas = db.query(Caja).filter(Caja.archivado_at.is_(None)).all()
        triviales = []
        materiales = []
        for c in cajas_activas:
            if c.nombre_normalizado in cajas_con_teorico:
                continue  # tiene teórico → no la toco
            v = Decimal(ventas_c1.get(c.nombre_normalizado, 0)) + Decimal(ventas_c2.get(c.nombre_normalizado, 0))
            ing = Decimal(entradas.get(c.nombre_normalizado, 0))
            egr = Decimal(salidas.get(c.nombre_normalizado, 0))
            saldo = v + ing - egr
            if saldo == 0:
                continue  # ya las archivamos las sin movs antes
            if abs(saldo) <= UMBRAL_TRIVIAL:
                triviales.append((c, saldo))
            else:
                materiales.append((c, saldo))

        print("=" * 70)
        print(f"CAJAS SIN TEORICO CON SALDO TRIVIAL (|saldo| <= ${UMBRAL_TRIVIAL})")
        print("=" * 70)
        ahora = datetime.utcnow()
        for c, saldo in sorted(triviales, key=lambda x: abs(x[1]), reverse=True):
            print(f"  {c.nombre_display:<28} saldo={saldo:>12,.2f}  -> archivada")
            c.archivado_at = ahora
        print(f"\n  Total archivadas: {len(triviales)}")

        print("\n" + "=" * 70)
        print(f"CAJAS SIN TEORICO CON SALDO MATERIAL (|saldo| > ${UMBRAL_TRIVIAL})")
        print(f"  Estas requieren decision manual (la duena no paso teorico):")
        print("=" * 70)
        for c, saldo in sorted(materiales, key=lambda x: abs(x[1]), reverse=True):
            print(f"  {c.nombre_display:<28} saldo={saldo:>15,.2f}")
        print(f"\n  Total cajas materiales sin teorico: {len(materiales)}")

        db.commit()
        print("\n" + "=" * 70)
        print("COMMIT exitoso")
        print("=" * 70)
    except Exception as e:
        db.rollback()
        print(f"ROLLBACK: {e!r}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
