"""Endpoints REST para control de sincronización asíncrona del catálogo."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from src.models.catalog_sync import CatalogSyncRunRead
from src.services.catalog_sync import ActiveRunConflictError, CatalogSyncService

router = APIRouter(tags=["catalog-sync"])


def _get_service(request: Request) -> CatalogSyncService:
    """Obtiene el servicio de sincronización desde el estado de la app."""
    service = getattr(request.app.state, "catalog_sync_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Servicio de sincronización no disponible",
        )
    return service


@router.post("/runs", response_model=CatalogSyncRunRead, status_code=202)
async def start_sync_run(
    service: CatalogSyncService = Depends(_get_service),
):
    """Inicia una nueva ejecución de sincronización del catálogo.

    Devuelve 202 Accepted si se inicia correctamente.
    Devuelve 409 Conflict si ya hay una sincronización activa.
    """
    try:
        run = await service.start()
        return run
    except ActiveRunConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "detail": str(exc),
                "active_run_id": exc.active_run_id,
                "status": exc.status,
            },
        )


@router.get("/runs/latest", response_model=CatalogSyncRunRead)
async def get_latest_run(
    service: CatalogSyncService = Depends(_get_service),
):
    """Obtiene la ejecución de sincronización más reciente."""
    run = await service.get_latest_run()
    if run is None:
        raise HTTPException(status_code=404, detail="No catalog sync runs found")
    return run


@router.get("/runs/{run_id}", response_model=CatalogSyncRunRead)
async def get_run(
    run_id: str,
    service: CatalogSyncService = Depends(_get_service),
):
    """Obtiene una ejecución de sincronización por su ID."""
    run = await service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return run