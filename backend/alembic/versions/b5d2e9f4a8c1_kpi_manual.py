"""kpis_manuales: tabla de KPIs cargados manualmente por mes

Revision ID: b5d2e9f4a8c1
Revises: a8c1d4e7b9f0
Create Date: 2026-05-08 14:50:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b5d2e9f4a8c1'
down_revision: Union[str, Sequence[str], None] = 'a8c1d4e7b9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'kpis_manuales',
        sa.Column('periodo', sa.String(), nullable=False),
        sa.Column('codigo', sa.String(), nullable=False),
        sa.Column('valor', sa.Numeric(18, 4), nullable=False),
        sa.Column('nota', sa.String(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('periodo', 'codigo'),
    )
    op.create_index(
        'ix_kpis_manuales_codigo', 'kpis_manuales', ['codigo']
    )


def downgrade() -> None:
    op.drop_index('ix_kpis_manuales_codigo', table_name='kpis_manuales')
    op.drop_table('kpis_manuales')
