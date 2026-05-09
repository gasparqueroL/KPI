from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Crea las tablas si no existen. NO toca datos."""
    import app.models  # noqa: F401  registra modelos en Base.metadata

    Base.metadata.create_all(bind=engine)


def seed_defaults() -> int:
    """Aplica familias por defecto a categorías sin clasificar.

    Idempotente: solo toca filas con `familia IS NULL`. Devuelve el
    número de categorías actualizadas para evitar commits innecesarios.
    """
    from app.importers.categorias_seed import aplicar_defaults

    db = SessionLocal()
    try:
        return aplicar_defaults(db)
    finally:
        db.close()
