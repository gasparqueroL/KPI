"""kpis_objetivos: tabla de targets por KPI

Revision ID: c7e5b8d3f9a2
Revises: b5d2e9f4a8c1
Create Date: 2026-05-08 17:55:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7e5b8d3f9a2'
down_revision: Union[str, Sequence[str], None] = 'b5d2e9f4a8c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'kpis_objetivos',
        sa.Column('codigo', sa.String(), nullable=False),
        sa.Column('valor_objetivo', sa.Numeric(18, 4), nullable=False),
        sa.Column('nota', sa.String(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('codigo'),
    )


def downgrade() -> None:
    op.drop_table('kpis_objetivos')
