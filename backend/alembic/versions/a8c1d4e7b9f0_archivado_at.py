"""casos_revisar y cajas: agregar columna archivado_at

Revision ID: a8c1d4e7b9f0
Revises: f3a7b9c8d1e2
Create Date: 2026-05-08 13:30:00.000000

Sistema de archivado soft: filas con archivado_at IS NOT NULL se ocultan
por default en queries productivas. Reversible: setear archivado_at=NULL
desarchiva. Diseño: ver decision en CLAUDE.md (jurado adversarial).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a8c1d4e7b9f0'
down_revision: Union[str, Sequence[str], None] = 'f3a7b9c8d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'casos_revisar',
        sa.Column('archivado_at', sa.DateTime(), nullable=True),
    )
    op.add_column(
        'cajas',
        sa.Column('archivado_at', sa.DateTime(), nullable=True),
    )
    # Indices parciales: aceleran filtros default WHERE archivado_at IS NULL
    # cuando crezcan las tablas con miles de archivados.
    op.create_index(
        'ix_casos_revisar_archivado_at',
        'casos_revisar', ['archivado_at'],
    )
    op.create_index(
        'ix_cajas_archivado_at',
        'cajas', ['archivado_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_cajas_archivado_at', table_name='cajas')
    op.drop_index('ix_casos_revisar_archivado_at', table_name='casos_revisar')
    op.drop_column('cajas', 'archivado_at')
    op.drop_column('casos_revisar', 'archivado_at')
