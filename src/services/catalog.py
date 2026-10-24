"""Servicios de negocio: catálogo, búsqueda y resolución."""

from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import urlsplit, urlunsplit

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
    from src.db.database import AsyncSessionLocal
    from src.db.models import Media, Source
    from src.services.cache import CatalogCache
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    _HAS_CACHE = True
except ImportError:
    CatalogCache = None  # type: ignore
    AsyncSessionLocal = None  # type: ignore
    Media = None  # type: ignore
    Source = None  # type: ignore
    select = None  # type: ignore
    selectinload = None  # type: ignore
    _HAS_CACHE = False


def normalize_catalog_url(url: str | None) -> str | None:
    """Normaliza canónicamente una URL de catálogo.

    Devuelve ``None`` para entradas vacías o ``None``; en otro caso,
    normaliza esquema y netloc a minúsculas, elimina query y fragmento,
    colapsa barras repetidas consecutivas en la ruta y aplica política
    uniforme de barra final (se conserva solo si la ruta es ``/``).
    """
    if not url:
        return None
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = re.sub(r"/{2,}", "/", parts.path)
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


class CatalogService:
    """Orquesta adapters para búsquedas, catálogo y resolución."""

    def __init__(
        self,
        providers: list[MediaProvider],
        cache: CatalogCache | None = None,
        catalog_ttl_seconds: int = 3600,
    ) -> None:
        self._providers = {p.name: p for p in providers}
        self._cache = cache
        self._catalog_ttl_seconds = catalog_ttl_seconds
        self._catalog_cache: dict[tuple[str, str | None], tuple[float, list[MediaItem]]] = {}
        self._catalog_locks: dict[tuple[str, str | None], asyncio.Lock] = {}
        self._db_read_lock = asyncio.Lock()

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
        db_media = await self._cache.get_by_source(provider, media_id)
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
        
        await self._cache.save_media(item_data, sources_data)

    async def _load_catalog_from_db(self, provider: str) -> list[MediaItem]:
        """Lee el snapshot local (SQLite) del proveedor vía sesión de BD. Sin red."""
        if not _HAS_CACHE or self._cache is None:
            return []
        stmt = (
            select(Media)
            .options(selectinload(Media.sources))
            .join(Source, Source.media_id == Media.id)
            .where(Source.provider == provider)
            .order_by(Media.id)
        )
        async with self._db_read_lock:
            try:
                result = await self._cache.db.execute(stmt)
                rows = result.scalars().all()
            except Exception:
                # BD ausente o sin tablas: snapshot vacío, sin rastreo de red.
                return []
        items: list[MediaItem] = []
        seen: set[int] = set()
        for media in rows:
            if media.id in seen:
                continue
            seen.add(media.id)
            item = self._convert_db_media_to_item(media, provider)
            if item is not None:
                items.append(item)
        return items

    async def search(self, query: str, provider: str | None = None) -> list[SearchResult]:
        """Buscar en el snapshot local (BD/memoria), filtrado por título. Sin red."""
        query_lower = query.lower().strip()
        if not query_lower:
            return []
        
        targets = [self._providers[provider]] if provider else list(self._providers.values())
        results: list[SearchResult] = []
        
        for p in targets:
            try:
                # Obtener catálogo completo del proveedor
                catalog = await self.get_catalog(p.name)
                # Filtrar localmente por título
                matched = [
                    item for item in catalog
                    if query_lower in item.title.lower()
                ]
                if matched:
                    results.append(SearchResult(items=matched, total=len(matched), query=query))
            except Exception:
                # Sin red: proveedor caído o desconocido no aporta resultados.
                continue
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
        self, provider: str, category: str | None = None, _allow_stale: bool = False
    ) -> list[MediaItem]:
        # Validar proveedor primero (lanza KeyError si no existe)
        self.get_provider(provider)
        
        key = (provider, category)
        now = time.monotonic()
        cached = self._catalog_cache.get(key)
        if cached is not None and now - cached[0] < self._catalog_ttl_seconds:
            return cached[1]
        if _allow_stale and cached is not None:
            return cached[1]

        lock = self._catalog_locks.setdefault(key, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            cached = self._catalog_cache.get(key)
            if cached is not None and now - cached[0] < self._catalog_ttl_seconds:
                return cached[1]
            if _allow_stale and cached is not None:
                return cached[1]
            if self._cache is not None:
                # Con BD configurada: leer exclusivamente el snapshot SQLite local.
                catalog = await self._load_catalog_from_db(provider)
            else:
                # Sin BD configurada (doubles de prueba con catálogo en memoria):
                # invocar adapter UNA VEZ para poblar la caché en memoria.
                # En producción siempre hay BD; esto evita rastreo de red real.
                provider_obj = self.get_provider(provider)
                catalog = await provider_obj.get_catalog(category)
            self._catalog_cache[key] = (time.monotonic(), catalog)
            return catalog
