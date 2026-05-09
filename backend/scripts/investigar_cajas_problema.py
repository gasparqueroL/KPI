"""Investiga las cajas problematicas antes de migrar:
- '$623,62' (nombre malformado, parece monto)
- 'JONA MERCADOOAGO' (typo de JONA MERCADOPAGO)
- 'FONDO GALPON.OLD' (vieja vs FONDO GALPON)
"""
from sqlalchemy import or_
from app.db import SessionLocal
from app.models.caja import Caja
from app.models.movimiento_caja import MovimientoCaja
from app.models.venta import Venta


def main():
    db = SessionLocal()
    try:
        problemas = {
            "$623,62": Caja.normalizar("$623,62"),
            "JONA MERCADOOAGO": Caja.normalizar("JONA MERCADOOAGO"),
            "FONDO GALPON.OLD": Caja.normalizar("FONDO GALPON.OLD"),
        }
        targets = {
            "JONA MERCADOOAGO": Caja.normalizar("JONA MERCADOPAGO"),
            "FONDO GALPON.OLD": Caja.normalizar("FONDO GALPON"),
        }

        for label, norm in problemas.items():
            print(f"\n{'='*70}")
            print(f"  {label}  (norm={norm!r})")
            print('='*70)
            caja = db.query(Caja).filter(Caja.nombre_normalizado == norm).first()
            if not caja:
                print(f"  NO existe en tabla cajas")
            else:
                print(f"  display={caja.nombre_display!r} tipo={caja.tipo!r} activa={caja.activa}")

            # Movimientos como origen
            movs_org = db.query(MovimientoCaja).filter(
                MovimientoCaja.caja_origen == norm
            ).count()
            # Movimientos como destino
            movs_dst = db.query(MovimientoCaja).filter(
                MovimientoCaja.caja_destino == norm
            ).count()
            # Ventas
            ventas_c1 = db.query(Venta).filter(Venta.caja1 == norm).count()
            ventas_c2 = db.query(Venta).filter(Venta.caja2 == norm).count()

            print(f"  movimientos_caja como origen:  {movs_org}")
            print(f"  movimientos_caja como destino: {movs_dst}")
            print(f"  ventas con caja1:              {ventas_c1}")
            print(f"  ventas con caja2:              {ventas_c2}")

            if label in targets:
                t_norm = targets[label]
                target = db.query(Caja).filter(Caja.nombre_normalizado == t_norm).first()
                print(f"  → target merge: norm={t_norm!r}, existe={bool(target)}")

            # Sample movs
            sample = db.query(MovimientoCaja).filter(
                or_(MovimientoCaja.caja_origen == norm, MovimientoCaja.caja_destino == norm)
            ).limit(3).all()
            for m in sample:
                print(f"    sample mov: id={m.id} fecha={m.fecha} tipo={m.tipo_operacion!r}"
                      f" monto={m.monto} origen={m.caja_origen!r} destino={m.caja_destino!r}")

            # Sample ventas (solo si hay)
            if ventas_c1 or ventas_c2:
                sample_v = db.query(Venta).filter(
                    or_(Venta.caja1 == norm, Venta.caja2 == norm)
                ).limit(3).all()
                for v in sample_v:
                    print(f"    sample venta: id={v.id_pedido} fecha={v.fecha} cliente={v.cliente!r}"
                          f" total={v.total} c1={v.caja1!r}/${v.monto_pago1} c2={v.caja2!r}/${v.monto_pago2}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
