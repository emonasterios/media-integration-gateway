"""Endpoints de compatibilidad Xtream Codes API."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request

from src.models.catalog import MediaItem, MediaType
from src.services.catalog import CatalogService


router = APIRouter(tags=["xtream"])


def _get_catalog_service() -> CatalogService:
    """Placeholder para inyección de dependencia. En main.py se configura el override."""
    raise NotImplementedError("CatalogService no configurado")


def _media_item_to_vod_stream(item: MediaItem, index: int) -> dict:
    """Convierte MediaItem a dict de stream VOD Xtream Codes."""
    return {
        "num": index,
        "name": item.title,
        "stream_type": "movie",
        "stream_id": 1000 + index,
        "stream_icon": item.poster_url or "",
        "rating": "0",
        "rating_5based": 0.0,
        "added": str(int(item.year * 31536000)) if item.year else "",
        "category_id": "1",
        "container_extension": "mp4",
        "custom_sid": "",
        "direct_source": "",
    }


def _media_item_to_series_stream(item: MediaItem, index: int) -> dict:
    """Convierte MediaItem a dict de stream de serie Xtream Codes."""
    return {
        "num": index,
        "name": item.title,
        "series_id": 2000 + index,
        "cover": item.poster_url or "",
        "plot": item.overview or "",
        "cast": "",
        "director": "",
        "genre": "",
        "releaseDate": f"{item.year}-01-01" if item.year else "",
        "last_modified": "",
        "rating": "0",
        "rating_5based": 0.0,
        "backdrop_path": [],
        "youtube_trailer": "",
        "episode_run_time": 0,
        "category_id": "2",
    }


@router.get("/player_api.php")
async def xtream_player_api(
    request: Request,
    username: str = "",
    password: str = "",
    action: Optional[str] = None,
    catalog_service: CatalogService = Depends(_get_catalog_service),
):
    """Endpoint principal Xtream Codes player_api.php."""
    
    # Sin credenciales o vacías -> auth=0
    if not username or not password:
        return {"user_info": {"auth": 0}, "server_info": {}}

    public_host = request.url.hostname or "localhost"
    public_port = request.url.port or (443 if request.url.scheme == "https" else 80)
    now = datetime.now()
    timestamp_now = str(int(now.timestamp()))
    time_now = now.strftime("%Y-%m-%d %H:%M:%S")

    user_info = {
        "username": username,
        "password": password,
        "auth": 1,
        "status": "Active",
        "exp_date": "4102444800",
        "is_trial": "0",
        "active_cons": "0",
        "created_at": "",
        "max_connections": "1",
        "allowed_output_formats": ["m3u8", "mp4", "ts"],
    }

    server_info = {
        # Xtream clients combine these fields themselves.  Advertising a URL
        # that already contains the port while also reporting the container's
        # internal port makes some TVs reject the playlist.
        "url": public_host,
        "port": str(public_port),
        "https_port": "",
        "server_protocol": request.url.scheme,
        "rtmp_port": "",
        "timezone": "America/Caracas",
        "timestamp_now": timestamp_now,
        "time_now": time_now,
    }

    if action == "get_vod_categories":
        return [{"category_id": "1", "category_name": "Peliculas", "parent_id": 0}]

    if action == "get_series_categories":
        return [{"category_id": "2", "category_name": "Series", "parent_id": 0}]

    if action == "get_live_categories":
        return [{"category_id": "3", "category_name": "TV en Vivo", "parent_id": 0}]

    if action == "get_vod_streams":
        catalog = await catalog_service.get_catalog("cuevana3")
        movies = [item for item in catalog if item.media_type == MediaType.MOVIE]
        return [_media_item_to_vod_stream(item, idx) for idx, item in enumerate(movies, 1)]

    if action == "get_series":
        catalog = await catalog_service.get_catalog("cuevana3")
        series = [item for item in catalog if item.media_type == MediaType.SERIES]
        return [_media_item_to_series_stream(item, idx) for idx, item in enumerate(series, 1)]

    if action == "get_live_streams":
        return []

    # Sin action -> devolver cuenta completa
    return {"user_info": user_info, "server_info": server_info}


@router.get("/panel_api.php")
async def xtream_panel_api(
    username: str = "",
    password: str = "",
    catalog_service: CatalogService = Depends(_get_catalog_service),
):
    """Endpoint Xtream Codes panel_api.php."""
    
    if not username or not password:
        return {"user_info": {"auth": 0}, "server_info": {}}

    catalog = await catalog_service.get_catalog("cuevana3")
    movies = [item for item in catalog if item.media_type == MediaType.MOVIE]
    series = [item for item in catalog if item.media_type == MediaType.SERIES]

    return {
        "panel_info": {
            "live_streams": 0,
            "vod_streams": len(movies),
            "series_streams": len(series),
            "episodes": 0,
            "active_connections": 0,
            "max_connections": 1,
        }
    }


# ── Streaming endpoints (lo que la TV pide al reproducir) ──────────

from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)


def _stream_id_to_media(index: int, media_type: str, catalog: list[MediaItem]) -> MediaItem | None:
    """Busca el MediaItem por stream_id (índice 1-based + offset)."""
    if media_type == "movie":
        movies = [m for m in catalog if m.media_type == MediaType.MOVIE]
        offset = 0  # stream_id = 1000 + index
        for idx, item in enumerate(movies, 1):
            if 1000 + idx == index:
                return item
    elif media_type == "series":
        series = [m for m in catalog if m.media_type == MediaType.SERIES]
        for idx, item in enumerate(series, 1):
            if 2000 + idx == index:
                return item
    return None


@router.get("/movie/{username}/{password}/{stream_id}.{ext}")
@router.get("/movie/{username}/{password}/{stream_id}")
async def stream_movie(
    username: str,
    password: str,
    stream_id: int,
    ext: str = "mp4",
    catalog_service: CatalogService = Depends(_get_catalog_service),
):
    """Reproduce una película VOD. Resuelve el video real y redirige o hace proxy."""
    catalog = await catalog_service.get_catalog("cuevana3")
    media = _stream_id_to_media(stream_id, "movie", catalog)
    if not media:
        return {"error": "stream not found", "stream_id": stream_id}

    result = await catalog_service.resolve_playback(media.provider, media.provider_id)

    # Si es video directo (hls/mp4), redirigir
    if result.protocol in ("hls", "mp4"):
        return RedirectResponse(url=result.url, status_code=302)

    # Si es embed HTML, intentar resolver el video real
    if result.protocol == "embed":
        from src.services.video_resolver import VideoResolver
        resolver = VideoResolver()
        try:
            if VideoResolver.is_voe(result.url):
                direct = await resolver.resolve_voe(result.url)
                if direct and direct.protocol in ("hls", "mp4"):
                    await resolver.close()
                    return RedirectResponse(url=direct.url, status_code=302)
            elif VideoResolver.is_doodstream(result.url):
                direct = await resolver.resolve_doodstream(result.url)
                if direct and direct.protocol in ("hls", "mp4"):
                    await resolver.close()
                    return RedirectResponse(url=direct.url, status_code=302)
        except Exception as e:
            logger.warning("Fallo resolviendo embed %s: %s", result.url, e)
        finally:
            await resolver.close()

    # Fallback: redirigir al embed (la TV puede que no lo reproduzca)
    return RedirectResponse(url=result.url, status_code=302)


@router.get("/series/{username}/{password}/{stream_id}/{episode}.{ext}")
async def stream_series(
    username: str,
    password: str,
    stream_id: int,
    episode: str,
    ext: str,
    request: Request,
    catalog_service: CatalogService = Depends(_get_catalog_service),
):
    """Reproduce un episodio de serie. Redirige al URL de playback real."""
    catalog = await catalog_service.get_catalog("cuevana3")
    media = _stream_id_to_media(stream_id, "series", catalog)
    if not media:
        return {"error": "stream not found", "stream_id": stream_id}

    result = await catalog_service.resolve_playback(media.provider, media.provider_id)
    return RedirectResponse(url=result.url, status_code=302)


@router.get("/live/{username}/{password}/{stream_id}.{ext}")
async def stream_live(
    username: str,
    password: str,
    stream_id: int,
    ext: str,
    request: Request,
):
    """Stream de TV en vivo (no implementado aún)."""
    return {"error": "live streaming not implemented"}
