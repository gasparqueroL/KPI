"""pagos_aplicados: CHECK monto>0 + ondelete CASCADE

Revision ID: e1f2a3b4c5d6
Revises: d2cde3f7eaa0
Create Date: 2026-05-03 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'd2cde3f7eaa0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Refuerza integridad de pagos_aplicados.

    SQLite no soporta ALTER TABLE para agregar CHECK ni cambiar FK,
    así que usamos batch_alter_table que recrea la tabla bajo el capó.
    Postgres/MySQL en el futuro usan ALTER nativo de forma transparente.

    Nota: en SQLite, las FK constraints creadas sin nombre explícito (caso
    típico de DBs creadas con `Base.metadata.create_all()` sin naming
    convention) no son drop-eables por nombre — `drop_constraint` falla.
    Como `recreate='always'` reconstruye la tabla entera desde los modelos
    + las alteraciones declaradas, podemos saltear los drops y solo
    declarar los `create_foreign_key` con `ondelete=CASCADE` — el resultado
    final es el mismo: tabla nueva con FKs correctas + CHECK.
    """
    with op.batch_alter_table('pagos_aplicados', recreate='always') as batch_op:
        batch_op.create_check_constraint(
            'ck_pago_aplicado_monto_pos', 'monto > 0'
        )
        batch_op.create_foreign_key(
            'fk_pagos_aplicados_id_venta_ventas',
            'ventas', ['id_venta'], ['id_pedido'],
            ondelete='CASCADE',
        )
        batch_op.create_foreign_key(
            'fk_pagos_aplicados_id_movimiento_movimientos_caja',
            'movimientos_caja', ['id_movimiento'], ['id'],
            ondelete='CASCADE',
        )


def downgrade() -> None:
    with op.batch_alter_table('pagos_aplicados', recreate='always') as batch_op:
        batch_op.drop_constraint('ck_pago_aplicado_monto_pos', type_='check')
        batch_op.create_foreign_key(
            'fk_pagos_aplicados_id_venta_ventas',
            'ventas', ['id_venta'], ['id_pedido'],
        )
        batch_op.create_foreign_key(
            'fk_pagos_aplicados_id_movimiento_movimientos_caja',
            'movimientos_caja', ['id_movimiento'], ['id'],
        )
