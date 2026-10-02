"""Servicio de caché con TTL configurable."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, delete
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
        return media

    async def save_media(self, item_data: dict, sources_data: list[dict]) -> Media:
        """Crea o actualiza el registro en Media con updated_at = datetime.utcnow(),
        sincroniza las sources asociadas y persiste con commit."""
        title = item_data.get("title")
        media_type = item_data.get("media_type")

        # Buscar existente
        stmt = select(Media).filter(Media.title == title)
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

        # Sincronizar sources: borrar las antiguas y crear las nuevas
        await self.db.execute(delete(Source).filter(Source.media_id == media.id))
        for src in sources_data:
            source = Source(media_id=media.id, **src)
            self.db.add(source)

        await self.db.commit()
        # Recargar con sources sin usar refresh (evita MissingGreenlet)
        stmt = select(Media).options(selectinload(Media.sources)).where(Media.id == media.id)
        result = await self.db.execute(stmt)
        media = result.scalar_one()
        return media

    def is_valid(self, media: Media) -> bool:
        """Verifica si datetime.utcnow() - media.updated_at <= timedelta(seconds=self.ttl_seconds)."""
        if media.updated_at is None:
            return False
        return datetime.utcnow() - media.updated_at <= timedelta(seconds=self.ttl_seconds)
