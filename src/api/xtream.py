"""Endpoints de compatibilidad Xtream Codes API."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException

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
        "available_languages": item.available_languages or [],
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
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    public_scheme = forwarded_proto if forwarded_proto in {"http", "https"} else request.url.scheme
    public_port = request.url.port or (443 if public_scheme == "https" else 80)
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
        "https_port": str(public_port) if public_scheme == "https" else "",
        "server_protocol": public_scheme,
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
        catalog2 = await catalog_service.get_catalog("cuevan_net")
        movies = [item for item in catalog + catalog2 if item.media_type == MediaType.MOVIE]
        return [_media_item_to_vod_stream(item, idx) for idx, item in enumerate(movies, 1)]

    if action == "get_vod_info":
        vod_id = request.query_params.get("vod_id", "")
        try:
            stream_id = int(vod_id)
        except ValueError:
            return {}

        catalog = await catalog_service.get_catalog("cuevana3")
        catalog2 = await catalog_service.get_catalog("cuevan_net")
        item = _stream_id_to_media(stream_id, "movie", catalog + catalog2)
        if item is None:
            return {}

        return {
            "info": {
                "name": item.title,
                "o_name": item.title,
                "movie_image": item.poster_url or "",
                "releasedate": str(item.year) if item.year else "",
                "plot": item.overview or "",
                "cast": ", ".join(item.cast or []),
                "director": item.director or "",
                "duration": item.duration or "",
                "rating": str(item.rating or 0),
                "country": item.country or "",
                "genre": ", ".join(item.genres),
            },
            "movie_data": _media_item_to_vod_stream(item, stream_id - 1000),
        }

    if action == "get_series":
        catalog = await catalog_service.get_catalog("cuevana3")
        catalog2 = await catalog_service.get_catalog("cuevan_net")
        series = [item for item in catalog + catalog2 if item.media_type == MediaType.SERIES]
        return [_media_item_to_series_stream(item, idx) for idx, item in enumerate(series, 1)]

    if action == "get_live_streams":
        # iMPlayer treats an empty live-stream response as a playlist download
        # failure, even when the account only exposes VOD and series.  Publish
        # one harmless compatibility entry so it can finish importing the
        # playlist and expose the real movie/series catalogs.
        return [
            {
                "num": 1,
                "name": "Peliculas y Series",
                "stream_type": "live",
                "stream_id": 1,
                "stream_icon": "",
                "epg_channel_id": None,
                "added": "",
                "category_id": "3",
                "custom_sid": "",
                "tv_archive": 0,
                "direct_source": "",
                "tv_archive_duration": 0,
            }
        ]

    # Búsqueda por nombre
    if action == "search_vod":
        query = request.query_params.get("query", "")
        if not query:
            return []
        search_results = await catalog_service.search(query)
        movies = [item for sr in search_results for item in sr.items if item.media_type == MediaType.MOVIE]
        return [_media_item_to_vod_stream(item, idx) for idx, item in enumerate(movies, 1)]

    if action == "search_series":
        query = request.query_params.get("query", "")
        if not query:
            return []
        search_results = await catalog_service.search(query)
        series = [item for sr in search_results for item in sr.items if item.media_type == MediaType.SERIES]
        return [_media_item_to_series_stream(item, idx) for idx, item in enumerate(series, 1)]

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
    catalog2 = await catalog_service.get_catalog("cuevan_net")
    movies = [item for item in catalog + catalog2 if item.media_type == MediaType.MOVIE]
    series = [item for item in catalog + catalog2 if item.media_type == MediaType.SERIES]

    return {
        "panel_info": {
            "live_streams": 1,
            "vod_streams": len(movies),
            "series_streams": len(series),
            "episodes": 0,
            "active_connections": 0,
            "max_connections": 1,
        }
    }


# ── Streaming endpoints (lo que la TV pide al reproducir) ──────────

from fastapi.responses import RedirectResponse, StreamingResponse
import httpx

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


@router.head("/movie/{username}/{password}/{stream_id}")
@router.head("/movie/{username}/{password}/{stream_id}.{ext}")
@router.get("/movie/{username}/{password}/{stream_id}")
@router.get("/movie/{username}/{password}/{stream_id}.{ext}")
async def stream_movie(
    username: str,
    password: str,
    stream_id: int,
    request: Request,
    ext: str = "mp4",
    catalog_service: CatalogService = Depends(_get_catalog_service),
):
    """Reproduce una película VOD. Hace proxy del video real con soporte de rangos."""
    catalog = await catalog_service.get_catalog("cuevana3")
    catalog2 = await catalog_service.get_catalog("cuevan_net")
    media = _stream_id_to_media(stream_id, "movie", catalog + catalog2)
    if not media:
        return {"error": "stream not found", "stream_id": stream_id}

    result = await catalog_service.resolve_playback(media.provider, media.provider_id)

    # Si es embed HTML, intentar resolver el video real
    if result.protocol == "embed":
        from src.services.video_resolver import VideoResolver
        resolver = VideoResolver()
        try:
            if VideoResolver.is_voe(result.url):
                direct = await resolver.resolve_voe(result.url)
                if direct and direct.protocol in ("hls", "mp4"):
                    result = direct
                    logger.info("Redirecting to direct %s URL: %s", result.protocol, result.url[:80])
                    return RedirectResponse(url=result.url, status_code=302)
            elif VideoResolver.is_doodstream(result.url):
                direct = await resolver.resolve_doodstream(result.url)
                if direct and direct.protocol in ("hls", "mp4"):
                    result = direct
                    logger.info("Redirecting to direct %s URL: %s", result.protocol, result.url[:80])
                    return RedirectResponse(url=result.url, status_code=302)
        except Exception as e:
            logger.warning("Fallo resolviendo embed %s: %s", result.url, e)
        finally:
            await resolver.close()

        # Si llegamos aquí, el resolver falló - NO hacer fallback al embed
        logger.error("No se pudo resolver video real para embed: %s", result.url)
        raise HTTPException(status_code=500, detail="No se pudo resolver fuente de video")

    # Si es video directo (hls/mp4), redirigir al CDN
    if result.protocol in ("hls", "mp4"):
        logger.info("Redirecting to direct %s URL: %s", result.protocol, result.url[:80])
        return RedirectResponse(url=result.url, status_code=302)

    # Si no es directo ni se pudo resolver
    raise HTTPException(status_code=500, detail="Fuente de video no disponible")


async def _proxy_stream(url: str, headers: dict):
    """Generador que hace proxy del stream de video con soporte de rangos."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
        async with client.stream("GET", url, headers=headers) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                yield chunk


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
    catalog2 = await catalog_service.get_catalog("cuevan_net")
    media = _stream_id_to_media(stream_id, "series", catalog + catalog2)
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
