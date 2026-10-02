"""Configuración de base de datos y sesión."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from src.core.config import settings


Base = declarative_base()

connect_args = (
    {"check_same_thread": False}
    if "sqlite" in settings.DATABASE_URL
    else {}
)

# Convert sqlite:/// to sqlite+aiosqlite:/// for async
database_url = settings.DATABASE_URL
if database_url.startswith("sqlite:///") and "aiosqlite" not in database_url:
    database_url = database_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)

engine = create_async_engine(database_url, connect_args=connect_args)

AsyncSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)


async def get_db():
    """Generador de sesión async de base de datos para dependencia de FastAPI."""
    db = AsyncSessionLocal()
    try:
        yield db
    finally:
        await db.close()


async def init_db():
    """Inicializa la base de datos creando todas las tablas."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)