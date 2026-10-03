"""Punto de entrada del Media Integration Gateway."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import FastAPI

from src.adapters.cuevana3 import Cuevana3Adapter
from src.adapters.cuevan_net import CuevanNetAdapter
from src.api.routes import router
from src.api.m3u import router as m3u_router
from src.api.xtream import router as xtream_router
from src.core.config import settings
from src.db.database import AsyncSessionLocal
from src.services.catalog import CatalogService
from src.services.cache import CatalogCache


def _build_app() -> FastAPI:
    """Construye la app sin lifespan (para tests)."""
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
    )
    app.include_router(router)
    app.include_router(m3u_router)
    app.include_router(xtream_router)

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    return app


def create_app(override_catalog: Optional[CatalogService] = None) -> FastAPI:
    """Factory para crear la app, permite inyectar un catálogo fake en tests."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if override_catalog is not None:
            from src.api.routes import _get_catalog
            from src.api.xtream import _get_catalog_service as _xtream_get_catalog
            app.dependency_overrides[_get_catalog] = lambda: override_catalog
            app.dependency_overrides[_xtream_get_catalog] = lambda: override_catalog
            yield
        else:
            from src.db.database import AsyncSessionLocal, init_db
            from src.services.cache import CatalogCache
            await init_db()
            db = AsyncSessionLocal()
            adapter = Cuevana3Adapter()
            cuevan_net = CuevanNetAdapter()
            catalog = CatalogService(providers=[adapter, cuevan_net], cache=CatalogCache(db))
            from src.api.routes import _get_catalog
            from src.api.xtream import _get_catalog_service as _xtream_get_catalog
            app.dependency_overrides[_get_catalog] = lambda: catalog
            app.dependency_overrides[_xtream_get_catalog] = lambda: catalog
            yield
            await adapter.close()
            await cuevan_net.close()
            await db.close()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(router)
    app.include_router(m3u_router)
    app.include_router(xtream_router)

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    return app


# Instancia por defecto para producción
app = create_app()
