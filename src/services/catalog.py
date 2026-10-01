"""Servicios de negocio: catálogo, búsqueda y resolución."""

from __future__ import annotations

from typing import Optional

from src.adapters.base import MediaProvider
from src.models.catalog import (
    Episode,
    MediaItem,
    PlaybackDescriptor,
    Season,
    SearchResult,
)


class CatalogService:
    """Orquesta adapters para búsquedas, catálogo y resolución."""

    def __init__(self, providers: list[MediaProvider]) -> None:
        self._providers = {p.name: p for p in providers}

    @property
    def provider_names(self) -> list[str]:
        return list(self._providers.keys())

    def get_provider(self, name: str) -> MediaProvider:
        if name not in self._providers:
            raise KeyError(f"Proveedor desconocido: {name}. Disponibles: {self.provider_names}")
        return self._providers[name]

    async def search(self, query: str, provider: Optional[str] = None) -> list[SearchResult]:
        """Buscar en uno o todos los proveedores."""
        targets = [self._providers[provider]] if provider else list(self._providers.values())
        results: list[SearchResult] = []
        for p in targets:
            try:
                results.append(await p.search(query))
            except Exception:
                # Proveedor caído: continuar con los demás
                pass
        return results

    async def get_details(self, provider: str, media_id: str) -> MediaItem:
        return await self.get_provider(provider).get_details(media_id)

    async def get_seasons(self, provider: str, media_id: str) -> list[Season]:
        return await self.get_provider(provider).get_seasons(media_id)

    async def get_episodes(
        self, provider: str, media_id: str, season_number: int
    ) -> list[Episode]:
        return await self.get_provider(provider).get_episodes(media_id, season_number)

    async def resolve_playback(self, provider: str, media_id: str) -> PlaybackDescriptor:
        return await self.get_provider(provider).resolve_playback(media_id)

    async def get_catalog(
        self, provider: str, category: Optional[str] = None
    ) -> list[MediaItem]:
        return await self.get_provider(provider).get_catalog(category)
