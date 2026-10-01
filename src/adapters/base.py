"""Interfaz base para Provider Adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from src.models.catalog import (
    Episode,
    MediaItem,
    PlaybackDescriptor,
    Season,
    SearchResult,
)


class MediaProvider(ABC):
    """Contrato que todo adapter debe implementar."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre identificador del proveedor (ej: 'cuevana3', 'jellyfin')."""

    @abstractmethod
    async def search(self, query: str) -> SearchResult:
        """Buscar contenido por texto."""

    @abstractmethod
    async def get_details(self, media_id: str) -> MediaItem:
        """Obtener detalles de una película o serie."""

    @abstractmethod
    async def get_seasons(self, media_id: str) -> list[Season]:
        """Obtener temporadas de una serie."""

    @abstractmethod
    async def get_episodes(self, media_id: str, season_number: int) -> list[Episode]:
        """Obtener episodios de una temporada."""

    @abstractmethod
    async def resolve_playback(self, media_id: str) -> PlaybackDescriptor:
        """Resolver la URL de reproducción para un elemento."""

    @abstractmethod
    async def get_catalog(self, category: Optional[str] = None) -> list[MediaItem]:
        """Listar catálogo completo, opcionalmente filtrado por categoría."""
