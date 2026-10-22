"""Servicio de caché con TTL configurable."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.config import settings
from src.db.models import Media, Source


class CatalogCache:
    """Caché de catálogo con TTL configurable usando la base de datos."""

    def __init__(self, db: AsyncSession, ttl_seconds: int = settings.CACHE_TTL_SECONDS) -> None:
        self.db = db
        self.ttl_seconds = ttl_seconds

    async def get_media(self, title: str, media_type: Optional[str] = None) -> Optional[Media]:
        """Busca en la tabla media. Si existe y no ha expirado, retorna la entidad con sus sources."""
        stmt = select(Media).filter(Media.title == title)
        if media_type:
            stmt = stmt.filter(Media.media_type == media_type)
        result = await self.db.execute(stmt)
        media = result.scalar_one_or_none()

        if media is None:
            return None

        if not self.is_valid(media):
            return None

        # Cargar sources explícitamente sin refresh
        stmt = select(Media).options(selectinload(Media.sources)).where(Media.id == media.id)
        result = await self.db.execute(stmt)
        media = result.scalar_one()
        if media.genres and isinstance(media.genres, str):
            media.genres = json.loads(media.genres)
        return media

    async def get_by_source(self, provider: str, provider_id: str) -> Optional[Media]:
        """Busca por la fuente (proveedor + id del proveedor)."""
        provider_name = provider.name if hasattr(provider, "name") else str(provider)
        if ":" in provider_id:
            provider_id = provider_id.split(":", 1)[1]
        stmt = (
            select(Media)
            .options(selectinload(Media.sources))
            .join(Source, Source.media_id == Media.id)
            .filter(Source.provider == provider_name, Source.url == provider_id)
        )
        result = await self.db.execute(stmt)
        media = result.scalar_one_or_none()
        if media is None or not self.is_valid(media):
            return None
        if media.genres and isinstance(media.genres, str):
            media.genres = json.loads(media.genres)
        return media

    async def save_media(self, item_data: dict, sources_data: list[dict] = None) -> Media:
        """Crea o actualiza el registro en Media con updated_at = datetime.utcnow(),
        sincroniza las sources asociadas y persiste con commit."""
        title = item_data.get("title")
        media_type = item_data.get("media_type")

        # Buscar existente
        if "genres" in item_data and isinstance(item_data["genres"], list):
            item_data["genres"] = json.dumps(item_data["genres"])

        # Usar el primer source URL como clave única
        source_url = sources_data[0].get("url") if sources_data else None
        if source_url:
            # JOIN con sources para buscar por URL única con carga impaciente de sources
            stmt = (
                select(Media)
                .options(selectinload(Media.sources))
                .join(Source, Media.id == Source.media_id)
                .where(Source.url == source_url)
            )
        else:
            # Fallback: buscar por title con carga impaciente de sources
            stmt = (
                select(Media)
                .options(selectinload(Media.sources))
                .filter(Media.title == title)
            )
            if media_type:
                stmt = stmt.filter(Media.media_type == media_type)
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()

        now = datetime.utcnow()

        if existing:
            # Actualizar campos
            for key, value in item_data.items():
                if hasattr(existing, key) and key not in ("id", "created_at", "sources"):
                    setattr(existing, key, value)
            existing.updated_at = now
            media = existing
        else:
            # Crear nuevo
            media = Media(**item_data, created_at=now, updated_at=now)
            self.db.add(media)
            await self.db.flush()  # Para obtener el ID

        # Sincronizar sources de forma idempotente: si ya existe una fuente con la
        # combinación (provider, url) para este medio, se actualizan sus campos;
        # en caso contrario se crea una nueva. Evita IntegrityError por duplicados.
        # Las fuentes del medio cuya combinación (provider, url) ya no llega en
        # sources_data se eliminan, manteniendo la sincronización sin duplicados.
        result = await self.db.execute(select(Source).where(Source.media_id == media.id))
        existing_sources = {(s.provider, s.url): s for s in result.scalars().all()}
        incoming_keys = {(src.get("provider"), src.get("url")) for src in sources_data}
        for key, stale in list(existing_sources.items()):
            if key not in incoming_keys:
                await self.db.delete(stale)
                del existing_sources[key]
        for src in sources_data:
            key = (src.get("provider"), src.get("url"))
            existing = existing_sources.get(key)
            if existing is not None:
                for k, v in src.items():
                    if hasattr(existing, k) and k not in ("id", "media_id", "created_at"):
                        setattr(existing, k, v)
            else:
                source = Source(media_id=media.id, **src)
                self.db.add(source)
                existing_sources[key] = source

        # Capturar el ID antes del commit: con expire_on_commit=True (default),
        # acceder a media.id tras el commit dispara MissingGreenlet
        media_id = media.id
        await self.db.commit()
        stmt = select(Media).options(selectinload(Media.sources)).where(Media.id == media_id)
        result = await self.db.execute(stmt)
        media = result.scalar_one_or_none()
        if media is None:
            return await self.db.get(Media, media_id)
        return media

    def is_valid(self, media: Media) -> bool:
        """Verifica si datetime.utcnow() - media.updated_at <= timedelta(seconds=self.ttl_seconds)."""
        if media.updated_at is None:
            return False
        return datetime.utcnow() - media.updated_at <= timedelta(seconds=self.ttl_seconds)
