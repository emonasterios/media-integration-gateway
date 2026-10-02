"""Generador de playlist M3U para IPTV."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_db
from src.db.models import Media
from src.models.catalog import MediaItem, MediaType


router = APIRouter(tags=["m3u"])


def _convert_db_media_to_item(db_media: Media) -> MediaItem:
    """Convierte un objeto Media de la BD a MediaItem del catálogo."""
    media_type_str = db_media.media_type
    if media_type_str == "movie":
        media_type = MediaType.MOVIE
    elif media_type_str == "series":
        media_type = MediaType.SERIES
    elif media_type_str == "episode":
        media_type = MediaType.EPISODE
    else:
        media_type = MediaType.MOVIE

    # Extraer provider y provider_id desde sources
    provider = ""
    provider_id = ""
    if db_media.sources:
        provider = db_media.sources[0].provider
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


def _get_group_title(media_type: MediaType) -> str:
    """Determina el group-title según el tipo de medio."""
    if media_type in (MediaType.MOVIE,):
        return "Peliculas"
    if media_type in (MediaType.SERIES, MediaType.EPISODE):
        return "Series"
    return "Peliculas"


@router.get("/playlist.m3u")
async def get_m3u_playlist(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Genera playlist M3U a partir de los elementos cacheados en la base de datos."""
    # Obtener todos los elementos de media cacheados (con sources cargados)
    stmt = select(Media)
    result = await db.execute(stmt)
    db_media_list = result.scalars().all()

    base_url = str(request.base_url).rstrip("/")
    if not base_url or base_url == "http://localhost":
        base_url = "http://localhost:8000"

    lines = ["#EXTM3U"]

    for db_media in db_media_list:
        # Cargar sources si no están cargados
        await db.refresh(db_media, ["sources"])
        
        if not db_media.sources:
            continue

        item = _convert_db_media_to_item(db_media)

        # Determinar grupo
        group = _get_group_title(item.media_type)

        # Formatear título con año si está presente
        title_with_year = f"{item.title} ({item.year})" if item.year else item.title

        # Línea EXTINF
        lines.append(f'#EXTINF:-1 group-title="{group}",{title_with_year}')

        # Línea de URL de resolución (GET endpoint para clientes IPTV)
        resolve_url = f"{base_url}/api/v1/resolve/{item.provider}/{item.provider_id}"
        lines.append(resolve_url)

    m3u_text = "\n".join(lines) + "\n"

    return Response(content=m3u_text, media_type="application/x-mpegurl")
