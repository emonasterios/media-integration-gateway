"""Punto de entrada del Media Integration Gateway."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import FastAPI

from src.adapters.cuevana3 import Cuevana3Adapter
from src.adapters.cuevan_net import CuevanNetAdapter
from src.api.catalog_sync import router as catalog_sync_router
from src.api.routes import router
from src.api.m3u import router as m3u_router
from src.api.xtream import router as xtream_router
from src.api.enrichment import router as enrichment_router
from src.api.enrichment import _enricher as global_enricher
from src.core.config import settings
from src.db.database import AsyncSessionLocal
from src.services.catalog import CatalogService
from src.services.catalog_sync import CatalogSyncService
from src.services.cache import CatalogCache
from src.services.enrichment import CatalogEnricher


def _build_app() -> FastAPI:
    """Construye la app sin lifespan (para tests)."""
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
    )
    app.include_router(router)
    app.include_router(m3u_router)
    app.include_router(xtream_router)
    app.include_router(enrichment_router)
    app.include_router(catalog_sync_router, prefix="/api/v1/catalog-sync", tags=["Catalog Sync"])

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
            # Servicio de sincronización de catálogo: los tests pueden inyectar
            # uno directamente en app.state o una session_factory propia.
            if getattr(app.state, "catalog_sync_service", None) is None:
                session_factory = getattr(app.state, "session_factory", None) or getattr(
                    app.state, "async_session_factory", None
                )
                if session_factory is not None:
                    app.state.catalog_sync_service = CatalogSyncService(
                        session_factory=session_factory
                    )
            if getattr(app.state, "catalog_sync_service", None) is not None:
                await app.state.catalog_sync_service.recover_interrupted_runs()
            yield
            if getattr(app.state, "catalog_sync_service", None) is not None:
                await app.state.catalog_sync_service.shutdown()
        else:
            from src.db.database import AsyncSessionLocal, init_db
            from src.services.cache import CatalogCache
            await init_db()
            db = AsyncSessionLocal()
            adapter = Cuevana3Adapter()
            cuevan_net = CuevanNetAdapter()
            catalog = CatalogService(providers=[adapter, cuevan_net], cache=CatalogCache(db))
            # Wire enricher
            global_enricher.set_providers([adapter, cuevan_net])
            from src.api.routes import _get_catalog
            from src.api.xtream import _get_catalog_service as _xtream_get_catalog
            app.dependency_overrides[_get_catalog] = lambda: catalog
            app.dependency_overrides[_xtream_get_catalog] = lambda: catalog
            # Servicio de control de la sincronización asíncrona del catálogo.
            # Los tests pueden inyectar uno directamente en app.state; si no,
            # se construye sobre la session_factory disponible.
            if getattr(app.state, "catalog_sync_service", None) is None:
                session_factory = getattr(app.state, "session_factory", None) or getattr(
                    app.state, "async_session_factory", None
                )
                if session_factory is None:
                    session_factory = AsyncSessionLocal
                app.state.catalog_sync_service = CatalogSyncService(
                    session_factory=session_factory
                )
            await app.state.catalog_sync_service.recover_interrupted_runs()
            # Warm-up: precargar catálogo en segundo plano para que las categorías
            # estén listas cuando el IPTV las pida
            async def _warmup():
                import logging
                logger = logging.getLogger(__name__)
                for provider in ["cuevana3", "cuevan_net"]:
                    try:
                        items = await catalog.get_catalog(provider)
                        logger.info(f"Warmup {provider}: {len(items)} items en caché")
                    except Exception as e:
                        logger.warning(f"Warmup {provider} falló: {e}")
            import asyncio
            asyncio.create_task(_warmup())
            yield
            if getattr(app.state, "catalog_sync_service", None) is not None:
                await app.state.catalog_sync_service.shutdown()
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
    app.include_router(enrichment_router)
    app.include_router(catalog_sync_router, prefix="/api/v1/catalog-sync", tags=["Catalog Sync"])

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    return app


# Instancia por defecto para producción
app = create_app()
