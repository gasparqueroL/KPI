"""factura_proveedor: agregar columna anulada

Revision ID: f3a7b9c8d1e2
Revises: e1f2a3b4c5d6
Create Date: 2026-05-03 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3a7b9c8d1e2'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'facturas_proveedor',
        sa.Column('anulada', sa.Boolean(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('facturas_proveedor', 'anulada')
