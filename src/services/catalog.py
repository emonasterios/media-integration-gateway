"""Servicios de negocio: catálogo, búsqueda y resolución."""

from __future__ import annotations

from src.adapters.base import MediaProvider
from src.models.catalog import (
    Episode,
    MediaItem,
    MediaType,
    PlaybackDescriptor,
    SearchResult,
    Season,
)

# Import condicional para evitar dependencia dura si no se usa cache
try:
    from src.db.database import SessionLocal
    from src.services.cache import CatalogCache
    _HAS_CACHE = True
except ImportError:
    CatalogCache = None  # type: ignore
    SessionLocal = None  # type: ignore
    _HAS_CACHE = False


class CatalogService:
    """Orquesta adapters para búsquedas, catálogo y resolución."""

    def __init__(
        self,
        providers: list[MediaProvider],
        cache: CatalogCache | None = None,
    ) -> None:
        self._providers = {p.name: p for p in providers}
        self._cache = cache

    @property
    def provider_names(self) -> list[str]:
        return list(self._providers.keys())

    def get_provider(self, name: str) -> MediaProvider:
        if name not in self._providers:
            raise KeyError(f"Proveedor desconocido: {name}. Disponibles: {self.provider_names}")
        return self._providers[name]

    def _get_media_type_from_provider_id(self, media_id: str) -> MediaType | None:
        """Determina el tipo de medio basado en el provider_id."""
        if media_id.startswith("cuevana3:"):
            slug = media_id.removeprefix("cuevana3:")
            if "/serie/" in slug or "temporada-" in slug or "capitulo-" in slug:
                return MediaType.SERIES
            return MediaType.MOVIE
        return None

    def _convert_db_media_to_item(self, db_media, provider: str) -> MediaItem | None:
        """Convierte un objeto Media de la BD a MediaItem del catálogo."""
        if db_media is None:
            return None
        
        media_type_str = db_media.media_type
        if media_type_str == "movie":
            media_type = MediaType.MOVIE
        elif media_type_str == "series":
            media_type = MediaType.SERIES
        elif media_type_str == "episode":
            media_type = MediaType.EPISODE
        else:
            media_type = MediaType.MOVIE
        
        # Extraer provider_id desde sources
        provider_id = ""
        if db_media.sources:
            # Buscar source que coincida con el provider solicitado
            for src in db_media.sources:
                if src.provider == provider:
                    provider_id = src.url  # usamos URL como provider_id en la BD
                    break
            if not provider_id:
                provider_id = db_media.sources[0].url
        
        return MediaItem(
            media_id=f"{provider}:{provider_id}" if provider_id else f"{provider}:{db_media.id}",
            title=db_media.title,
            media_type=media_type,
            year=db_media.year,
            poster_url=db_media.poster_url,
            overview=db_media.synopsis,
            provider=provider,
            provider_id=provider_id or str(db_media.id),
        )

    async def _get_from_cache(self, provider: str, media_id: str) -> MediaItem | None:
        """Intenta obtener el elemento desde la caché."""
        if not _HAS_CACHE or self._cache is None:
            return None
        
        # Extraer el slug/título del media_id
        # Formato típico: "cuevana3:slug" o similar
        if ":" in media_id:
            slug = media_id.split(":", 1)[1]
        else:
            slug = media_id
        
        # Buscar en caché usando el título (o podríamos usar provider_id)
        media_type = self._get_media_type_from_provider_id(media_id)
        media_type_str = media_type.value if media_type else None
        
        db_media = self._cache.get_media(slug, media_type_str)
        if db_media:
            return self._convert_db_media_to_item(db_media, provider)
        return None

    async def _save_to_cache(self, provider: str, item: MediaItem) -> None:
        """Guarda el elemento en la caché."""
        if not _HAS_CACHE or self._cache is None:
            return
        
        item_data = {
            "title": item.title,
            "original_title": item.title,
            "media_type": item.media_type.value,
            "year": item.year,
            "synopsis": item.overview,
            "poster_url": item.poster_url,
        }
        
        sources_data = [{
            "provider": item.provider,
            "url": item.provider_id,
            "quality": "auto",
            "language": "es",
        }]
        
        self._cache.save_media(item_data, sources_data)

    async def search(self, query: str, provider: str | None = None) -> list[SearchResult]:
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
        # Primero intentar desde caché
        cached = await self._get_from_cache(provider, media_id)
        if cached:
            return cached
        
        # Si no está en caché, obtener del adapter
        item = await self.get_provider(provider).get_details(media_id)
        
        # Guardar en caché para futuras consultas
        await self._save_to_cache(provider, item)
        
        return item

    async def get_seasons(self, provider: str, media_id: str) -> list[Season]:
        return await self.get_provider(provider).get_seasons(media_id)

    async def get_episodes(
        self, provider: str, media_id: str, season_number: int
    ) -> list[Episode]:
        return await self.get_provider(provider).get_episodes(media_id, season_number)

    async def resolve_playback(self, provider: str, media_id: str) -> PlaybackDescriptor:
        return await self.get_provider(provider).resolve_playback(media_id)

    async def get_catalog(
        self, provider: str, category: str | None = None
    ) -> list[MediaItem]:
        # Para get_catalog, no usamos caché por ahora ya que devuelve listas
        # y la lógica de TTL sería más compleja (invalidar toda la lista)
        return await self.get_provider(provider).get_catalog(category)