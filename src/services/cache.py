"""Servicio de caché con TTL configurable."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from src.core.config import settings
from src.db.models import Media, Source


class CatalogCache:
    """Caché de catálogo con TTL configurable usando la base de datos."""

    def __init__(self, db: Session, ttl_seconds: int = settings.CACHE_TTL_SECONDS) -> None:
        self.db = db
        self.ttl_seconds = ttl_seconds

    def get_media(self, title: str, media_type: Optional[str] = None) -> Optional[Media]:
        """Busca en la tabla media. Si existe y no ha expirado, retorna la entidad con sus sources."""
        query = self.db.query(Media).filter(Media.title == title)
        if media_type:
            query = query.filter(Media.media_type == media_type)
        media = query.first()

        if media is None:
            return None

        if not self.is_valid(media):
            return None

        # Cargar sources explícitamente
        _ = media.sources
        return media

    def get_by_source(self, provider: str, provider_id: str) -> Optional[Media]:
        """Busca por la fuente (proveedor + id del proveedor), que es lo que conoce quien consulta."""
        provider_name = provider.name if hasattr(provider, "name") else str(provider)
        if ":" in provider_id:
            provider_id = provider_id.split(":", 1)[1]
        media = (
            self.db.query(Media)
            .join(Source, Source.media_id == Media.id)
            .filter(Source.provider == provider_name, Source.url == provider_id)
            .first()
        )
        if media is None or not self.is_valid(media):
            return None
        _ = media.sources
        return media

    def save_media(self, item_data: dict, sources_data: list[dict]) -> Media:
        """Crea o actualiza el registro en Media con updated_at = datetime.utcnow(),
        sincroniza las sources asociadas y persiste con commit."""
        title = item_data.get("title")
        media_type = item_data.get("media_type")

        # Buscar existente
        existing = self.db.query(Media).filter(Media.title == title)
        if media_type:
            existing = existing.filter(Media.media_type == media_type)
        existing = existing.first()

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
            self.db.flush()  # Para obtener el ID

        # Sincronizar sources: borrar las antiguas y crear las nuevas
        self.db.query(Source).filter(Source.media_id == media.id).delete()
        for src in sources_data:
            source = Source(media_id=media.id, **src)
            self.db.add(source)

        self.db.commit()
        self.db.refresh(media)
        return media

    def is_valid(self, media: Media) -> bool:
        """Verifica si datetime.utcnow() - media.updated_at <= timedelta(seconds=self.ttl_seconds)."""
        if media.updated_at is None:
            return False
        return datetime.utcnow() - media.updated_at <= timedelta(seconds=self.ttl_seconds)