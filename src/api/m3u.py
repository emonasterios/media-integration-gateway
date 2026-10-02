"""Endpoint de playlist M3U para IPTV."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from src.db.database import SessionLocal
from src.db.models import Media
from src.services.cache import CatalogCache

router = APIRouter()


def _get_db() -> Session:
    """Dependencia para obtener sesión de base de datos."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _get_cache(db: Session = Depends(_get_db)) -> CatalogCache:
    """Dependencia para obtener el servicio de caché."""
    return CatalogCache(db)


@router.get("/playlist.m3u")
async def get_playlist_m3u(
    request: Request,
    cache: CatalogCache = Depends(_get_cache),
) -> Response:
    """
    Genera playlist M3U con todos los elementos cacheados.
    
    Retorna contenido text/plain con media_type application/x-mpegurl
    para compatibilidad con reproductores IPTV.
    """
    # Obtener todos los elementos de media válidos de la base de datos
    # Usamos la sesión del cache para consultar directamente
    media_items = cache.db.query(Media).all()
    
    # Filtrar solo los que están vigentes según TTL
    valid_items = [m for m in media_items if cache.is_valid(m)]
    
    lines = ["#EXTM3U"]
    
    for media in valid_items:
        # Determinar el grupo según el tipo de medio
        group_title = _get_group_title(media.media_type)
        
        # Obtener el provider_id desde sources
        provider_id = ""
        provider_name = ""
        if media.sources:
            # Usar la primera fuente disponible
            src = media.sources[0]
            provider_name = src.provider
            provider_id = src.url
        
        if not provider_id or not provider_name:
            continue
        
        # Construir URL de resolución usando request.base_url
        base_url = str(request.base_url).rstrip("/")
        resolve_url = f"{base_url}/api/v1/playback/resolve/{provider_name}/{provider_id}"
        
        # Línea EXTINF: duración -1 (live/desconocida), group-title, título
        lines.append(f'#EXTINF:-1 group-title="{group_title}",{media.title}')
        # Línea de URL
        lines.append(resolve_url)
    
    content = "\n".join(lines) + "\n"
    
    return Response(
        content=content,
        media_type="application/x-mpegurl",
    )


def _get_group_title(media_type: str) -> str:
    """Mapea el tipo de medio a nombre de grupo para M3U."""
    mapping = {
        "movie": "Peliculas",
        "series": "Series",
        "episode": "Episodios",
    }
    return mapping.get(media_type, "Otros")