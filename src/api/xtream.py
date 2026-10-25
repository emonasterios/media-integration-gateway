"""Endpoints de compatibilidad Xtream Codes API."""

from __future__ import annotations

import aiosqlite
import json
import logging
import os.path
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException

from src.models.catalog import MediaItem, MediaType
from src.services.catalog import CatalogService

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "gateway.db"
MOVIE_STREAM_ID_BASE = 100_000


async def _load_catalog_from_db(
    db_path: Path | str | None = None,
    media_type: MediaType = MediaType.MOVIE,
) -> list[MediaItem]:
    """Carga una sección del catálogo desde SQLite. db_path permite tests aislados."""
    target = Path(db_path) if db_path else DB_PATH
    if not target.exists():
        return []
    async with aiosqlite.connect(str(target)) as db:
        async with db.execute(
            "SELECT m.id, m.title, m.original_title, m.media_type, m.year, m.synopsis, m.poster_url, m.genres, "
            "MIN(s.url) as source_url "
            "FROM media m "
            "JOIN sources s ON s.media_id = m.id AND s.provider = 'cuevana3' AND s.catalog_presence = 'present' "
            "WHERE m.media_type = ? "
            "GROUP BY m.id, m.title, m.original_title, m.media_type, m.year, m.synopsis, m.poster_url, m.genres "
            "ORDER BY m.id",
            (media_type.value,),
        ) as cur:
            rows = await cur.fetchall()
    return [
        MediaItem(
            media_id=str(row[0]),
            provider="cuevana3",
            provider_id=row[8] or str(row[0]),
            title=row[1],
            original_title=row[2],
            media_type=media_type,
            year=row[4],
            overview=row[5],
            poster_url=row[6],
            genres=json.loads(row[7]) if row[7] else [],
        )
        for row in rows
    ]


