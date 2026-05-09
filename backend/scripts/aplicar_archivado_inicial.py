"""Aplica una vez el archivado inicial:
1. Casos resueltos (descartado/corregido) -> archivados
2. Cajas sin uso (ni movs, ni ventas) -> archivadas

Idempotente: re-correr no archiva nada que ya esté archivado.
"""
from datetime import datetime

from app.db import SessionLocal
from app.models.caja import Caja
from app.models.caso_revisar import CasoRevisar
from app.models.movimiento_caja import MovimientoCaja
from app.models.venta import Venta


def archivar_casos_resueltos(db) -> int:
    ahora = datetime.utcnow()
    return (
        db.query(CasoRevisar)
        .filter(
            CasoRevisar.estado.in_(["descartado", "corregido"]),
            CasoRevisar.archivado_at.is_(None),
        )
        .update(
            {CasoRevisar.archivado_at: ahora, CasoRevisar.updated_at: ahora},
            synchronize_session=False,
        )
    )


def archivar_cajas_sin_uso(db) -> tuple[int, list[str]]:
    en_uso: set[str] = set()
    for col in (Venta.caja1, Venta.caja2, MovimientoCaja.caja_origen, MovimientoCaja.caja_destino):
        en_uso.update(r[0] for r in db.query(col).filter(col.isnot(None)).distinct().all())

    q = db.query(Caja).filter(Caja.archivado_at.is_(None))
    if en_uso:
        q = q.filter(~Caja.nombre_normalizado.in_(en_uso))
    candidatas = q.all()

    ahora = datetime.utcnow()
    nombres = []
    for c in candidatas:
        c.archivado_at = ahora
        nombres.append(c.nombre_display)
    return len(nombres), nombres


def main():
    db = SessionLocal()
    try:
        print("=" * 70)
        print("PASO 1: Archivar casos resueltos")
        print("=" * 70)
        # Estado pre
        from sqlalchemy import func as f
        por_estado_pre = dict(
            db.query(CasoRevisar.estado, f.count())
            .filter(CasoRevisar.archivado_at.is_(None))
            .group_by(CasoRevisar.estado).all()
        )
        print(f"  Pendientes activos:  {por_estado_pre.get('pendiente', 0)}")
        print(f"  Descartados activos: {por_estado_pre.get('descartado', 0)}")
        print(f"  Corregidos activos:  {por_estado_pre.get('corregido', 0)}")

        n_casos = archivar_casos_resueltos(db)
        print(f"\n  Casos archivados: {n_casos}")

        print("\n" + "=" * 70)
        print("PASO 2: Archivar cajas sin uso")
        print("=" * 70)
        cajas_pre = db.query(Caja).filter(Caja.archivado_at.is_(None)).count()
        print(f"  Cajas activas antes: {cajas_pre}")

        n_cajas, nombres = archivar_cajas_sin_uso(db)
        print(f"\n  Cajas archivadas: {n_cajas}")
        if nombres:
            print(f"  Nombres (primeras 20): {nombres[:20]}")
            if len(nombres) > 20:
                print(f"  ... y {len(nombres) - 20} mas")

        cajas_post = db.query(Caja).filter(Caja.archivado_at.is_(None)).count()
        print(f"\n  Cajas activas despues: {cajas_post}")

        db.commit()
        print("\n" + "=" * 70)
        print("COMMIT exitoso")
        print("=" * 70)

    except Exception as e:
        db.rollback()
        print(f"\nROLLBACK por excepcion: {e!r}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
