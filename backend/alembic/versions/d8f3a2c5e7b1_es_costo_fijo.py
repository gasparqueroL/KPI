"""categorias_caja: agregar columna es_costo_fijo

Revision ID: d8f3a2c5e7b1
Revises: c7e5b8d3f9a2
Create Date: 2026-05-08 21:30:00.000000

Habilita el cálculo de punto de equilibrio: clasificar categorías de
gasto en fijos (alquileres, sueldos) vs variables (mercadería, envíos).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd8f3a2c5e7b1'
down_revision: Union[str, Sequence[str], None] = 'c7e5b8d3f9a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'categorias_caja',
        sa.Column('es_costo_fijo', sa.Boolean(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('categorias_caja', 'es_costo_fijo')