async def _load_single_movie_from_db(
    media_id: int,
    db_path: Path | str | None = None,
) -> MediaItem | None:
    """Carga UNA película por media_id (PK) desde SQLite. db_path permite tests aislados."""
    target = Path(db_path) if db_path else DB_PATH
    if not target.exists():
        return None
    async with aiosqlite.connect(str(target)) as db:
        # Verificar qué columnas existen en la tabla media (compatibilidad con schemas de test)
        async with db.execute("PRAGMA table_info(media)") as cur:
            columns = {row[1] for row in await cur.fetchall()}
        
        # Construir SELECT dinámico según columnas disponibles
        base_cols = ["m.id", "m.title", "m.original_title", "m.media_type", "m.year", "m.synopsis", "m.poster_url", "m.genres"]
        extra_cols = []
        if "cast" in columns:
            extra_cols.append("m.cast")
        else:
            extra_cols.append("NULL as cast")
        if "director" in columns:
            extra_cols.append("m.director")
        else:
            extra_cols.append("NULL as director")
        if "duration" in columns:
            extra_cols.append("m.duration")
        else:
            extra_cols.append("NULL as duration")
        if "rating" in columns:
            extra_cols.append("m.rating")
        else:
            extra_cols.append("NULL as rating")
        if "country" in columns:
            extra_cols.append("m.country")
        else:
            extra_cols.append("NULL as country")
        
        select_cols = ", ".join(base_cols + extra_cols + ["s.url as source_url"])
        
        async with db.execute(
            f"SELECT {select_cols} "
            "FROM media m "
            "JOIN sources s ON s.media_id = m.id AND s.provider = 'cuevana3' AND s.catalog_presence = 'present' "
            "WHERE m.media_type = 'movie' AND m.id = ? "
            "GROUP BY m.id",
            (media_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    # row indices: 0=id, 1=title, 2=original_title, 3=media_type, 4=year, 5=synopsis, 6=poster_url, 7=genres,
    # 8=cast, 9=director, 10=duration, 11=rating, 12=country, 13=source_url
    return MediaItem(
        media_id=str(row[0]),
        provider="cuevana3",
        provider_id=row[13] or str(row[0]),
        title=row[1],
        original_title=row[2],
        media_type=MediaType.MOVIE,
        year=row[4],
        overview=row[5],
        poster_url=row[6],
        genres=json.loads(row[7]) if row[7] else [],
        cast=json.loads(row[8]) if row[8] else [],
        director=row[9] or "",
        duration=row[10] or "",
        rating=row[11] or 0,
        country=row[12] or "",
    )


router = APIRouter(tags=["xtream"])


def _get_catalog_service() -> CatalogService:
    """Placeholder para inyección de dependencia. En main.py se configura el override."""
    raise NotImplementedError("CatalogService no configurado")


def _genre_to_id(genres: list[str], sorted_genres: list[str]) -> str:
    if not genres or not sorted_genres:
        return "1"
    first = genres[0]
    if first in sorted_genres:
        return str(sorted_genres.index(first) + 1)
    return "1"


def _movie_stream_id(movie: MediaItem, fallback_index: int = 1) -> int:
    """Calcula un stream_id estable en un rango separado de los IDs VOD heredados."""
    try:
        return MOVIE_STREAM_ID_BASE + int(movie.media_id)
    except (ValueError, TypeError):
        return MOVIE_STREAM_ID_BASE + fallback_index


def _build_genre_categories(genres_or_items: list | set | None = None) -> list[dict]:
    """Construye la lista de categorías VOD a partir de géneros o MediaItems."""
    genres: set[str] = set()
    if genres_or_items:
        for item in genres_or_items:
            if isinstance(item, str):
                genres.add(item)
            elif hasattr(item, "genres") and item.genres:
                genres.update(item.genres)
            elif isinstance(item, dict) and "genres" in item:
                genres.update(item["genres"])
    if genres:
        return [
            {"category_id": str(idx), "category_name": genre_name, "parent_id": 0}
            for idx, genre_name in enumerate(sorted(genres), 1)
        ]
    return [{"category_id": "1", "category_name": "Peliculas", "parent_id": 0}]


async def _enrich_genres_from_db(items: list[MediaItem], db_path: Path | str | None = None) -> list[MediaItem]:
    """Lee géneros de la BD y los inyecta en los items que los tienen vacíos."""
    target = Path(db_path) if db_path else DB_PATH
    if not target.exists():
        return items
    try:
        async with aiosqlite.connect(str(target)) as db:
            async with db.execute(
                "SELECT id, genres FROM media WHERE media_type='movie' AND genres IS NOT NULL AND genres != '[]'"
            ) as cur:
                db_genres = {str(row[0]): json.loads(row[1]) async for row in cur}
        for item in items:
            if not item.genres:
                if item.provider_id in db_genres:
                    item.genres = db_genres[item.provider_id]
                elif item.media_id in db_genres:
                    item.genres = db_genres[item.media_id]
    except Exception:
        pass
    return items


def _media_item_to_vod_stream(
    item: MediaItem,
    index: int,
    sorted_genres: list[str] | None = None,
    category_id: str | None = None,
) -> dict:
    """Convierte MediaItem a dict de stream VOD Xtream Codes."""
    stream_id = _movie_stream_id(item, index)
    return {
        "num": index,
        "name": item.title,
        "stream_type": "movie",
        "stream_id": stream_id,
        "stream_icon": item.poster_url or "",
        "rating": "0",
        "rating_5based": 0.0,
        "added": str(int(item.year * 31536000)) if item.year else "",
        # Xtream only admits one category_id per row.  For a category-filtered
        # request it must match the requested category, even when that genre is
        # not the movie's first genre; otherwise clients such as iMPlayer drop
        # the otherwise valid row from that category.
        "category_id": category_id or _genre_to_id(item.genres, sorted_genres or []),
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
        genres: set[str] = set()
        movies = await _load_catalog_from_db(media_type=MediaType.MOVIE)
        for movie in movies:
            genres.update(movie.genres or [])
        if genres:
            return _build_genre_categories(movies)
        # Fallback: leer del caché en memoria de catalog_service
        movies: list[MediaItem] = []
        cache = getattr(catalog_service, "_catalog_cache", {})
        for key, value in cache.items():
            # value es (timestamp, list[MediaItem])
            items = value[1] if isinstance(value, tuple) else value
            for item in items:
                if getattr(item, "media_type", None) == MediaType.MOVIE:
                    movies.append(item)
        if movies:
            return _build_genre_categories(movies)
        return [{"category_id": "1", "category_name": "Peliculas", "parent_id": 0}]

    if action == "get_series_categories":
        return [{"category_id": "2", "category_name": "Series", "parent_id": 0}]

    if action == "get_live_categories":
        return [{"category_id": "3", "category_name": "TV en Vivo", "parent_id": 0}]

    if action == "get_vod_streams":
        category_id = request.query_params.get("category_id")
        unique_movies = await _load_catalog_from_db()
        unique_movies.sort(key=lambda m: (m.media_id or "", m.title))
        unique_movies = await _enrich_genres_from_db(unique_movies)
        genres_set: set[str] = set()
        for m in unique_movies:
            genres_set.update(m.genres or [])
        sorted_genres = sorted(genres_set)
        if category_id:
            try:
                idx = int(category_id)
            except ValueError:
                return []
            if not (1 <= idx <= len(sorted_genres)):
                return []
            target_genre = sorted_genres[idx - 1]
            unique_movies = [m for m in unique_movies if m.genres and target_genre in m.genres]
        return [
            _media_item_to_vod_stream(item, idx, sorted_genres, category_id=category_id)
            for idx, item in enumerate(unique_movies, 1)
        ]

    if action == "get_vod_info":
        vod_id = request.query_params.get("vod_id", "")
        try:
            stream_id = int(vod_id)
        except ValueError:
            return {}

        media_id = stream_id - MOVIE_STREAM_ID_BASE
        if media_id <= 0:
            return {}

        item = await _load_single_movie_from_db(media_id)
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
            "movie_data": _media_item_to_vod_stream(item, stream_id - MOVIE_STREAM_ID_BASE),
        }

    if action == "get_series":
        series = await _load_catalog_from_db(media_type=MediaType.SERIES)
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
        items = await _load_catalog_from_db(media_type=MediaType.MOVIE)
        query_lower = query.lower()
        movies = [item for item in items if query_lower in item.title.lower()]
        sorted_genres = sorted({genre for item in movies for genre in (item.genres or [])})
        return [_media_item_to_vod_stream(item, idx, sorted_genres) for idx, item in enumerate(movies, 1)]

    if action == "search_series":
        query = request.query_params.get("query", "")
        if not query:
            return []
        items = await _load_catalog_from_db(media_type=MediaType.SERIES)
        query_lower = query.lower()
        series = [item for item in items if query_lower in item.title.lower()]
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

    movies = await _load_catalog_from_db(media_type=MediaType.MOVIE)
    series = await _load_catalog_from_db(media_type=MediaType.SERIES)
    if not movies and not series:
        # Fallback: leer del caché en memoria de catalog_service (sin red)
        cache = getattr(catalog_service, "_catalog_cache", {})
        for value in cache.values():
            cached_items = value[1] if isinstance(value, tuple) else value
            for item in cached_items:
                if getattr(item, "media_type", None) == MediaType.MOVIE:
                    movies.append(item)
                elif getattr(item, "media_type", None) == MediaType.SERIES:
                    series.append(item)

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


def movie_stream_id(media_id: int) -> int:
    return MOVIE_STREAM_ID_BASE + media_id


def media_id_from_stream_id(stream_id: int) -> int:
    return stream_id - MOVIE_STREAM_ID_BASE


def find_movie_by_stream_id(items: list[MediaItem], stream_id: int) -> MediaItem | None:
    if stream_id <= MOVIE_STREAM_ID_BASE:
        return None
    for idx, movie in enumerate(items, start=1):
        if _movie_stream_id(movie, idx) == stream_id:
            return movie
    return None


def _stream_id_to_media(index: int, media_type: str, catalog: list[MediaItem]) -> MediaItem | None:
    """Busca el MediaItem por stream_id (índice 1-based + offset)."""
    if media_type == "movie":
        movies = [m for m in catalog if m.media_type == MediaType.MOVIE]
        return find_movie_by_stream_id(movies, index)
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
    media_id = stream_id - MOVIE_STREAM_ID_BASE
    if media_id <= 0:
        return {"error": "stream not found", "stream_id": stream_id}
    media = await _load_single_movie_from_db(media_id)
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
            elif VideoResolver.is_doodstream(result.url):
                direct = await resolver.resolve_doodstream(result.url)
                if direct and direct.protocol in ("hls", "mp4"):
                    result = direct
        except Exception as e:
            logger.warning("Fallo resolviendo embed %s: %s", result.url, e)
        finally:
            await resolver.close()

        if result.protocol == "embed":
            # El resolver falló: no hacer fallback al HTML embed.
            logger.error("No se pudo resolver video real para embed: %s", result.url)
            raise HTTPException(status_code=500, detail="No se pudo resolver fuente de video")

    # Validar la URL final, después de convertir cualquier embed a HLS/MP4.
    if not await _verify_playback_url(result.url, result.protocol):
        logger.warning("Playback URL no responde (CDN muerto): %s", result.url[:80])
        raise HTTPException(status_code=502, detail="Fuente de video no disponible (CDN caído)")

    if result.protocol == "mp4":
        proxy_headers = {
            "Referer": "https://cuevana3.li",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        range_header = request.headers.get("range")
        if range_header:
            proxy_headers["Range"] = range_header

        logger.info("Proxying mp4 URL: %s", result.url[:80])
        return StreamingResponse(
            _proxy_stream(result.url, proxy_headers),
            status_code=206 if range_header else 200,
            media_type="video/mp4",
            headers={"Accept-Ranges": "bytes"},
        )

    if result.protocol == "hls":
        logger.info("Redirecting to HLS URL: %s", result.url[:80])
        return RedirectResponse(url=result.url, status_code=302)

    # Si no es directo ni se pudo resolver
    raise HTTPException(status_code=500, detail="Fuente de video no disponible")


async def _verify_playback_url(url: str, protocol: str) -> bool:
    """Verifica que la URL de playback responde. Útil para detectar CDN caídos."""
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=3,
            timeout=8.0,
        ) as client:
            response = await client.head(url)
        if response.status_code not in (200, 206):
            return False
        if protocol == "hls":
            return True
        if protocol == "mp4":
            content_type = response.headers.get("content-type", "")
            return "video/" in content_type
        return False
    except Exception:
        return False


async def _proxy_stream(url: str, headers: dict):
    """Generador que hace proxy del stream de video con soporte de rangos."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=60.0, verify=False) as client:
        async with client.stream("GET", url, headers=headers) as response:
            async for chunk in response.aiter_bytes(chunk_size=65536):
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
    series_catalog = await _load_catalog_from_db(media_type=MediaType.SERIES)
    media = _stream_id_to_media(stream_id, "series", series_catalog)
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
