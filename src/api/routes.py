"""Endpoints REST del Media Integration Gateway."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from src.models.catalog import (
    Episode,
    MediaItem,
    PlaybackDescriptor,
    Season,
    SearchResult,
)
from src.services.catalog import CatalogService

router = APIRouter(prefix="/api/v1", tags=["catalog"])


def _get_catalog() -> CatalogService:
    """Placeholder para inyección de dependencia. En main.py se configura el override."""
    raise NotImplementedError("CatalogService no configurado")


# -------------------------------------------------------------------
# Búsqueda
# -------------------------------------------------------------------
@router.get("/search", response_model=list[SearchResult])
async def search(
    q: str,
    provider: Optional[str] = None,
    catalog: CatalogService = Depends(_get_catalog),
):
    """Buscar contenido en uno o todos los proveedores."""
    return await catalog.search(q, provider)


# -------------------------------------------------------------------
# Catálogo
# -------------------------------------------------------------------
@router.get("/catalog/{provider}", response_model=list[MediaItem])
async def get_catalog(
    provider: str,
    category: Optional[str] = None,
    catalog: CatalogService = Depends(_get_catalog),
):
    """Listar catálogo de un proveedor."""
    try:
        return await catalog.get_catalog(provider, category)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


# -------------------------------------------------------------------
# Detalles
# -------------------------------------------------------------------
@router.get("/details/{provider}/{media_id}", response_model=MediaItem)
async def get_details(
    provider: str,
    media_id: str,
    catalog: CatalogService = Depends(_get_catalog),
):
    """Detalles de una película o serie."""
    try:
        return await catalog.get_details(provider, media_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


# -------------------------------------------------------------------
# Temporadas
# -------------------------------------------------------------------
@router.get("/seasons/{provider}/{media_id}", response_model=list[Season])
async def get_seasons(
    provider: str,
    media_id: str,
    catalog: CatalogService = Depends(_get_catalog),
):
    try:
        return await catalog.get_seasons(provider, media_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


# -------------------------------------------------------------------
# Episodios
# -------------------------------------------------------------------
@router.get("/episodes/{provider}/{media_id}/{season_number}", response_model=list[Episode])
async def get_episodes(
    provider: str,
    media_id: str,
    season_number: int,
    catalog: CatalogService = Depends(_get_catalog),
):
    try:
        return await catalog.get_episodes(provider, media_id, season_number)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


# -------------------------------------------------------------------
# Resolución de reproducción
# -------------------------------------------------------------------
@router.post("/playback/resolve/{provider}/{media_id}", response_model=PlaybackDescriptor)
async def resolve_playback(
    provider: str,
    media_id: str,
    catalog: CatalogService = Depends(_get_catalog),
):
    """Obtener URL de reproducción para un elemento."""
    try:
        return await catalog.resolve_playback(provider, media_id)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))


# -------------------------------------------------------------------
# Proveedores disponibles
# -------------------------------------------------------------------
@router.get("/providers", response_model=list[str])
async def list_providers(catalog: CatalogService = Depends(_get_catalog)):
    """Listar nombres de proveedores registrados."""
    return catalog.provider_names
