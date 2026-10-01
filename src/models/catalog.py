"""Modelos canónicos del catálogo multimedia."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MediaType(str, Enum):
    MOVIE = "movie"
    SERIES = "series"
    EPISODE = "episode"


class SubtitleInfo(BaseModel):
    language: str
    url: str
    label: Optional[str] = None


class PlaybackDescriptor(BaseModel):
    """Respuesta del Resolver: cómo reproducir un elemento."""

    protocol: str = Field(description="hls, mp4, dash, etc.")
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    expires_at: Optional[datetime] = None
    subtitles: list[SubtitleInfo] = Field(default_factory=list)


class MediaSource(BaseModel):
    """Una fuente que ofrece un elemento multimedia."""

    provider: str
    provider_id: str


class MediaItem(BaseModel):
    """Modelo canónico para películas y series."""

    media_id: str
    title: str
    media_type: MediaType
    year: Optional[int] = None
    poster_url: Optional[str] = None
    overview: Optional[str] = None
    provider: str
    provider_id: str
    external_id: Optional[str] = Field(
        default=None, description="IMDb, TMDb u otro identificador externo"
    )


class Season(BaseModel):
    season_number: int
    title: Optional[str] = None
    episode_count: int = 0


class Episode(BaseModel):
    episode_number: int
    season_number: int
    title: Optional[str] = None
    overview: Optional[str] = None
    provider_id: str
    provider: str


class SearchResult(BaseModel):
    items: list[MediaItem]
    total: int
    query: str
