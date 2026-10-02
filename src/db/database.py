"""Configuración de base de datos y sesión."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from src.core.config import settings


Base = declarative_base()

connect_args = (
    {"check_same_thread": False}
    if "sqlite" in settings.DATABASE_URL
    else {}
)

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Generador de sesión de base de datos para dependencia de FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Inicializa la base de datos creando todas las tablas."""
    Base.metadata.create_all(bind=engine)