"""Modelos SQLAlchemy para la base de datos."""

from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from src.db.database import Base


class Media(Base):
    """Modelo para contenido multimedia."""
    __tablename__ = "media"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    original_title = Column(String, nullable=True)
    media_type = Column(String, nullable=False)
    year = Column(Integer, nullable=True)
    synopsis = Column(Text, nullable=True)
    poster_url = Column(String, nullable=True)
    genres = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sources = relationship("Source", back_populates="media", cascade="all, delete-orphan")


class Source(Base):
    """Modelo para fuentes de contenido multimedia."""
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("provider", "url", name="uq_sources_provider_url"),
    )

    id = Column(Integer, primary_key=True)
    media_id = Column(Integer, ForeignKey("media.id"), nullable=False)
    provider = Column(String, nullable=False)
    url = Column(String, nullable=False)
    page_url = Column(String, nullable=True)
    quality = Column(String, nullable=True)
    language = Column(String, nullable=True)

    media = relationship("Media", back_populates="sources")


class Favorite(Base):
    """Modelo para favoritos de usuario."""
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True)
    media_id = Column(Integer, ForeignKey("media.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    media = relationship("Media")


class History(Base):
    """Modelo para historial de visualización."""
    __tablename__ = "history"

    id = Column(Integer, primary_key=True)
    media_id = Column(Integer, ForeignKey("media.id"), nullable=False)
    viewed_at = Column(DateTime, default=datetime.utcnow)
    progress = Column(Float, default=0.0)

    media = relationship("Media")


class CatalogSyncRun(Base):
    """Modelo para ejecuciones de sincronización del catálogo."""
    __tablename__ = "catalog_sync_runs"

    id = Column(String(36), primary_key=True)
    status = Column(String(32), nullable=False, index=True, default="pending")
    active_slot = Column(Integer, nullable=True)
    checkpoint_path = Column(String, nullable=True)
    pages_completed = Column(Integer, nullable=False, default=0)
    items_discovered = Column(Integer, nullable=False, default=0)
    last_activity_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("active_slot", name="uq_catalog_sync_runs_active_slot"),
    )