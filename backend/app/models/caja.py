from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, String

from app.db import Base


class Caja(Base):
    """Entidad central: cada 'forma de pago' o 'caja' donde vive el dinero.

    `nombre_normalizado` es la PK (lowercase, sin espacios) para tolerar
    variantes de escritura. `nombre_display` conserva la versión legible.

    Dos flags con semánticas distintas conviven y NO son intercambiables:
      - `activa` (Boolean): "no usar para nuevas altas/movs" (form de
        nuevo movimiento la oculta) — semántica de catálogo. La caja
        sigue apareciendo en saldos, listados, alertas.
      - `archivado_at` (DateTime nullable): "ocultar de la vista por
        default" — soft delete reversible. Saldos, alertas y dropdowns
        la excluyen. Las queries productivas filtran `archivado_at IS
        NULL`. Movimientos hacia/desde la caja archivada SIGUEN sumando
        a la otra punta (transferencias).

    Una caja puede ser `activa=False, archivado_at=NULL` (visible en
    saldos pero no en altas) o `archivado_at=NOT NULL` (oculta de todo).
    """

    __tablename__ = "cajas"

    nombre_normalizado = Column(String, primary_key=True)
    nombre_display = Column(String, nullable=False)
    tipo = Column(String, nullable=False, default="operativa")
    activa = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    archivado_at = Column(DateTime, nullable=True, index=True)

    @staticmethod
    def normalizar(nombre: str) -> str:
        if not nombre:
            return ""
        return "".join(nombre.strip().lower().split())
