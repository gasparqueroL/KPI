"""KPIs derivados que combinan datos manuales (KpiManual) con datos
computados del sistema. Una fila por KPI con su valor + status:
  ok      → valor calculado, completo
  parcial → valor con advertencia (uno de los inputs faltó, default 0)
  faltan  → faltan datos manuales, no se puede computar
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.kpis import financieros
from app.models.kpi_manual import KpiManual
from app.models.kpi_objetivo import KpiObjetivo
from app.models.venta import Venta


def _to_float(v) -> float:
    return float(v) if v is not None else 0.0


def _periodo_a_rango(periodo: str) -> tuple[date, date]:
    """YYYY-MM -> (primer dia, ultimo dia)."""
    anio = int(periodo[:4])
    mes = int(periodo[5:])
    desde = date(anio, mes, 1)
    if mes == 12:
        hasta = date(anio + 1, 1, 1) - timedelta(days=1)
    else:
        hasta = date(anio, mes + 1, 1) - timedelta(days=1)
    return desde, hasta


def _valores_manuales(db: Session, periodo: str) -> dict[str, Decimal]:
    rows = db.query(KpiManual).filter(KpiManual.periodo == periodo).all()
    return {r.codigo: Decimal(str(r.valor)) for r in rows}


def _kpi(codigo: str, area: str, label: str, valor, formula: str,
        unidad: str, status: str, **extras) -> dict:
    return {
        "codigo": codigo,
        "area": area,
        "label": label,
        "valor": valor,
        "unidad": unidad,
        "formula": formula,
        "status": status,
        "mejor_si": "bajar" if codigo in MENOS_ES_MEJOR else "subir",
        **extras,
    }


def kpis_del_mes(
    db: Session, periodo: str, solo_codigos: set[str] | None = None,
) -> dict[str, Any]:
    """Computa los KPIs derivados para un mes específico (YYYY-MM).

    Si `solo_codigos` está dado, salta los bloques de cómputo cuyos KPIs
    no fueron pedidos. Performance crítico para `/derivados/historico/{codigo}`
    que llama a esto 12 veces — sin filtro corre ~200 queries por request.
    """
    desde, hasta = _periodo_a_rango(periodo)
    m = _valores_manuales(db, periodo)

    out: list[dict] = []
    # Set de KPIs financieros que dependen de margen_operativo computado.
    FIN_CODIGOS = {
        "margen_neto", "margen_neto_pct", "margen_operativo", "ebitda",
        "roi", "roa", "roe", "endeudamiento", "productividad_por_empleado",
        "cac", "ltv_proxy", "costo_por_lead", "tasa_conversion", "romi",
        "tasa_reclamos",
    }
    LIQ_CODIGOS = {"liquidez_corriente", "capital_trabajo"}
    LTV_CODIGOS = {"ltv_proxy"}

    def _aplica(codigo: str) -> bool:
        return solo_codigos is None or codigo in solo_codigos

    def _aplica_alguno(codigos: set[str]) -> bool:
        return solo_codigos is None or bool(codigos & solo_codigos)

    def _div(num, den):
        """num/den -> float, None si den es 0/None/inválido o num es None."""
        if num is None or den is None:
            return None
        try:
            d = Decimal(str(den))
            if d == 0:
                return None
            return float(Decimal(str(num)) / d)
        except Exception:
            return None

    def _pct(num, den):
        """num/den * 100 -> float, None si la división no aplica.
        Reemplaza el patrón frágil `_div(a,b) and _div(a,b) * 100`."""
        v = _div(num, den)
        return v * 100 if v is not None else None

    def _val(v):
        """Manual value -> float o None (no 0)."""
        return _to_float(v) if v is not None else None

    # ===== Financieros (combinan manual + computado) =====
    activos = m.get("activos_totales")
    activos_corr = m.get("activos_corrientes")
    pasivos = m.get("pasivos_totales")
    pasivos_corr = m.get("pasivos_corrientes")
    patrimonio = m.get("patrimonio_neto")
    capital_inv = m.get("capital_invertido")

    # Compute margen_operativo solo si lo necesitamos (~5 queries).
    if _aplica_alguno(FIN_CODIGOS):
        margen_op = financieros.margen_operativo(db, desde=desde, hasta=hasta)
        ganancia = Decimal(str(margen_op["margen_operativo"]))
        ingresos_ventas = Decimal(str(margen_op["ingresos_total"]))
    else:
        margen_op = None
        ganancia = Decimal("0")
        ingresos_ventas = Decimal("0")

    if _aplica("margen_neto") and margen_op:
        out.append(_kpi("margen_neto", "Dirección", "Margen neto del período",
            margen_op["margen_operativo"], "ingresos - egresos operativos", "ARS", "ok"))
    if _aplica("margen_neto_pct") and margen_op:
        out.append(_kpi("margen_neto_pct", "Dirección", "Margen neto %",
            margen_op["margen_operativo_pct"],
            "(ingresos - egresos) / ingresos * 100", "%", "ok"))
    if _aplica("margen_operativo") and margen_op:
        out.append(_kpi("margen_operativo", "Dirección", "Margen operativo",
            margen_op["margen_operativo"], "= margen neto en ausencia de amort/intereses", "ARS", "ok"))

    # EBITDA: reusa margen_op ya computado (evita doble call a margen_operativo).
    if _aplica("ebitda") and margen_op:
        amortizaciones = 0.0  # sin categoría de amortización cargada todavía
        ebitda_val = margen_op["margen_operativo"] + amortizaciones
        out.append(_kpi("ebitda", "Dirección", "EBITDA (aprox)",
            ebitda_val,
            "margen operativo + amortizaciones (sin amort = ≈ margen op)", "ARS",
            "parcial" if amortizaciones == 0 else "ok",
            nota="EBITDA aproximado: sin amortizaciones cargadas, equivale al margen operativo."))

    # ROI = ganancia / capital_invertido
    if _aplica("roi"):
        out.append(_kpi("roi", "Dirección", "ROI",
            _pct(ganancia, capital_inv),
            "ganancia / capital_invertido * 100", "%",
            "ok" if capital_inv is not None else "faltan",
            falta=None if capital_inv is not None else "capital_invertido"))

    # ROA = ganancia / activos_totales
    if _aplica("roa"):
        out.append(_kpi("roa", "Dirección", "ROA (retorno sobre activos)",
            _pct(ganancia, activos),
            "ganancia / activos_totales * 100", "%",
            "ok" if activos is not None else "faltan",
            falta=None if activos is not None else "activos_totales"))

    # ROE = ganancia / patrimonio
    if _aplica("roe"):
        out.append(_kpi("roe", "Dirección", "ROE (retorno sobre patrimonio)",
            _pct(ganancia, patrimonio),
            "ganancia / patrimonio_neto * 100", "%",
            "ok" if patrimonio is not None else "faltan",
            falta=None if patrimonio is not None else "patrimonio_neto"))

    # Liquidez = activos_corrientes / pasivos_corrientes
    if _aplica("liquidez_corriente"):
        out.append(_kpi("liquidez_corriente", "Finanzas", "Liquidez corriente",
            _div(activos_corr, pasivos_corr),
            "activos_corrientes / pasivos_corrientes", "ratio",
            "ok" if (activos_corr is not None and pasivos_corr is not None) else "faltan",
            falta=None if (activos_corr is not None and pasivos_corr is not None) else "activos_corrientes/pasivos_corrientes"))

    # Endeudamiento = pasivos / activos
    if _aplica("endeudamiento"):
        out.append(_kpi("endeudamiento", "Finanzas", "Endeudamiento",
            _pct(pasivos, activos),
            "pasivos_totales / activos_totales * 100", "%",
            "ok" if (pasivos is not None and activos is not None) else "faltan",
            falta=None if (pasivos is not None and activos is not None) else "pasivos_totales/activos_totales"))

    # Capital de trabajo = activo_corriente - pasivo_corriente
    if _aplica("capital_trabajo"):
        cap_trab = None
        if activos_corr is not None and pasivos_corr is not None:
            cap_trab = float(Decimal(str(activos_corr)) - Decimal(str(pasivos_corr)))
        out.append(_kpi("capital_trabajo", "Finanzas", "Capital de trabajo",
            cap_trab,
            "activos_corrientes - pasivos_corrientes", "ARS",
            "ok" if cap_trab is not None else "faltan",
            falta=None if cap_trab is not None else "activos_corrientes/pasivos_corrientes"))

    # ===== RRHH =====
    emp_ini = m.get("empleados_inicio_mes")
    emp_fin = m.get("empleados_fin_mes")
    altas = m.get("altas_mes")
    bajas = m.get("bajas_mes")
    aus = m.get("dias_ausencia_total")
    dias_lab = m.get("dias_laborables_mes")
    accidentes = m.get("accidentes_mes")
    ant = m.get("antiguedad_promedio_anios")
    cobertura = m.get("dias_cobertura_vacante")

    emp_promedio = None
    if emp_ini is not None and emp_fin is not None:
        emp_promedio = (Decimal(str(emp_ini)) + Decimal(str(emp_fin))) / 2

    # Rotación = bajas / promedio empleados * 100
    out.append(_kpi("rotacion", "RRHH", "Rotación de personal %",
        _pct(bajas, emp_promedio),
        "bajas / empleados_promedio * 100", "%",
        "ok" if (bajas is not None and emp_promedio is not None and emp_promedio != 0) else "faltan",
        falta=None if (bajas is not None and emp_promedio) else "bajas_mes/empleados_*"))

    # Ausentismo = ausencias / días_laborables * 100
    out.append(_kpi("ausentismo", "RRHH", "Ausentismo %",
        _pct(aus, dias_lab),
        "dias_ausencia / dias_laborables * 100", "%",
        "ok" if (aus is not None and dias_lab is not None and dias_lab != 0) else "faltan",
        falta=None if (aus is not None and dias_lab) else "dias_ausencia/dias_laborables"))

    # Productividad por empleado = ingresos del período / empleados promedio.
    # `ingresos_ventas` ya está inicializado en el bloque financiero arriba
    # (Decimal("0") si no aplica margen_op).
    out.append(_kpi("productividad_por_empleado", "RRHH", "Productividad por empleado",
        _div(ingresos_ventas, emp_promedio),
        "ingresos / empleados_promedio", "ARS/empleado",
        "ok" if emp_promedio else "faltan",
        falta=None if emp_promedio else "empleados_*"))

    # Accidentabilidad = accidentes / empleados * 1000 (proxy)
    accidentab = _div(accidentes, emp_promedio)
    out.append(_kpi("accidentabilidad", "RRHH", "Índice de accidentabilidad",
        accidentab * 1000 if accidentab is not None else None,
        "accidentes / empleados_promedio * 1000", "‰",
        "ok" if (accidentes is not None and emp_promedio) else "faltan",
        falta=None if (accidentes is not None and emp_promedio) else "accidentes/empleados"))

    out.append(_kpi("antiguedad_promedio", "RRHH", "Antigüedad promedio",
        _to_float(ant) if ant is not None else None,
        "input manual", "años",
        "ok" if ant is not None else "faltan",
        falta=None if ant is not None else "antiguedad_promedio_anios"))

    out.append(_kpi("dias_cobertura_vacante", "RRHH", "Tiempo de cobertura de vacante",
        _to_float(cobertura) if cobertura is not None else None,
        "input manual", "días",
        "ok" if cobertura is not None else "faltan",
        falta=None if cobertura is not None else "dias_cobertura_vacante"))

    # ===== Encuestas (NPS / eNPS / clima / satisfacción) =====
    for codigo, label, area in [
        ("nps", "NPS (clientes)", "Atención"),
        ("enps", "eNPS (empleados)", "RRHH"),
        ("clima_laboral_score", "Clima laboral", "RRHH"),
        ("satisfaccion_post_servicio", "Satisfacción post-servicio", "Atención"),
    ]:
        v = m.get(codigo)
        out.append(_kpi(codigo, area, label,
            _to_float(v) if v is not None else None,
            "input encuesta", "score",
            "ok" if v is not None else "faltan",
            falta=None if v is not None else codigo))

    # ===== Marketing =====
    gasto_mkt = m.get("gasto_marketing")
    leads = m.get("leads_generados")
    trafico = m.get("trafico_web")
    alcance = m.get("alcance_campanas")

    # Clientes nuevos: query costoso, computar solo si lo necesitamos.
    NEEDS_CLIENTES = {"cac", "ltv_proxy", "tasa_conversion", "tasa_reclamos"}
    clientes_nuevos_mes = (
        _clientes_nuevos_en_periodo(db, desde, hasta)
        if _aplica_alguno(NEEDS_CLIENTES) else 0
    )

    # CAC = gasto_marketing / clientes_nuevos. Caso especial: si hay
    # gasto pero 0 clientes nuevos, el CAC matemáticamente es ∞ — lo
    # marcamos `parcial` con nota.
    if gasto_mkt is None:
        cac_v, cac_status, cac_falta, cac_nota = None, "faltan", "gasto_marketing", None
    elif clientes_nuevos_mes == 0:
        cac_v, cac_status, cac_falta = None, "parcial", None
        cac_nota = "Hubo gasto en marketing pero 0 clientes nuevos en el mes — CAC indefinido (∞)."
    else:
        cac_v = _div(gasto_mkt, clientes_nuevos_mes)
        cac_status, cac_falta, cac_nota = "ok", None, None
    out.append(_kpi("cac", "Marketing", "CAC (Costo de Adquisición)",
        cac_v, "gasto_marketing / clientes_nuevos", "ARS",
        cac_status, falta=cac_falta, nota=cac_nota))

    # LTV proxy (3 queries adicionales) — solo si lo piden.
    if _aplica("ltv_proxy"):
        # ticket_promedio = ingresos / cantidad_pedidos del mes.
        cant_pedidos = db.query(func.count(Venta.id_pedido)).filter(
            Venta.fecha >= datetime.combine(desde, datetime.min.time()),
            Venta.fecha <= datetime.combine(hasta, datetime.max.time()),
        ).scalar() or 0
        ticket_prom = _div(ingresos_ventas, cant_pedidos)
        total_clientes_mes_ltv = _total_clientes_en_periodo(db, desde, hasta)
        clientes_recurrentes = db.query(func.count(func.distinct(Venta.id_cliente))).filter(
            Venta.id_cliente.isnot(None),
            Venta.fecha >= datetime.combine(desde, datetime.min.time()),
            Venta.fecha <= datetime.combine(hasta, datetime.max.time()),
            Venta.id_cliente.in_(
                db.query(Venta.id_cliente).filter(
                    Venta.fecha < datetime.combine(desde, datetime.min.time()),
                )
            ),
        ).scalar() or 0
        tasa_recompra = _div(clientes_recurrentes, total_clientes_mes_ltv) if total_clientes_mes_ltv else 0
        if ticket_prom and tasa_recompra:
            ltv_proxy = ticket_prom * (tasa_recompra + 1)
        else:
            ltv_proxy = ticket_prom
        out.append(_kpi("ltv_proxy", "Marketing", "LTV (proxy mensual)",
            ltv_proxy,
            "ticket_promedio * (1 + tasa_recompra) — proxy", "ARS",
            "parcial" if ltv_proxy else "faltan",
            falta="sin ventas en el mes" if not ltv_proxy else None,
            nota="Proxy mensual: para LTV preciso falta horizonte de cliente y churn rate."))

    # Costo por lead
    out.append(_kpi("costo_por_lead", "Marketing", "Costo por lead",
        _div(gasto_mkt, leads),
        "gasto_marketing / leads_generados", "ARS",
        "ok" if (gasto_mkt is not None and leads) else "faltan",
        falta=None if (gasto_mkt is not None and leads) else "gasto_marketing/leads"))

    # Tasa de conversión = clientes_nuevos / leads * 100
    out.append(_kpi("tasa_conversion", "Marketing", "Tasa de conversión",
        _pct(clientes_nuevos_mes, leads),
        "clientes_nuevos / leads * 100", "%",
        "ok" if leads else "faltan",
        falta=None if leads else "leads_generados"))

    # ROMI = (ingresos - gasto_mkt) / gasto_mkt * 100. Crudo: asume que
    # TODO el ingreso es atribuible a marketing (sobreestima si parte
    # de las ventas es organic/recurrente).
    if gasto_mkt is not None and gasto_mkt > 0:
        romi = float((ingresos_ventas - gasto_mkt) / gasto_mkt * 100)
    else:
        romi = None
    out.append(_kpi("romi", "Marketing", "ROMI",
        romi,
        "(ingresos - gasto_marketing) / gasto_marketing * 100", "%",
        "parcial" if romi is not None else "faltan",
        falta=None if gasto_mkt else "gasto_marketing",
        nota="Proxy crudo: asume que TODO el ingreso es atribuible a marketing. Para ROMI preciso falta atribución."))

    out.append(_kpi("trafico_web", "Marketing", "Tráfico web",
        _to_float(trafico) if trafico is not None else None,
        "input manual (Google Analytics)", "sesiones",
        "ok" if trafico is not None else "faltan",
        falta=None if trafico is not None else "trafico_web"))

    out.append(_kpi("alcance_campanas", "Marketing", "Alcance de campañas",
        _to_float(alcance) if alcance is not None else None,
        "input manual", "impresiones",
        "ok" if alcance is not None else "faltan",
        falta=None if alcance is not None else "alcance_campanas"))

    # ===== IT / Sistemas =====
    incidentes = m.get("incidentes_it_mes")
    horas_res = m.get("horas_resolucion_total")
    downtime = m.get("horas_downtime")
    usuarios = m.get("usuarios_activos")
    procesos_total = m.get("procesos_total")
    procesos_auto = m.get("procesos_automatizados")

    out.append(_kpi("incidentes_it", "IT", "Cantidad de incidentes",
        _to_float(incidentes) if incidentes is not None else None,
        "input manual", "incidentes",
        "ok" if incidentes is not None else "faltan",
        falta=None if incidentes is not None else "incidentes_it_mes"))

    out.append(_kpi("tiempo_resolucion_promedio", "IT", "Tiempo promedio de resolución",
        _div(horas_res, incidentes),
        "horas_resolucion_total / cantidad_incidentes", "horas",
        "ok" if (horas_res is not None and incidentes is not None and incidentes != 0) else "faltan",
        falta=None if (horas_res is not None and incidentes) else "horas_resolucion_total/incidentes"))

    out.append(_kpi("tiempo_caida", "IT", "Tiempo de caída (downtime)",
        _to_float(downtime) if downtime is not None else None,
        "input manual", "horas",
        "ok" if downtime is not None else "faltan",
        falta=None if downtime is not None else "horas_downtime"))

    out.append(_kpi("usuarios_activos", "IT", "Usuarios activos",
        _to_float(usuarios) if usuarios is not None else None,
        "input manual", "usuarios",
        "ok" if usuarios is not None else "faltan",
        falta=None if usuarios is not None else "usuarios_activos"))

    out.append(_kpi("automatizacion_pct", "IT", "Automatización de procesos %",
        _pct(procesos_auto, procesos_total),
        "procesos_automatizados / procesos_total * 100", "%",
        "ok" if (procesos_total and procesos_auto is not None) else "faltan",
        falta=None if (procesos_total and procesos_auto is not None) else "procesos_total/procesos_automatizados"))

    # ===== Atención al cliente =====
    reclamos = m.get("reclamos_mes")
    reclamos_recurrentes = m.get("reclamos_recurrentes_mes")
    t_resp = m.get("tiempo_respuesta_promedio_horas")
    t_res = m.get("tiempo_resolucion_promedio_horas")

    # Total clientes (query costoso) solo si se necesita (tasa_reclamos).
    total_clientes_mes = (
        _total_clientes_en_periodo(db, desde, hasta)
        if _aplica("tasa_reclamos") else 0
    )
    out.append(_kpi("tasa_reclamos", "Atención", "Tasa de reclamos %",
        _pct(reclamos, total_clientes_mes),
        "reclamos / total_clientes_mes * 100", "%",
        "ok" if (reclamos is not None and total_clientes_mes) else "faltan",
        falta=None if (reclamos is not None and total_clientes_mes) else "reclamos_mes"))

    out.append(_kpi("tiempo_respuesta", "Atención", "Tiempo de respuesta",
        _to_float(t_resp) if t_resp is not None else None,
        "input manual", "horas",
        "ok" if t_resp is not None else "faltan",
        falta=None if t_resp is not None else "tiempo_respuesta_promedio_horas"))

    out.append(_kpi("tiempo_resolucion_clientes", "Atención", "Tiempo de resolución de reclamos",
        _to_float(t_res) if t_res is not None else None,
        "input manual", "horas",
        "ok" if t_res is not None else "faltan",
        falta=None if t_res is not None else "tiempo_resolucion_promedio_horas"))

    # Reclamos recurrentes %: cuánto del total son re-reclamos.
    # Caso especial: si reclamos=0 (con dato cargado), no hay falta de
    # input — simplemente no hubo reclamos. Status=ok con valor=None.
    if reclamos_recurrentes is None or reclamos is None:
        rec_status, rec_falta = "faltan", "reclamos_recurrentes_mes/reclamos_mes"
        rec_valor = None
    elif reclamos == 0:
        rec_status, rec_falta = "ok", None
        rec_valor = None  # sin reclamos no se puede dividir, dato sano
    else:
        rec_status, rec_falta = "ok", None
        rec_valor = _pct(reclamos_recurrentes, reclamos)
    out.append(_kpi("reclamos_recurrentes_pct", "Atención", "Reclamos recurrentes %",
        rec_valor,
        "reclamos_recurrentes / reclamos_mes * 100", "%",
        rec_status, falta=rec_falta))

    # ===== Compras / Inventario =====
    repos = m.get("tiempo_reposicion_dias")
    quiebres = m.get("quiebres_stock")
    stock = m.get("stock_promedio_ars")
    cmv = m.get("costo_mercaderia_vendida_mes")
    out.append(_kpi("tiempo_reposicion", "Compras", "Tiempo promedio de reposición",
        _to_float(repos) if repos is not None else None,
        "input manual", "días",
        "ok" if repos is not None else "faltan",
        falta=None if repos is not None else "tiempo_reposicion_dias"))
    out.append(_kpi("quiebres_stock", "Compras", "Quiebres de stock",
        _to_float(quiebres) if quiebres is not None else None,
        "input manual", "incidentes",
        "ok" if quiebres is not None else "faltan",
        falta=None if quiebres is not None else "quiebres_stock"))
    out.append(_kpi("nivel_stock", "Compras", "Nivel de stock valorizado",
        _to_float(stock) if stock is not None else None,
        "input manual", "ARS",
        "ok" if stock is not None else "faltan",
        falta=None if stock is not None else "stock_promedio_ars"))
    # Rotación = CMV / stock_promedio (veces que rota el inventario en el mes)
    out.append(_kpi("rotacion_inventario", "Compras", "Rotación de inventario",
        _div(cmv, stock),
        "costo_mercaderia_vendida / stock_promedio", "veces",
        "ok" if (cmv and stock) else "faltan",
        falta=None if (cmv and stock) else "stock_promedio_ars/costo_mercaderia_vendida_mes"))

    # ===== Comercial avanzado =====
    leads_calientes = m.get("leads_calientes_actuales")
    leads_cerrados = m.get("leads_cerrados_mes")
    leads_ganados = m.get("leads_ganados_mes")
    ciclo = m.get("ciclo_venta_dias")
    out.append(_kpi("pipeline_oportunidades", "Comercial", "Pipeline (oportunidades vivas)",
        _to_float(leads_calientes) if leads_calientes is not None else None,
        "input manual (cuenta de leads en embudo)", "leads",
        "ok" if leads_calientes is not None else "faltan",
        falta=None if leads_calientes is not None else "leads_calientes_actuales"))
    # Tasa de cierre = ganados / cerrados * 100
    out.append(_kpi("tasa_cierre", "Comercial", "Tasa de cierre %",
        _pct(leads_ganados, leads_cerrados),
        "leads_ganados / leads_cerrados * 100", "%",
        "ok" if (leads_ganados is not None and leads_cerrados) else "faltan",
        falta=None if (leads_ganados is not None and leads_cerrados) else "leads_ganados_mes/leads_cerrados_mes"))
    out.append(_kpi("ciclo_venta", "Comercial", "Ciclo de venta promedio",
        _to_float(ciclo) if ciclo is not None else None,
        "input manual", "días",
        "ok" if ciclo is not None else "faltan",
        falta=None if ciclo is not None else "ciclo_venta_dias"))

    # ===== Operaciones (planta/proceso) =====
    ef_op = m.get("eficiencia_operativa_pct")
    h_inact = m.get("horas_inactividad_mes")
    h_prod = m.get("horas_productivas_mes")
    inc_op = m.get("incidentes_operativos_mes")
    ent_tiempo = m.get("entregas_a_tiempo_mes")
    ent_total = m.get("entregas_total_mes")
    out.append(_kpi("eficiencia_operativa", "Operaciones", "Eficiencia operativa %",
        _to_float(ef_op) if ef_op is not None else None,
        "input manual (output real / máximo)", "%",
        "ok" if ef_op is not None else "faltan",
        falta=None if ef_op is not None else "eficiencia_operativa_pct"))
    out.append(_kpi("inactividad_pct", "Operaciones", "Tiempo de inactividad %",
        _pct(h_inact, h_prod),
        "horas_inactividad / horas_productivas * 100", "%",
        "ok" if (h_inact is not None and h_prod) else "faltan",
        falta=None if (h_inact is not None and h_prod) else "horas_inactividad_mes/horas_productivas_mes"))
    out.append(_kpi("incidentes_operativos", "Operaciones", "Incidentes operativos",
        _to_float(inc_op) if inc_op is not None else None,
        "input manual", "incidentes",
        "ok" if inc_op is not None else "faltan",
        falta=None if inc_op is not None else "incidentes_operativos_mes"))
    out.append(_kpi("entregas_a_tiempo_pct", "Operaciones", "Entregas a tiempo %",
        _pct(ent_tiempo, ent_total),
        "entregas_a_tiempo / entregas_total * 100", "%",
        "ok" if (ent_tiempo is not None and ent_total) else "faltan",
        falta=None if (ent_tiempo is not None and ent_total) else "entregas_a_tiempo_mes/entregas_total_mes"))

    # Filtro final: si se pidió un subset, dejar solo esos. Necesario
    # porque algunos bloques se computan sin guard `_aplica` (cheap RRHH/
    # encuestas/IT). Performance se gana en el guard de las secciones
    # caras (margen, clientes, LTV).
    if solo_codigos is not None:
        out = [k for k in out if k["codigo"] in solo_codigos]

    return {
        "periodo": periodo,
        "kpis": out,
        "resumen": {
            "total": len(out),
            "ok": sum(1 for k in out if k["status"] == "ok"),
            "parcial": sum(1 for k in out if k["status"] == "parcial"),
            "faltan": sum(1 for k in out if k["status"] == "faltan"),
        },
    }


def _periodo_anio_anterior(periodo: str) -> str:
    """YYYY-MM -> YYYY-1 con mismo mes. Asume que el caller ya validó
    el formato; si no, ValueError se propaga arriba con stack claro."""
    if not periodo or len(periodo) != 7 or periodo[4] != "-":
        raise ValueError(f"Período inválido para comparativa: {periodo!r}")
    return f"{int(periodo[:4]) - 1:04d}-{periodo[5:]}"


def kpis_del_mes_con_comparativa(
    db: Session, periodo: str, solo_codigos: set[str] | None = None,
) -> dict[str, Any]:
    """Wrapper de `kpis_del_mes` que agrega `valor_anterior` y `delta_pct`
    contra el mismo mes del año anterior. Útil para que la dueña vea si
    un KPI mejoró o empeoró interanual sin tener que mirar el chart.

    Propaga `solo_codigos` a ambas corridas para que cuando se pida un
    subset (ej. desde `/kpis-manuales`), no corramos los 30 KPIs 2 veces
    sino solo los que se necesitan.
    """
    actual = kpis_del_mes(db, periodo, solo_codigos)
    periodo_ant = _periodo_anio_anterior(periodo)
    anterior = kpis_del_mes(db, periodo_ant, solo_codigos)
    by_codigo_ant = {k["codigo"]: k["valor"] for k in anterior["kpis"]}
    # ¿Tenemos al menos UN dato concreto del año anterior? Si todos son
    # None, los datos pre-2025 fueron purgados o nunca se cargaron — el
    # frontend usa esto para mostrar "(sin datos del año anterior)".
    comparativa_disponible = any(v is not None for v in by_codigo_ant.values())

    # Objetivos cargados (rolling, sin período).
    objetivos = {
        o.codigo: float(o.valor_objetivo)
        for o in db.query(KpiObjetivo).all()
    }

    for k in actual["kpis"]:
        v_ant = by_codigo_ant.get(k["codigo"])
        k["valor_anterior"] = v_ant
        k["periodo_anterior"] = periodo_ant
        if k["valor"] is not None and v_ant is not None and v_ant != 0:
            try:
                k["delta_pct"] = float((Decimal(str(k["valor"])) - Decimal(str(v_ant))) / abs(Decimal(str(v_ant))) * 100)
            except Exception:
                k["delta_pct"] = None
        else:
            k["delta_pct"] = None
        # Objetivo + cumple flag
        obj = objetivos.get(k["codigo"])
        k["objetivo"] = obj
        if obj is None or k["valor"] is None:
            k["cumple_objetivo"] = None
        elif k["mejor_si"] == "bajar":
            k["cumple_objetivo"] = k["valor"] <= obj
        else:
            k["cumple_objetivo"] = k["valor"] >= obj
    actual["comparativa_disponible"] = comparativa_disponible
    return actual


# Lookup constante de metadata por código (label/area/unidad). Lo que
# devuelve `historico_derivado` viene de acá, NO del último KPI de la
# iteración del loop — más robusto si en el futuro se cambian labels.
_META: dict[str, dict] = {
    # Dirección / Finanzas
    "margen_neto": {"label": "Margen neto del período", "area": "Dirección", "unidad": "ARS"},
    "margen_neto_pct": {"label": "Margen neto %", "area": "Dirección", "unidad": "%"},
    "margen_operativo": {"label": "Margen operativo", "area": "Dirección", "unidad": "ARS"},
    "ebitda": {"label": "EBITDA (aprox)", "area": "Dirección", "unidad": "ARS"},
    "roi": {"label": "ROI", "area": "Dirección", "unidad": "%"},
    "roa": {"label": "ROA (retorno sobre activos)", "area": "Dirección", "unidad": "%"},
    "roe": {"label": "ROE (retorno sobre patrimonio)", "area": "Dirección", "unidad": "%"},
    "liquidez_corriente": {"label": "Liquidez corriente", "area": "Finanzas", "unidad": "ratio"},
    "endeudamiento": {"label": "Endeudamiento", "area": "Finanzas", "unidad": "%"},
    "capital_trabajo": {"label": "Capital de trabajo", "area": "Finanzas", "unidad": "ARS"},
    # RRHH
    "rotacion": {"label": "Rotación de personal %", "area": "RRHH", "unidad": "%"},
    "ausentismo": {"label": "Ausentismo %", "area": "RRHH", "unidad": "%"},
    "productividad_por_empleado": {"label": "Productividad por empleado", "area": "RRHH", "unidad": "ARS/empleado"},
    "accidentabilidad": {"label": "Índice de accidentabilidad", "area": "RRHH", "unidad": "‰"},
    "antiguedad_promedio": {"label": "Antigüedad promedio", "area": "RRHH", "unidad": "años"},
    "dias_cobertura_vacante": {"label": "Tiempo de cobertura de vacante", "area": "RRHH", "unidad": "días"},
    # Encuestas
    "nps": {"label": "NPS (clientes)", "area": "Atención", "unidad": "score"},
    "enps": {"label": "eNPS (empleados)", "area": "RRHH", "unidad": "score"},
    "clima_laboral_score": {"label": "Clima laboral", "area": "RRHH", "unidad": "score"},
    "satisfaccion_post_servicio": {"label": "Satisfacción post-servicio", "area": "Atención", "unidad": "score"},
    # Marketing
    "cac": {"label": "CAC (Costo de Adquisición)", "area": "Marketing", "unidad": "ARS"},
    "ltv_proxy": {"label": "LTV (proxy mensual)", "area": "Marketing", "unidad": "ARS"},
    "costo_por_lead": {"label": "Costo por lead", "area": "Marketing", "unidad": "ARS"},
    "tasa_conversion": {"label": "Tasa de conversión", "area": "Marketing", "unidad": "%"},
    "romi": {"label": "ROMI", "area": "Marketing", "unidad": "%"},
    "trafico_web": {"label": "Tráfico web", "area": "Marketing", "unidad": "sesiones"},
    "alcance_campanas": {"label": "Alcance de campañas", "area": "Marketing", "unidad": "impresiones"},
    # IT
    "incidentes_it": {"label": "Cantidad de incidentes", "area": "IT", "unidad": "incidentes"},
    "tiempo_resolucion_promedio": {"label": "Tiempo promedio de resolución", "area": "IT", "unidad": "horas"},
    "tiempo_caida": {"label": "Tiempo de caída (downtime)", "area": "IT", "unidad": "horas"},
    "usuarios_activos": {"label": "Usuarios activos", "area": "IT", "unidad": "usuarios"},
    "automatizacion_pct": {"label": "Automatización de procesos %", "area": "IT", "unidad": "%"},
    # Atención
    "tasa_reclamos": {"label": "Tasa de reclamos %", "area": "Atención", "unidad": "%"},
    "tiempo_respuesta": {"label": "Tiempo de respuesta", "area": "Atención", "unidad": "horas"},
    "tiempo_resolucion_clientes": {"label": "Tiempo de resolución de reclamos", "area": "Atención", "unidad": "horas"},
    "reclamos_recurrentes_pct": {"label": "Reclamos recurrentes %", "area": "Atención", "unidad": "%"},
    # Compras
    "tiempo_reposicion": {"label": "Tiempo promedio de reposición", "area": "Compras", "unidad": "días"},
    "quiebres_stock": {"label": "Quiebres de stock", "area": "Compras", "unidad": "incidentes"},
    "nivel_stock": {"label": "Nivel de stock valorizado", "area": "Compras", "unidad": "ARS"},
    "rotacion_inventario": {"label": "Rotación de inventario", "area": "Compras", "unidad": "veces"},
    # Comercial avanzado
    "pipeline_oportunidades": {"label": "Pipeline (oportunidades vivas)", "area": "Comercial", "unidad": "leads"},
    "tasa_cierre": {"label": "Tasa de cierre %", "area": "Comercial", "unidad": "%"},
    "ciclo_venta": {"label": "Ciclo de venta promedio", "area": "Comercial", "unidad": "días"},
    # Operaciones
    "eficiencia_operativa": {"label": "Eficiencia operativa %", "area": "Operaciones", "unidad": "%"},
    "inactividad_pct": {"label": "Tiempo de inactividad %", "area": "Operaciones", "unidad": "%"},
    "incidentes_operativos": {"label": "Incidentes operativos", "area": "Operaciones", "unidad": "incidentes"},
    "entregas_a_tiempo_pct": {"label": "Entregas a tiempo %", "area": "Operaciones", "unidad": "%"},
}


def metadata(codigo: str) -> dict | None:
    """Devuelve {label, area, unidad} de un código, None si no existe."""
    return _META.get(codigo)


def todos_los_codigos() -> list[tuple[str, dict]]:
    """API pública para iterar el catálogo de KPIs derivados sin
    importar `_META` (privado). Devuelve [(codigo, {label, area, unidad}), ...]."""
    return list(_META.items())


# Rangos duros para validar `valor_objetivo` cuando se carga un target.
# SOLO los KPIs con techo matemático real — para KPIs ARS/ratio/% que
# pueden exceder 100 (margen, rotación extrema), NO ponemos cota
# para no bloquear targets aspiracionales. Decisión de jurado adversarial.
_RANGOS_OBJETIVO: dict[str, tuple[float | None, float | None]] = {
    "nps": (-100, 100),
    "enps": (-100, 100),
    "clima_laboral_score": (1, 10),
    "satisfaccion_post_servicio": (1, 10),
    "automatizacion_pct": (0, 100),
    # Tasas que no pueden ser negativas pero sin techo (devolución/reclamos
    # podría ser >100% en casos raros — no acotar).
    "rotacion": (0, None),
    "ausentismo": (0, None),
    "tasa_reclamos": (0, None),
    "reclamos_recurrentes_pct": (0, 100),
    "tasa_conversion": (0, None),
    "tasa_cierre": (0, 100),
    "eficiencia_operativa": (0, 100),
    "inactividad_pct": (0, 100),
    "entregas_a_tiempo_pct": (0, 100),
    # Conteos y duraciones — solo lower bound 0
    "ciclo_venta": (0, None),
    "incidentes_operativos": (0, None),
    "accidentabilidad": (0, None),
    # Tiempos no pueden ser negativos
    "tiempo_respuesta": (0, None),
    "tiempo_resolucion_clientes": (0, None),
    "tiempo_resolucion_promedio": (0, None),
    "tiempo_caida": (0, None),
    "tiempo_reposicion": (0, None),
    "dias_cobertura_vacante": (0, None),
    # Conteos
    "incidentes_it": (0, None),
    "quiebres_stock": (0, None),
    "usuarios_activos": (0, None),
    "antiguedad_promedio": (0, None),
}


def rango_objetivo(codigo: str) -> tuple[float | None, float | None]:
    """Devuelve (min, max) para validar valor_objetivo. None significa
    sin cota en ese lado. KPIs no listados → (None, None) — sin validación."""
    return _RANGOS_OBJETIVO.get(codigo, (None, None))


# KPIs donde "menos es mejor": rotación alta es mala, ausentismo alto
# es malo, etc. El frontend usa esto para colorear delta interanual
# (verde si baja un KPI de "menos es mejor"). Centralizado acá para
# que el backend sea single source of truth — agregar un KPI nuevo
# acá actualiza el frontend automáticamente.
MENOS_ES_MEJOR: set[str] = {
    "rotacion", "ausentismo", "accidentabilidad",
    "tasa_reclamos", "reclamos_recurrentes_pct",
    "tiempo_respuesta", "tiempo_resolucion_clientes",
    "tiempo_resolucion_promedio", "tiempo_caida", "tiempo_reposicion",
    "quiebres_stock", "endeudamiento", "costo_por_lead",
    "incidentes_it", "dias_cobertura_vacante",
    # Operaciones / Comercial avanzado
    "inactividad_pct", "incidentes_operativos", "ciclo_venta",
}


def mejor_si(codigo: str) -> str:
    """Devuelve "bajar" si el KPI mejora cuando baja, "subir" en caso
    contrario. Sirve al frontend para colorear delta correctamente."""
    return "bajar" if codigo in MENOS_ES_MEJOR else "subir"


def _clientes_nuevos_en_periodo(db: Session, desde: date, hasta: date) -> int:
    """Clientes que tienen su PRIMERA venta en el período."""
    sub = db.query(
        Venta.id_cliente,
        func.min(Venta.fecha).label("primera"),
    ).filter(Venta.id_cliente.isnot(None)).group_by(Venta.id_cliente).subquery()

    # primera fecha dentro del rango (desde inicio día, hasta fin día).
    from datetime import datetime
    desde_dt = datetime.combine(desde, datetime.min.time())
    hasta_dt = datetime.combine(hasta, datetime.max.time())

    return db.query(sub.c.id_cliente).filter(
        and_(sub.c.primera >= desde_dt, sub.c.primera <= hasta_dt)
    ).count()


def _total_clientes_en_periodo(db: Session, desde: date, hasta: date) -> int:
    """Clientes únicos con al menos una venta en el período."""
    from datetime import datetime
    desde_dt = datetime.combine(desde, datetime.min.time())
    hasta_dt = datetime.combine(hasta, datetime.max.time())
    return db.query(func.count(func.distinct(Venta.id_cliente))).filter(
        Venta.id_cliente.isnot(None),
        Venta.fecha >= desde_dt,
        Venta.fecha <= hasta_dt,
    ).scalar() or 0
