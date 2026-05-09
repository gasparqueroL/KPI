from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.db import Base


class CasoRevisar(Base):
    """Filas que no pasaron las reglas de validación durante la importación.

    No contaminan los KPIs hasta que el usuario las corrige o descarta.
    """

    __tablename__ = "casos_revisar"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fuente = Column(String, nullable=False, index=True)
    motivo_codigo = Column(String, nullable=False, index=True)
    motivo_descripcion = Column(String, nullable=False)
    datos_originales = Column(Text, nullable=False)
    estado = Column(String, nullable=False, default="pendiente", index=True)
    correccion = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    archivado_at = Column(DateTime, nullable=True, index=True)
