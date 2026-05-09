"""Detector automático de alertas.

Por ahora son reglas hardcoded con umbrales razonables. Algunos umbrales
sensibles a inflación (ARS) se leen de env vars para evitar hardcodear
montos que la inflación argentina come en pocos meses.
"""

import os
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.formato import fmt_money_ar
from app.kpis._fechas import hoy_ar
from app.kpis import caja as kpi_caja
from app.kpis import cierres as kpi_cierres
from app.kpis import comerciales
from app.kpis import conciliacion as kpi_conciliacion
from app.kpis import cuentas_corrientes as kpi_cc
from app.kpis import derivados as kpi_derivados
from app.kpis import proveedores as kpi_prov
from app.models.caso_revisar import CasoRevisar
from app.models.categoria_caja import CategoriaCaja
from app.models.kpi_objetivo import KpiObjetivo


SEVERIDADES = {"critica": 3, "atencion": 2, "info": 1}

# Mapa de dominio por código de alerta — el frontend agrupa visualmente
# las alertas para que la dueña no vea 13 ítems mezclados sino 4 grupos
# claros. Default "datos" para alertas no clasificadas (como casos a
# revisar y categorías sin familia).
DOMINIOS = {
    # Comercial: ventas, productos, retención de clientes
    "caida_ventas": "comercial",
    "caida_margen": "comercial",
    "productos_perdida": "comercial",
    "productos_dormidos": "comercial",
    "clientes_perdidos": "comercial",
    "concentracion_ventas": "comercial",
    # Cobranza: dinero a cobrar/pagar
    "cobertura_baja": "cobranza",
    "clientes_morosos": "cobranza",
    "clientes_con_credito": "cobranza",
    "facturas_vencidas": "cobranza",
    "facturas_por_vencer": "cobranza",
    # Caja: estado financiero operativo
    "caja_saldo_negativo": "caja",
    "movimientos_atipicos": "caja",
    "cierres_con_diff": "caja",
    # Datos: integridad, configuración, mantenimiento
    "casos_pendientes": "datos",
    "categorias_sin_familia": "datos",
    # Objetivos: KPIs derivados que no cumplen target del mes en curso
    "objetivo_no_cumple": "comercial",
}


