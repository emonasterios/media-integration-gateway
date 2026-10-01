"""Punto de entrada del Media Integration Gateway."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from src.adapters.cuevana3 import Cuevana3Adapter
from src.api.routes import router
from src.core.config import settings
from src.services.catalog import CatalogService

# Instancia global del servicio (se reemplaza en tests)
catalog_service: CatalogService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Inicializa adapters y servicios al arrancar."""
    global catalog_service
    adapter = Cuevana3Adapter()
    catalog_service = CatalogService(providers=[adapter])
    # Registrar en el router para Depends
    from src.api.routes import _get_catalog

    app.dependency_overrides[_get_catalog] = lambda: catalog_service
    yield
    await adapter.close()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/healthz")
async def health():
    return {"status": "ok"}
