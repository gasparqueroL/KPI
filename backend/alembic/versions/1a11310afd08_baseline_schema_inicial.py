"""baseline_schema_inicial

Revision ID: 1a11310afd08
Revises: 
Create Date: 2026-05-02 05:49:04.590509

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a11310afd08'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Schema baseline.

    Antes era no-op porque la app llama `init_db()` (`Base.metadata.create_all`)
    en startup, y las migraciones siguientes son solo ALTER. Ahora delegamos
    al mismo helper para que `alembic upgrade head` sobre BD vacía sea
    self-sufficient — caso típico en CI o deploy fresh sin haber arrancado
    la app antes.

    Idempotencia: ESTA revisión usa `create_all` (idempotente — usa
    CREATE TABLE IF NOT EXISTS). PERO la cadena completa NO es 100%
    idempotente: las migraciones siguientes hacen `ALTER TABLE ADD COLUMN`
    sobre columnas que `init_db()` ya creó del modelo actualizado, y
    SQLite tira error en columnas duplicadas. Workflow seguro:
    - Deploy fresh: `alembic upgrade head` (NO arrancar app antes).
    - Deploy con app ya corrida: `alembic stamp head` + reiniciar.
    """
    bind = op.get_bind()
    # Importar models registra todos los Base.metadata.tables.
    import app.models  # noqa: F401
    from app.db import Base
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """Drop ALL tables. Destructivo — usar solo en dev/test."""
    bind = op.get_bind()
    import app.models  # noqa: F401
    from app.db import Base
    Base.metadata.drop_all(bind=bind)
