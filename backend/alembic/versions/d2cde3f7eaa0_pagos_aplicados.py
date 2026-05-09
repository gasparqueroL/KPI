"""pagos_aplicados

Revision ID: d2cde3f7eaa0
Revises: 804731e3a11c
Create Date: 2026-05-03 11:12:32.615911

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2cde3f7eaa0'
down_revision: Union[str, Sequence[str], None] = '804731e3a11c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'pagos_aplicados',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('id_venta', sa.String(), nullable=False),
        sa.Column('id_movimiento', sa.Integer(), nullable=False),
        sa.Column('monto', sa.Numeric(14, 2), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['id_movimiento'], ['movimientos_caja.id'], ),
        sa.ForeignKeyConstraint(['id_venta'], ['ventas.id_pedido'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('id_venta', 'id_movimiento', name='uq_pago_aplicado'),
    )
    op.create_index(
        'ix_pagos_aplicados_id_venta', 'pagos_aplicados', ['id_venta'], unique=False
    )
    op.create_index(
        'ix_pagos_aplicados_id_movimiento', 'pagos_aplicados', ['id_movimiento'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_pagos_aplicados_id_movimiento', table_name='pagos_aplicados')
    op.drop_index('ix_pagos_aplicados_id_venta', table_name='pagos_aplicados')
    op.drop_table('pagos_aplicados')
