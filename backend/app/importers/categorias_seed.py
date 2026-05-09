"""Seed de familia/flags por defecto para categorías de caja conocidas.

Se aplica al startup: para cada categoría ya en BD que NO tenga familia
asignada, se le pone la default. NO sobreescribe ediciones manuales.
"""

from sqlalchemy.orm import Session

from app.models.categoria_caja import CategoriaCaja

DEFAULTS = {
    # Costo mercadería
    "Materia Prima": ("Costo mercadería", {}),
    "Botellas": ("Costo mercadería", {}),
    "Envases": ("Costo mercadería", {}),
    "Bolsas": ("Costo mercadería", {}),
    "Embalaje": ("Costo mercadería", {}),
    "Local": ("Costo mercadería", {}),
    "Insumos Produccion": ("Costo mercadería", {}),
    "Gondola": ("Costo mercadería", {}),
    # Logística
    "Envios": ("Logística / Envíos", {}),
    "Cadeteria": ("Logística / Envíos", {}),
    "Andreani F.": ("Logística / Envíos", {}),
    "Transportista": ("Logística / Envíos", {}),
    "Nafta": ("Logística / Envíos", {}),
    "Camioneta": ("Logística / Envíos", {}),
    "Movilidad Urbana": ("Logística / Envíos", {}),
    "Uber/Taxi/Remis": ("Logística / Envíos", {}),
    # Personal
    "Sueldo": ("Personal", {}),
    "Empleados": ("Personal", {}),
    "Adelanto": ("Personal", {}),
    "Comida Empleados": ("Personal", {}),
    "Uniforme": ("Personal", {}),
    "Indeminización": ("Personal", {}),
    "ADELANTO GERENCIA": ("Personal", {"es_retiro": True}),
    # Gastos fijos
    "Monotributo": ("Gastos fijos", {}),
    "Impuestos": ("Gastos fijos", {}),
    "Oficina": ("Gastos fijos", {}),
    "Software": ("Gastos fijos", {}),
    "Gasto FIJO": ("Gastos fijos", {}),
    # Gastos operativos
    "Insumos Oficina": ("Gastos operativos", {}),
    "Insumos Taller": ("Gastos operativos", {}),
    "Comida Negocio": ("Gastos operativos", {}),
    "Limpieza": ("Gastos operativos", {}),
    "Kiosko": ("Gastos operativos", {}),
    "Gasto Operativo": ("Gastos operativos", {}),
    # Marketing
    "Publicidad": ("Marketing", {}),
    "Cursos": ("Marketing", {}),
    # Inversión
    "Inversion": ("Inversión / Capex", {}),
    "Herramientas/Maquinas": ("Inversión / Capex", {}),
    "Electronica": ("Inversión / Capex", {}),
    "Construccion": ("Inversión / Capex", {}),
    "Elementos de Seguridad": ("Inversión / Capex", {}),
    # Salud
    "Gasto Medico": ("Salud", {}),
    "Insumos medicos": ("Salud", {}),
    "Reparación": ("Salud", {}),
    # Ajustes
    "Cagadas": ("Ajustes / Pérdidas", {}),
    "Devoluciones": ("Ajustes / Pérdidas", {}),
    # Operaciones especiales (con flags)
    "Balance": ("Operaciones especiales", {"es_transferencia": True}),
    "Retiro de Dinero": ("Operaciones especiales", {"es_retiro": True}),
    "Ingreso": ("Operaciones especiales", {}),
    "Buenos Aires": ("Operaciones especiales", {"excluir_flujo": True}),
    "Buenos Aires Local": ("Operaciones especiales", {"excluir_flujo": True}),
    "Cajas": ("Operaciones especiales", {"es_transferencia": True}),
    "LEGALES": ("Gastos fijos", {}),
    # Cobranzas posteriores de cuenta corriente — son ingreso comercial
    "Ingreso": ("Operaciones especiales", {"es_ingreso_operativo": True}),
    "paga cuenta corriente": ("Operaciones especiales", {"es_ingreso_operativo": True}),
}


def aplicar_defaults(db: Session) -> int:
    """Para cada categoría SIN familia, aplica el default si existe.
    Devuelve el número de categorías actualizadas.

    Ediciones manuales (categorías con familia ya asignada) NO se tocan,
    incluso si los flags difieren de los defaults — el usuario es la
    autoridad sobre lo que ya configuró.
    """
    actualizadas = 0
    sin_fam = db.query(CategoriaCaja).filter(CategoriaCaja.familia.is_(None)).all()
    for cat in sin_fam:
        if cat.tipo_operacion in DEFAULTS:
            familia, flags = DEFAULTS[cat.tipo_operacion]
            cat.familia = familia
            for k, v in flags.items():
                setattr(cat, k, v)
            actualizadas += 1
    if actualizadas:
        db.commit()
    return actualizadas
