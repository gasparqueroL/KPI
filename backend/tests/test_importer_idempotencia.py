"""Tests de idempotencia: importar el mismo CSV dos veces no debe duplicar."""

import io

import pandas as pd

from app.importers.dispatch import importar


VENTAS_CSV = """IdPedido,Fecha,hora,idCliente,cliente,formaDePago1,montoPago1,PAGO V.,formaDePago2,montoPago2,PAGO V. 2,total,comprobanteDePago,vendedor,idVenta,helperV
ped-1,30/4/2026 20:27:17,20:27:17,7932,Debora Alaniz,EMA TACA,"$156.249,80",TRUE,,,TRUE,"$156.249,80",,ROCIO,id-1,TRUE
ped-2,30/4/2026 17:05:55,17:05:55,6947,Nicolas Romano,NICO.A,"$53.726,92",FALSE,,,FALSE,"$53.726,92",,FLORENCIA,id-2,FALSE
"""

CAJA_CSV = """FECHA,Tipo de Operación,DETALLE DEL GASTO,MONTO,SALIDAS,ENTRADAS
01/05/2026,Sueldo,sueldo paolo,"$175.000,00",CAJA LOCAL,
29/04/2026,Botellas,Botellas x100,"$31.400,00",CAJA LOCAL,
29/04/2026,Botellas,Botellas x100,"$31.400,00",CAJA LOCAL,
"""


def test_ventas_idempotente(db):
    contenido = VENTAS_CSV.encode("utf-8")
    tipo, r1 = importar(db, contenido)
    assert tipo == "ventas"
    assert r1.aceptados == 2
    assert r1.ya_existian == 0

    # Segunda importación: nada nuevo
    _, r2 = importar(db, contenido)
    assert r2.aceptados == 0
    assert r2.ya_existian == 2


def test_movimientos_caja_idempotente_y_dedupe_intra_csv(db):
    contenido = CAJA_CSV.encode("utf-8")
    tipo, r1 = importar(db, contenido)
    assert tipo == "movimientos_caja"
    # Hay 3 filas en el CSV pero 2 son idénticas -> 2 aceptados, 1 ya_existian
    assert r1.aceptados == 2
    assert r1.ya_existian == 1

    # Segunda importación: todos los hash colisionan
    _, r2 = importar(db, contenido)
    assert r2.aceptados == 0
    assert r2.ya_existian == 3


DETALLE_CSV_ORDEN_A = """idVenta,fecha,producto,listaDePrecios,cantidad,precioUnitario,subTotal,descuentoUnitario,CST
v-1,30/4/2026 12:00:00,JABON,50,1,$100,$100,,50
v-1,30/4/2026 12:00:00,DETERGENTE,50,1,$200,$200,,100
"""

DETALLE_CSV_ORDEN_B = """idVenta,fecha,producto,listaDePrecios,cantidad,precioUnitario,subTotal,descuentoUnitario,CST
v-1,30/4/2026 12:00:00,DETERGENTE,50,1,$200,$200,,100
v-1,30/4/2026 12:00:00,JABON,50,1,$100,$100,,50
"""

VENTAS_PARA_DETALLE = """IdPedido,Fecha,hora,idCliente,cliente,formaDePago1,montoPago1,PAGO V.,formaDePago2,montoPago2,PAGO V. 2,total,comprobanteDePago,vendedor,idVenta,helperV
ped-x,30/4/2026 12:00:00,12:00:00,1,Cliente,EFECTIVO,"$300",TRUE,,,TRUE,"$300",,V,v-1,TRUE
"""


def test_detalle_dedupe_estable_con_orden_distinto(db):
    """Re-import con orden distinto NO debe duplicar líneas."""
    importar(db, VENTAS_PARA_DETALLE.encode("utf-8"))
    _, r1 = importar(db, DETALLE_CSV_ORDEN_A.encode("utf-8"))
    assert r1.aceptados == 2

    # Re-import con líneas en orden invertido: NO debe agregar nada
    _, r2 = importar(db, DETALLE_CSV_ORDEN_B.encode("utf-8"))
    assert r2.aceptados == 0, f"se duplicaron filas: aceptados={r2.aceptados}"
    assert r2.ya_existian == 2


CAJA_CON_FILA_INVALIDA = """FECHA,Tipo de Operación,DETALLE DEL GASTO,MONTO,SALIDAS,ENTRADAS
01/05/2026,Sueldo,fila ok 1,"$100",CAJA LOCAL,
fecha_invalida,Sueldo,fila rota,"$100",CAJA LOCAL,
01/05/2026,Sueldo,fila ok 2,"$100",CAJA LOCAL,
"""


def test_movimientos_fila_rota_no_revierte_aceptadas(db):
    """Una fila inválida en el medio NO debe deshacer las anteriores aceptadas."""
    _, r = importar(db, CAJA_CON_FILA_INVALIDA.encode("utf-8"))
    assert r.aceptados == 2, f"se perdieron filas válidas: aceptados={r.aceptados}"
    assert len(r.rechazados) >= 1


def test_importar_acepta_xlsx_directo(db):
    """La dueña sube .xlsx exportado de Excel sin convertir a CSV antes.
    El dispatch detecta el formato por magic bytes (PK\\x03\\x04 = zip)."""
    # Generamos un xlsx en memoria con el mismo contenido que VENTAS_CSV
    df = pd.read_csv(io.StringIO(VENTAS_CSV), dtype=str, keep_default_na=False)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    contenido_xlsx = buf.getvalue()

    # Sanity: empieza con magic bytes de zip
    assert contenido_xlsx[:4] == b"PK\x03\x04"

    tipo, r = importar(db, contenido_xlsx)
    assert tipo == "ventas"
    assert r.aceptados == 2


def test_es_xlsx_detecta_por_magic_bytes():
    from app.importers.dispatch import es_xlsx
    assert es_xlsx(b"PK\x03\x04ignorado") is True
    assert es_xlsx(b"IdPedido,Fecha\nx,y\n") is False
    assert es_xlsx(b"") is False
