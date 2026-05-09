"""Tests del seed de categorías — no debe sobrescribir ediciones manuales."""
from app.importers.categorias_seed import aplicar_defaults
from app.models.categoria_caja import CategoriaCaja


def test_no_sobrescribe_ediciones_de_usuario(db):
    """Si el usuario configuró manualmente, el seed NO debe modificar nada
    (familia, ni ningún flag), incluso si los defaults dirían otra cosa."""
    db.add(CategoriaCaja(
        tipo_operacion="Ingreso",
        familia="Operaciones especiales",
        es_ingreso_operativo=False,  # usuario lo apagó
        es_transferencia=True,        # usuario lo prendió (default sería False)
        es_retiro=True,               # usuario lo prendió
        excluir_flujo=True,           # usuario lo prendió
    ))
    db.commit()

    aplicar_defaults(db)

    cat = db.get(CategoriaCaja, "Ingreso")
    assert cat.familia == "Operaciones especiales"
    assert cat.es_ingreso_operativo is False, "el seed sobreescribió es_ingreso_operativo"
    assert cat.es_transferencia is True, "el seed pisó es_transferencia"
    assert cat.es_retiro is True, "el seed pisó es_retiro"
    assert cat.excluir_flujo is True, "el seed pisó excluir_flujo"


def test_aplica_defaults_a_categorias_sin_familia(db):
    """Categorías recién detectadas (sin familia) sí reciben los defaults."""
    db.add(CategoriaCaja(tipo_operacion="Materia Prima", familia=None))
    db.add(CategoriaCaja(tipo_operacion="Ingreso", familia=None))
    db.commit()

    n = aplicar_defaults(db)
    assert n == 2, f"deberían actualizarse 2 categorías, fueron {n}"

    mp = db.get(CategoriaCaja, "Materia Prima")
    ing = db.get(CategoriaCaja, "Ingreso")
    assert mp.familia == "Costo mercadería"
    assert ing.familia == "Operaciones especiales"
    assert ing.es_ingreso_operativo is True
