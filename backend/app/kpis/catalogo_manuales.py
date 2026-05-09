"""Catálogo de códigos de KPIs manuales: define qué se carga, en qué área,
con qué label y unidad. El frontend consume esto para armar el form
dinámicamente — agregar un dato nuevo se hace acá, no en JSX.

Campos opcionales por entrada:
- `min_valor` / `max_valor`: rango válido (excluye negativos para conteos,
  acota score 1-10, NPS -100/+100, etc.). Se valida en el router.
- `descripcion`: hint explicativo para la dueña.
"""

# Cada entrada: codigo, area, label, unidad, [min_valor, max_valor, descripcion]
CATALOGO: list[dict] = [
    # ===== Balance contable (input directo, requeridos para ROA/ROE/liquidez) =====
    {"codigo": "activos_totales", "area": "Balance",
     "label": "Activos totales", "unidad": "ARS", "min_valor": 0,
     "descripcion": "Suma de activos corrientes + no corrientes al cierre del mes."},
    {"codigo": "activos_corrientes", "area": "Balance",
     "label": "Activos corrientes", "unidad": "ARS", "min_valor": 0,
     "descripcion": "Caja + bancos + CxC + inventario + otros realizables a < 12 meses."},
    {"codigo": "pasivos_totales", "area": "Balance",
     "label": "Pasivos totales", "unidad": "ARS", "min_valor": 0,
     "descripcion": "Suma de pasivos corrientes + no corrientes al cierre."},
    {"codigo": "pasivos_corrientes", "area": "Balance",
     "label": "Pasivos corrientes", "unidad": "ARS", "min_valor": 0,
     "descripcion": "Deudas pagables a < 12 meses (CxP, sueldos, etc.)."},
    {"codigo": "patrimonio_neto", "area": "Balance",
     "label": "Patrimonio neto", "unidad": "ARS",
     "descripcion": "Activos - Pasivos. Puede ser negativo si la empresa está en rojo."},
    {"codigo": "capital_invertido", "area": "Balance",
     "label": "Capital invertido", "unidad": "ARS", "min_valor": 0,
     "descripcion": "Aportes de socios + reinversión (para cálculo de ROI)."},

    # ===== RRHH =====
    {"codigo": "empleados_inicio_mes", "area": "RRHH",
     "label": "Empleados al inicio del mes", "unidad": "personas", "min_valor": 0},
    {"codigo": "empleados_fin_mes", "area": "RRHH",
     "label": "Empleados al fin del mes", "unidad": "personas", "min_valor": 0},
    {"codigo": "altas_mes", "area": "RRHH",
     "label": "Altas del mes", "unidad": "personas", "min_valor": 0},
    {"codigo": "bajas_mes", "area": "RRHH",
     "label": "Bajas del mes", "unidad": "personas", "min_valor": 0},
    {"codigo": "dias_ausencia_total", "area": "RRHH",
     "label": "Días de ausencia (total mes)", "unidad": "días", "min_valor": 0,
     "descripcion": "Suma de días no trabajados por enfermedad/personal/sin goce."},
    {"codigo": "dias_laborables_mes", "area": "RRHH",
     "label": "Días laborables del mes", "unidad": "días", "min_valor": 0,
     "descripcion": "Días hábiles posibles × empleados promedio."},
    {"codigo": "accidentes_mes", "area": "RRHH",
     "label": "Accidentes laborales (mes)", "unidad": "incidentes", "min_valor": 0},
    {"codigo": "antiguedad_promedio_anios", "area": "RRHH",
     "label": "Antigüedad promedio (años)", "unidad": "años", "min_valor": 0},
    {"codigo": "dias_cobertura_vacante", "area": "RRHH",
     "label": "Días promedio de cobertura de vacante", "unidad": "días", "min_valor": 0,
     "descripcion": "Tiempo promedio entre baja y reposición. Cargar 0 si no hubo vacantes."},

    # ===== Encuestas (NPS / eNPS / clima / satisfacción) =====
    {"codigo": "nps", "area": "Encuestas",
     "label": "NPS (Net Promoter Score)", "unidad": "score",
     "min_valor": -100, "max_valor": 100,
     "descripcion": "Resultado de encuesta a clientes (-100 a +100)."},
    {"codigo": "enps", "area": "Encuestas",
     "label": "eNPS (Employee NPS)", "unidad": "score",
     "min_valor": -100, "max_valor": 100,
     "descripcion": "Resultado de encuesta interna a empleados (-100 a +100)."},
    {"codigo": "clima_laboral_score", "area": "Encuestas",
     "label": "Clima laboral (1-10)", "unidad": "score",
     "min_valor": 1, "max_valor": 10},
    {"codigo": "satisfaccion_post_servicio", "area": "Encuestas",
     "label": "Satisfacción post-servicio (1-10)", "unidad": "score",
     "min_valor": 1, "max_valor": 10},

    # ===== Marketing =====
    {"codigo": "gasto_marketing", "area": "Marketing",
     "label": "Gasto en marketing del mes", "unidad": "ARS", "min_valor": 0},
    {"codigo": "leads_generados", "area": "Marketing",
     "label": "Leads generados", "unidad": "leads", "min_valor": 0},
    {"codigo": "trafico_web", "area": "Marketing",
     "label": "Tráfico web (sesiones)", "unidad": "sesiones", "min_valor": 0},
    {"codigo": "alcance_campanas", "area": "Marketing",
     "label": "Alcance de campañas (impresiones)", "unidad": "impresiones", "min_valor": 0},

    # ===== IT / Sistemas =====
    {"codigo": "incidentes_it_mes", "area": "Sistemas/IT",
     "label": "Cantidad de incidentes IT", "unidad": "incidentes", "min_valor": 0},
    {"codigo": "horas_resolucion_total", "area": "Sistemas/IT",
     "label": "Horas totales de resolución de incidentes", "unidad": "horas", "min_valor": 0},
    {"codigo": "horas_downtime", "area": "Sistemas/IT",
     "label": "Horas de caída de sistemas", "unidad": "horas", "min_valor": 0},
    {"codigo": "usuarios_activos", "area": "Sistemas/IT",
     "label": "Usuarios activos del sistema", "unidad": "usuarios", "min_valor": 0},
    {"codigo": "procesos_total", "area": "Sistemas/IT",
     "label": "Total procesos clave del negocio", "unidad": "procesos", "min_valor": 0,
     "descripcion": "Para % de digitalización / automatización."},
    {"codigo": "procesos_automatizados", "area": "Sistemas/IT",
     "label": "Procesos automatizados", "unidad": "procesos", "min_valor": 0},

    # ===== Atención al cliente =====
    {"codigo": "reclamos_mes", "area": "Atención al cliente",
     "label": "Reclamos del mes", "unidad": "reclamos", "min_valor": 0},
    {"codigo": "reclamos_recurrentes_mes", "area": "Atención al cliente",
     "label": "Reclamos recurrentes (mismo cliente, 2+ veces)", "unidad": "reclamos", "min_valor": 0,
     "descripcion": "Cantidad de reclamos provenientes de clientes que YA reclamaron antes este mes."},
    {"codigo": "tiempo_respuesta_promedio_horas", "area": "Atención al cliente",
     "label": "Tiempo de respuesta promedio (horas)", "unidad": "horas", "min_valor": 0},
    {"codigo": "tiempo_resolucion_promedio_horas", "area": "Atención al cliente",
     "label": "Tiempo de resolución promedio (horas)", "unidad": "horas", "min_valor": 0},

    # ===== Operaciones / Logística (si aplican) =====
    {"codigo": "tiempo_reposicion_dias", "area": "Compras",
     "label": "Tiempo promedio de reposición (días)", "unidad": "días", "min_valor": 0},
    {"codigo": "quiebres_stock", "area": "Compras",
     "label": "Cantidad de quiebres de stock", "unidad": "incidentes", "min_valor": 0},
    {"codigo": "stock_promedio_ars", "area": "Compras",
     "label": "Stock promedio (ARS valorizado)", "unidad": "ARS", "min_valor": 0,
     "descripcion": "Inventario valuado al cierre del mes. Habilita cálculo de rotación."},
    {"codigo": "costo_mercaderia_vendida_mes", "area": "Compras",
     "label": "Costo de mercadería vendida (mes)", "unidad": "ARS", "min_valor": 0,
     "descripcion": "Si lo cargás, se computa rotación = CMV/stock_promedio."},

    # ===== Comercial avanzado (manual, requiere CRM o tracking) =====
    {"codigo": "leads_calientes_actuales", "area": "Comercial",
     "label": "Oportunidades en pipeline (cuenta)", "unidad": "leads", "min_valor": 0,
     "descripcion": "Total de leads calientes vivos en el embudo (todas las etapas)."},
    {"codigo": "leads_cerrados_mes", "area": "Comercial",
     "label": "Leads cerrados en el mes (ganados o perdidos)", "unidad": "leads", "min_valor": 0},
    {"codigo": "leads_ganados_mes", "area": "Comercial",
     "label": "Leads ganados (cerrados=ventas)", "unidad": "leads", "min_valor": 0},
    {"codigo": "ciclo_venta_dias", "area": "Comercial",
     "label": "Ciclo de venta promedio (días lead → cobro)", "unidad": "días", "min_valor": 0,
     "descripcion": "Tiempo desde primer contacto hasta cobro de la venta."},

    # ===== Operaciones (planta/proceso) =====
    {"codigo": "eficiencia_operativa_pct", "area": "Operaciones",
     "label": "Eficiencia operativa %", "unidad": "%", "min_valor": 0, "max_valor": 100,
     "descripcion": "Output real / output máximo teórico × 100."},
    {"codigo": "horas_inactividad_mes", "area": "Operaciones",
     "label": "Horas de inactividad (planta/equipo)", "unidad": "horas", "min_valor": 0},
    {"codigo": "horas_productivas_mes", "area": "Operaciones",
     "label": "Horas productivas posibles del mes", "unidad": "horas", "min_valor": 0,
     "descripcion": "Para computar % de inactividad."},
    {"codigo": "incidentes_operativos_mes", "area": "Operaciones",
     "label": "Incidentes operativos del mes", "unidad": "incidentes", "min_valor": 0},
    {"codigo": "entregas_a_tiempo_mes", "area": "Operaciones",
     "label": "Entregas a tiempo (cuenta)", "unidad": "entregas", "min_valor": 0},
    {"codigo": "entregas_total_mes", "area": "Operaciones",
     "label": "Entregas totales del mes", "unidad": "entregas", "min_valor": 0},
]


def codigos_validos() -> set[str]:
    return {c["codigo"] for c in CATALOGO}


def por_codigo() -> dict[str, dict]:
    return {c["codigo"]: c for c in CATALOGO}