def evaluar_alertas(db: Session) -> list[dict[str, Any]]:
    alertas: list[dict] = []

    # 1. Casos a revisar pendientes.
    # Severidad fija en `atencion`: por más casos que haya, esto es backlog
    # administrativo, no plata en riesgo. Reservamos `critica` para alertas
    # financieras u operativas (decisión de jurado adversarial).
    n_casos = db.query(CasoRevisar).filter(
        CasoRevisar.estado == "pendiente",
        CasoRevisar.archivado_at.is_(None),
    ).count()
    if n_casos > 0:
        alertas.append({
            "codigo": "casos_pendientes",
            "severidad": "atencion",
            "titulo": f"{n_casos} casos pendientes de revisar",
            "detalle": "Filas que no pasaron validación durante import.",
            "link": "/casos",
            "valor": n_casos,
        })

    # 2. Categorías sin familia clasificada
    n_sin_fam = db.query(CategoriaCaja).filter(CategoriaCaja.familia.is_(None)).count()
    if n_sin_fam > 0:
        alertas.append({
            "codigo": "categorias_sin_familia",
            "severidad": "info",
            "titulo": f"{n_sin_fam} categorías de caja sin clasificar",
            "detalle": "Asigná familia para que aparezcan en Composición de gastos.",
            "link": "/config",
            "valor": n_sin_fam,
        })

    # 3. Saldo negativo en alguna caja operativa
    saldos = kpi_caja.saldos_por_caja(db)
    cajas_negativas = [c for c in saldos if c["tipo"] == "operativa" and c["saldo"] < 0]
    if cajas_negativas:
        nombres = ", ".join(c["caja"] for c in cajas_negativas[:3])
        if len(cajas_negativas) > 3:
            nombres += f" (+{len(cajas_negativas) - 3} más)"
        alertas.append({
            "codigo": "caja_saldo_negativo",
            "severidad": "critica",
            "titulo": f"{len(cajas_negativas)} cajas operativas con saldo negativo",
            "detalle": nombres,
            "link": "/caja",
            "valor": len(cajas_negativas),
        })

    # 4. Comparativa últimos 30 días vs 30 días previos
    hoy = hoy_ar()
    desde = hoy - timedelta(days=29)
    desde_prev = desde - timedelta(days=30)
    hasta_prev = desde - timedelta(days=1)

    actual = comerciales.resumen(db, desde=desde, hasta=hoy)
    anterior = comerciales.resumen(db, desde=desde_prev, hasta=hasta_prev)

    # 4a. Caída fuerte de ventas
    if anterior["ventas_totales"] > 0:
        delta_ventas = (actual["ventas_totales"] - anterior["ventas_totales"]) / anterior["ventas_totales"] * 100
        if delta_ventas <= -20:
            alertas.append({
                "codigo": "caida_ventas",
                "severidad": "critica",
                "titulo": f"Ventas cayeron {abs(delta_ventas):.1f}% en los últimos 30 días",
                "detalle": f"Período {desde} a {hoy} vs {desde_prev} a {hasta_prev}.",
                "link": "/comercial",
                "valor": delta_ventas,
            })
        elif delta_ventas <= -10:
            alertas.append({
                "codigo": "caida_ventas",
                "severidad": "atencion",
                "titulo": f"Ventas cayeron {abs(delta_ventas):.1f}% en los últimos 30 días",
                "detalle": f"Período {desde} a {hoy} vs {desde_prev} a {hasta_prev}.",
                "link": "/comercial",
                "valor": delta_ventas,
            })

    # 4b. Caída de margen %
    if anterior["margen_pct"] > 0:
        delta_margen_pp = actual["margen_pct"] - anterior["margen_pct"]
        if delta_margen_pp <= -3:
            alertas.append({
                "codigo": "caida_margen",
                "severidad": "atencion",
                "titulo": f"Margen bruto bajó {abs(delta_margen_pp):.1f} puntos",
                "detalle": f"De {anterior['margen_pct']:.1f}% a {actual['margen_pct']:.1f}% en los últimos 30 días.",
                "link": "/comercial",
                "valor": delta_margen_pp,
            })

    # 5. Cobertura de conciliación: facturado vs ingreso real
    conc = kpi_conciliacion.conciliacion(db)
    cobertura = conc["cobertura_pct"]
    if cobertura < 85:
        alertas.append({
            "codigo": "cobertura_baja",
            "severidad": "critica",
            "titulo": f"Cobertura de cobros: {cobertura:.1f}%",
            "detalle": f"Falta cobrar/registrar {fmt_money_ar(conc['diferencia_facturado_vs_operativo'], strict=True)} sobre {fmt_money_ar(conc['facturado'], strict=True)} facturados.",
            "link": "/conciliacion",
            "valor": cobertura,
        })
    elif cobertura < 95:
        alertas.append({
            "codigo": "cobertura_baja",
            "severidad": "atencion",
            "titulo": f"Cobertura de cobros: {cobertura:.1f}%",
            "detalle": f"Gap de {fmt_money_ar(conc['diferencia_facturado_vs_operativo'], strict=True)}. Revisar ventas sin cobro y discrepancias.",
            "link": "/conciliacion",
            "valor": cobertura,
        })

    # 6. Productos a pérdida real
    perdidas = comerciales.productos_a_perdida(db, limite=5)
    if perdidas:
        total_perdida = sum(abs(p["margen"]) for p in perdidas)
        alertas.append({
            "codigo": "productos_perdida",
            "severidad": "atencion",
            "titulo": f"{len(perdidas)} productos vendidos con margen negativo",
            "detalle": f"Pérdida acumulada: {fmt_money_ar(total_perdida, strict=True)}",
            "link": "/comercial",
            "valor": len(perdidas),
        })

    # 7. Facturas de proveedor vencidas o a vencer en 7 días.
    # Reusa `vencimientos_proximos(dias_ventana=7)` que ya filtra por saldo
    # > tolerancia y excluye anuladas. Particionamos en vencidas vs a vencer
    # para diferenciar severidad: vencidas = critica, próximas = atencion.
    vencimientos = kpi_prov.vencimientos_proximos(db, dias_ventana=7)
    vencidas = [v for v in vencimientos if v["vencida"]]
    proximas = [v for v in vencimientos if not v["vencida"]]
    if vencidas:
        total = sum(v["pendiente"] for v in vencidas)
        proveedores_dist = {v["proveedor"] for v in vencidas}
        nombres = ", ".join(list(proveedores_dist)[:3])
        if len(proveedores_dist) > 3:
            nombres += f" (+{len(proveedores_dist) - 3} más)"
        # Deep link al proveedor con mayor pendiente (el que más urge pagar
        # o renegociar). Frontend Proveedores.jsx ya tiene handler `?proveedor=X`.
        peor = max(vencidas, key=lambda v: v["pendiente"])
        link = "/proveedores"
        if peor.get("id_proveedor"):
            link += f"?proveedor={peor['id_proveedor']}"
        alertas.append({
            "codigo": "facturas_vencidas",
            "severidad": "critica",
            "titulo": f"{len(vencidas)} facturas de proveedor vencidas",
            "detalle": f"Total adeudado: {fmt_money_ar(total, strict=True)} — {nombres}",
            "link": link,
            "valor": len(vencidas),
        })
    if proximas:
        total = sum(v["pendiente"] for v in proximas)
        alertas.append({
            "codigo": "facturas_por_vencer",
            "severidad": "atencion",
            "titulo": f"{len(proximas)} facturas vencen en los próximos 7 días",
            "detalle": f"Total a pagar: {fmt_money_ar(total, strict=True)}",
            "link": "/proveedores",
            "valor": len(proximas),
        })

    # 8. Concentración de ventas en pocos clientes (riesgo comercial).
    # Una PyME que depende de 1-2 clientes para sustentar el negocio está
    # un cobro perdido de cerrar. Métrica: % del top1 sobre ventas totales
    # 90d. Severidad escalonada — top1 dominante (50%+) es señal crítica;
    # top1 alto (30%+) o top3 alto (60%+) es atención.
    # 89 = 90 días inclusivos contando el día de hoy (89 días atrás + hoy = 90).
    # El KPI `concentracion_clientes` NO tiene ventana propia (acepta
    # desde/hasta arbitrario), así que esta alerta define la suya. La magic
    # 89 garantiza que el período medido coincida con el título "(90d)" que
    # la dueña ve — sino el texto miente sobre lo que se calculó.
    desde_conc = hoy - timedelta(days=89)
    conc = comerciales.concentracion_clientes(db, desde=desde_conc, hasta=hoy)
    # Umbrales centralizados en `comerciales._umbrales_concentracion` —
    # leemos del mismo dict que devuelve el endpoint para que frontend y
    # alerta no puedan desincronizarse.
    UMBRAL_TOP1_CRITICA = conc["umbrales"]["top1_critica"]
    UMBRAL_TOP1_ATENCION = conc["umbrales"]["top1_atencion"]
    UMBRAL_TOP3_ATENCION = conc["umbrales"]["top3_atencion"]
    if conc["total_periodo"] > 0 and conc["top_clientes"]:
        top1 = conc["top_clientes"][0]
        # Deep link al cliente top1 — la dueña ve "Mega Cliente = 50%" y al
        # click va al ledger del cliente directamente. Solo aplica en las
        # branches que SÍ tienen un cliente individual identificado (top1
        # crítica/atención). La branch top3 abajo es sobre concentración
        # colectiva — sin entity individual → link genérico a /comercial.
        #
        # Nota: la alerta tiene `dominio: "comercial"` (DOMINIOS map) pero
        # el link sale a `/cuentas-corrientes`. Inconsistencia DELIBERADA:
        # el contexto útil para investigar concentración (saldo, historial,
        # ledger) está en el ledger del cliente, no en /comercial que muestra
        # tops genéricos. El dominio agrupa visualmente la alerta;
        # el link la hace accionable.
        link_top1 = "/cuentas-corrientes"
        if top1.get("id_cliente"):
            link_top1 += f"?cliente={top1['id_cliente']}"
        if conc["top_1_pct"] >= UMBRAL_TOP1_CRITICA:
            alertas.append({
                "codigo": "concentracion_ventas",
                "severidad": "critica",
                "titulo": f"Concentración: {top1['cliente']} = {conc['top_1_pct']:.0f}% de las ventas (90d)",
                "detalle": f"Riesgo alto: perder este cliente equivale a cerrar el negocio. Top 3 acumula {conc['top_3_pct']:.0f}%.",
                "link": link_top1,
                "valor": conc["top_1_pct"],
            })
        elif conc["top_1_pct"] >= UMBRAL_TOP1_ATENCION:
            alertas.append({
                "codigo": "concentracion_ventas",
                "severidad": "atencion",
                "titulo": f"{top1['cliente']} representa {conc['top_1_pct']:.0f}% de las ventas (90d)",
                "detalle": f"Diversificar cartera: top 3 acumula {conc['top_3_pct']:.0f}%, top 5 acumula {conc['top_5_pct']:.0f}%.",
                "link": link_top1,
                "valor": conc["top_1_pct"],
            })
        elif conc["top_3_pct"] >= UMBRAL_TOP3_ATENCION:
            alertas.append({
                "codigo": "concentracion_ventas",
                "severidad": "atencion",
                "titulo": f"Top 3 clientes acumulan {conc['top_3_pct']:.0f}% de las ventas (90d)",
                "detalle": f"Concentración elevada en pocos clientes. Top 5: {conc['top_5_pct']:.0f}%.",
                "link": "/comercial",
                "valor": conc["top_3_pct"],
            })

    # 9. Clientes con saldo +90 días (morosidad estructural).
    # Reusa `aging_cobros` que ya respeta `pagos_aplicados` como override
    # cuando hay vinculación granular.
    #
    # Limitación consciente: solo miramos `bucket_90_mas`, no el saldo
    # total. Un cliente con $40k en 90+ y $200k repartidos en 0-30/31-60
    # NO dispara esta alerta (el aging acumula FIFO desde lo más viejo,
    # entonces si tiene saldo en 90+, el deterioro real está ahí). Para
    # detectar concentración de deuda total existe `cobertura_baja` (#5).
    # Esta alerta enfoca específicamente "cobranza complicada por antigüedad".
    #
    # Umbral en ARS por env var: la inflación argentina obliga a recalibrar
    # cada 6-12 meses; hardcodearlo equivale a pedir un PR cada vez.
    UMBRAL_MOROSIDAD = int(os.getenv("UMBRAL_MOROSIDAD_ARS", "50000"))
    aging = kpi_cc.aging_cobros(db)
    morosos = [
        it for it in aging["items"]
        if it["bucket_90_mas"] >= UMBRAL_MOROSIDAD
    ]
    if morosos:
        morosos.sort(key=lambda it: it["bucket_90_mas"], reverse=True)
        total_90 = sum(it["bucket_90_mas"] for it in morosos)
        nombres = ", ".join(it["cliente"] or f"#{it['id_cliente']}" for it in morosos[:3])
        if len(morosos) > 3:
            nombres += f" (+{len(morosos) - 3} más)"
        # Deep link al cliente con peor morosidad — la dueña ve la alerta
        # y al click abre el ledger del cliente directamente, no la página
        # genérica. Frontend (CuentasCorrientes.jsx) ya tiene handler para
        # `?cliente=X`. Si por algún motivo el id no está, fallback a la
        # página general — sino el link queda roto y la dueña pierde 1 click.
        top = morosos[0]
        link = "/cuentas-corrientes"
        if top.get("id_cliente"):
            link += f"?cliente={top['id_cliente']}"
        alertas.append({
            "codigo": "clientes_morosos",
            "severidad": "atencion",
            "titulo": f"{len(morosos)} clientes con saldo +90 días",
            "detalle": f"Total moroso: {fmt_money_ar(total_90, strict=True)} — {nombres}",
            "link": link,
            "valor": len(morosos),
        })

    # 9b. Clientes con saldo a favor (sobrepagos / anticipos sin aplicar).
    # Reusa el `aging` ya cargado arriba para clientes_morosos. Plata que la
    # PyME le debe a clientes — no es deuda en sentido estricto pero conviene
    # aplicar al próximo pedido o devolver. Severidad `info`: no es urgente,
    # solo "tenés esto pendiente de resolver".
    #
    # Umbral en ARS por env var (inflación argentina obliga a recalibrar):
    # debajo del umbral, el ruido de centavitos de redondeo no vale alertar.
    UMBRAL_CREDITO = int(os.getenv("UMBRAL_CREDITO_AFAVOR_ARS", "30000"))
    con_credito = aging.get("con_credito", [])
    total_credito = sum(c["credito_a_favor"] for c in con_credito)
    if total_credito >= UMBRAL_CREDITO:
        nombres = ", ".join(
            (c["cliente"] or f"#{c['id_cliente']}") for c in con_credito[:3]
        )
        if len(con_credito) > 3:
            nombres += f" (+{len(con_credito) - 3} más)"
        alertas.append({
            "codigo": "clientes_con_credito",
            "severidad": "info",
            "titulo": (
                f"{len(con_credito)} clientes con saldo a favor — {fmt_money_ar(total_credito, strict=True)}"
            ),
            "detalle": (
                f"Sobrepagos / anticipos pendientes de aplicar — {nombres}"
            ),
            "link": "/cuentas-corrientes",
            "valor": total_credito,
        })

    # 10. Clientes perdidos: tenían historial pero hace 90+ días no compran.
    # Útil para que comercial intente recontactar antes de que sea irreversible.
    # Umbrales por env var: cambiar `UMBRAL_DIAS_INACTIVIDAD` a 60 da más
    # señales tempranas (puede ser ruidoso); 120 menos pero más sólidas.
    DIAS_INACT = int(os.getenv("UMBRAL_DIAS_INACTIVIDAD", "90"))
    PEDIDOS_MIN = int(os.getenv("UMBRAL_PEDIDOS_MIN_HISTORICOS", "3"))
    perdidos = comerciales.clientes_perdidos(
        db, dias_inactividad=DIAS_INACT, pedidos_minimos=PEDIDOS_MIN,
    )
    if perdidos:
        # Top 3 por monto histórico (lo más doloroso si efectivamente se fueron).
        top = perdidos[:3]
        nombres = ", ".join((p["cliente"] or f"#{p['id_cliente']}") for p in top)
        if len(perdidos) > 3:
            nombres += f" (+{len(perdidos) - 3} más)"
        total_monto = sum(p["monto_total"] for p in perdidos)
        # Deep link al cliente top perdido (mayor monto histórico) — la dueña
        # ve la alerta y al click abre su ledger en cuentas-corrientes para
        # revisar contexto antes de llamarlo a recontactar.
        peor = top[0]
        link = "/cuentas-corrientes"
        if peor.get("id_cliente"):
            link += f"?cliente={peor['id_cliente']}"
        alertas.append({
            "codigo": "clientes_perdidos",
            "severidad": "atencion",
            # "sin pedidos" en vez de "sin compras" — en boca de la dueña
            # "compras" suele referirse a gasto a proveedores. "Pedidos" es
            # inequívoco: ventas que el cliente nos hace.
            "titulo": (
                f"{len(perdidos)} clientes habituales sin pedidos en {DIAS_INACT}+ días"
            ),
            "detalle": f"Histórico {fmt_money_ar(total_monto, strict=True)} — {nombres}",
            "link": link,
            "valor": len(perdidos),
        })

    # 11. Productos dormidos: tenían rotación pero hace 60+ días no se venden.
    # Posible señal de stock que se está enfriando o cambio en demanda.
    DIAS_INACT_PROD = int(os.getenv("UMBRAL_DIAS_INACTIVIDAD_PRODUCTO", "60"))
    VENTAS_MIN_PROD = int(os.getenv("UMBRAL_VENTAS_MIN_HISTORICAS_PRODUCTO", "5"))
    productos_dormidos = comerciales.productos_sin_venta_reciente(
        db, dias_inactividad=DIAS_INACT_PROD, ventas_minimas=VENTAS_MIN_PROD,
    )
    if productos_dormidos:
        top = productos_dormidos[:3]
        nombres = ", ".join((p["producto"] or "")[:30] for p in top)
        if len(productos_dormidos) > 3:
            nombres += f" (+{len(productos_dormidos) - 3} más)"
        total_monto = sum(p["monto_total"] for p in productos_dormidos)
        alertas.append({
            "codigo": "productos_dormidos",
            "severidad": "atencion",
            "titulo": (
                f"{len(productos_dormidos)} productos con rotación previa sin ventas "
                f"en {DIAS_INACT_PROD}+ días"
            ),
            "detalle": f"Histórico {fmt_money_ar(total_monto, strict=True)} — {nombres}",
            "link": "/comercial",
            "valor": len(productos_dormidos),
        })

    # 12. Movimientos atípicos: gastos N× mayores al promedio histórico
    # de su categoría. Detecta errores de carga (typo en monto) o gastos
    # anómalos a revisar.
    FACTOR_ATIPICO = float(os.getenv("UMBRAL_FACTOR_ATIPICO", "5.0"))
    atipicos = kpi_caja.movimientos_atipicos(db, factor=FACTOR_ATIPICO)
    if atipicos:
        peor = atipicos[0]  # ya viene ordenado por monto desc
        mas = ""
        if len(atipicos) > 1:
            mas = f" (+{len(atipicos) - 1} más)"
        alertas.append({
            "codigo": "movimientos_atipicos",
            "severidad": "atencion",
            "titulo": (
                f"{len(atipicos)} movimientos con monto atípico "
                f"({FACTOR_ATIPICO:.0f}× promedio)"
            ),
            "detalle": (
                f"Mayor: {fmt_money_ar(peor['monto'], strict=True)} en {peor['tipo_operacion']} "
                f"vs promedio {fmt_money_ar(peor['promedio_historico'], strict=True)}{mas}"
            ),
            "link": "/caja-diaria",
            "valor": len(atipicos),
        })

    # 13. Cierres de caja con discrepancia entre declarado vs calculado.
    # Si la dueña declaró $X al cerrar pero el sistema calcula $Y > umbral,
    # algo se cargó mal o se modificó retroactivamente. Severidad escala
    # a crítica si el peor diff supera el umbral crítico — un agujero de
    # $50k en una PyME chica no es "atención", es "robo o error grave".
    umbrales_cc = kpi_cierres.umbrales_auditoria_cierre()
    cierres_con_diff = kpi_cierres.auditar_cierres(db, tolerancia=umbrales_cc["tolerancia"])
    if cierres_con_diff:
        peores = sorted(cierres_con_diff, key=lambda c: c["diff_abs"], reverse=True)[:3]
        nombres = ", ".join(f"{c['caja']} {c['fecha']}" for c in peores)
        if len(cierres_con_diff) > 3:
            nombres += f" (+{len(cierres_con_diff) - 3} más)"
        peor_diff = max(c["diff_abs"] for c in cierres_con_diff)
        es_critico = peor_diff > float(umbrales_cc["umbral_critica"])
        alertas.append({
            "codigo": "cierres_con_diff",
            "severidad": "critica" if es_critico else "atencion",
            "titulo": (
                f"{len(cierres_con_diff)} cierres con discrepancia "
                f"(peor: {fmt_money_ar(peor_diff, strict=True)})"
            ),
            "detalle": f"Revisar: {nombres}",
            "link": "/caja-diaria",
            "valor": len(cierres_con_diff),
        })

    # Objetivos: alertar por cada KPI con objetivo cargado que NO cumple.
    # Usamos el MES ANTERIOR CERRADO (no el mes en curso) — el día 1-5 de
    # cualquier mes los datos del mes en curso suelen estar incompletos
    # y todo daría "valor=None → cumple_objetivo=None → sin alerta",
    # generando falsos negativos. Con mes anterior la cifra es estable.
    #
    # Performance: usamos `kpis_del_mes` directo (sin comparativa) y
    # cruzamos manualmente con los objetivos. Evita el costo de correr
    # también el año anterior que el wrapper haría.
    try:
        objetivos = db.query(KpiObjetivo).all()
        if objetivos:
            hoy = hoy_ar()
            # Primer día del mes actual menos 1 → último del mes anterior.
            ultimo_mes_anterior = hoy.replace(day=1) - timedelta(days=1)
            periodo_anterior = f"{ultimo_mes_anterior.year:04d}-{ultimo_mes_anterior.month:02d}"
            codigos_con_objetivo = {o.codigo for o in objetivos}
            objetivos_dict = {
                o.codigo: float(o.valor_objetivo) for o in objetivos
            }
            r = kpi_derivados.kpis_del_mes(
                db, periodo_anterior, solo_codigos=codigos_con_objetivo,
            )
            no_cumplen = []
            for k in r["kpis"]:
                if k["valor"] is None:
                    continue
                obj = objetivos_dict.get(k["codigo"])
                if obj is None:
                    continue
                if k["mejor_si"] == "bajar":
                    cumple = k["valor"] <= obj
                else:
                    cumple = k["valor"] >= obj
                if not cumple:
                    k["objetivo"] = obj
                    no_cumplen.append(k)
            for k in no_cumplen:
                op = "≤" if k["mejor_si"] == "bajar" else "≥"
                alertas.append({
                    "codigo": "objetivo_no_cumple",
                    "severidad": "atencion",
                    "titulo": f"{k['label']}: no cumple objetivo ({periodo_anterior})",
                    "detalle": f"Actual {k['valor']} · objetivo {op} {k['objetivo']}",
                    "link": "/kpis-manuales",
                    "valor": k["valor"],
                })
    except Exception as e:
        # No queremos que un error en objetivos rompa TODAS las alertas.
        import logging
        logging.getLogger("kpi").warning(
            "Falló evaluación de alertas por objetivos: %r", e,
        )

    # Asignar dominio a cada alerta usando el mapa centralizado. Default
    # "datos" si el código no está clasificado (alerta nueva sin entry en
    # DOMINIOS — fallback seguro en lugar de tirar KeyError).
    for a in alertas:
        a["dominio"] = DOMINIOS.get(a["codigo"], "datos")

    # Ordenar por severidad descendente
    alertas.sort(key=lambda a: SEVERIDADES.get(a["severidad"], 0), reverse=True)
    return alertas
