"""Endpoints REST para KPIs comerciales."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.kpis import comerciales

router = APIRouter(prefix="/api/kpis/comerciales", tags=["kpis-comerciales"])


@router.get("/resumen")
def resumen(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    vendedor: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return comerciales.resumen(db, desde=desde, hasta=hasta, vendedor=vendedor)


@router.get("/serie-temporal")
def serie_temporal(
    periodo: str = Query("mes", regex="^(dia|semana|mes|anio)$"),
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    vendedor: str | None = Query(None),
    db: Session = Depends(get_db),
):
    try:
        return comerciales.serie_temporal(db, periodo=periodo, desde=desde, hasta=hasta, vendedor=vendedor)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/proyeccion-mes")
def proyeccion_mes(db: Session = Depends(get_db)):
    """Proyección de cierre del mes en curso (extrapolación lineal)."""
    return comerciales.proyeccion_mes_actual(db)


@router.get("/analisis-abc-productos")
def analisis_abc_productos(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    db: Session = Depends(get_db),
):
    """Clasificación ABC (Pareto) de productos por contribución al margen."""
    return comerciales.analisis_abc_productos(db, desde=desde, hasta=hasta)


@router.get("/clientes-de-producto")
def clientes_de_producto(
    producto: str = Query(..., min_length=1),
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    limite: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Drill-down: clientes que compraron un producto, ordenados por monto."""
    return comerciales.clientes_de_producto(
        db, producto=producto, desde=desde, hasta=hasta, limite=limite
    )


@router.get("/top-productos")
def top_productos(
    por: str = Query("margen", regex="^(margen|ingresos|cantidad)$"),
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    limite: int = Query(10, ge=1, le=100),
    vendedor: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return comerciales.top_productos(db, por=por, desde=desde, hasta=hasta, limite=limite, vendedor=vendedor)


@router.get("/top-clientes")
def top_clientes(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    limite: int = Query(10, ge=1, le=100),
    vendedor: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return comerciales.top_clientes(db, desde=desde, hasta=hasta, limite=limite, vendedor=vendedor)


@router.get("/concentracion-clientes")
def concentracion_clientes(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    db: Session = Depends(get_db),
):
    """% que representa el top 1/3/5/10 sobre ventas totales del período.
    Útil para visualizar riesgo de concentración aún cuando no dispara alerta."""
    return comerciales.concentracion_clientes(db, desde=desde, hasta=hasta)


@router.get("/top-vendedores")
def top_vendedores(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    limite: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return comerciales.top_vendedores(db, desde=desde, hasta=hasta, limite=limite)


@router.get("/recompra")
def recompra(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    db: Session = Depends(get_db),
):
    return comerciales.recompra(db, desde=desde, hasta=hasta)


@router.get("/formas-pago")
def formas_pago(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    db: Session = Depends(get_db),
):
    return comerciales.formas_pago(db, desde=desde, hasta=hasta)


@router.get("/cohortes")
def cohortes(
    meses_max: int = Query(12, ge=1, le=24),
    minimo_cohorte: int = Query(5, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return comerciales.cohortes_retencion(
        db, meses_max=meses_max, minimo_cohorte=minimo_cohorte
    )


@router.get("/productos-a-perdida")
def productos_a_perdida(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    limite: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return comerciales.productos_a_perdida(db, desde=desde, hasta=hasta, limite=limite)
