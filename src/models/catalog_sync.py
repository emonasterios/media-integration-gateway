"""Esquemas Pydantic para ejecuciones de sincronización del catálogo.

Exponen únicamente el estado observable de una ejecución; nunca trazas,
variables de entorno ni secretos.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PageSyncResult(BaseModel):
    """Resultado de la sincronización de una página individual."""

    model_config = ConfigDict(from_attributes=True)

    page_number: int
    page_url: str
    next_page_url: Optional[str] = None
    fingerprint: str
    seen: int
    unique: int
    inserted: int
    updated: int
    unchanged: int
    duplicate_in_run: int
    rejected: int


class CatalogSyncRunRead(BaseModel):
    """Vista pública de una ejecución de sincronización del catálogo."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    active_slot: Optional[int] = None
    checkpoint_path: Optional[str] = None
    phase: str = "queued"
    stop_reason: Optional[str] = None
    next_page_url: Optional[str] = None
    pages_completed: int = 0
    items_discovered: int = 0
    items_seen: int = 0
    items_unique: int = 0
    items_inserted: int = 0
    items_updated: int = 0
    items_unchanged: int = 0
    items_duplicate_in_run: int = 0
    items_rejected: int = 0
    last_activity_at: Optional[datetime] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None


class CatalogSyncConflictDetail(BaseModel):
    """Respuesta 409 cuando ya existe una sincronización activa."""

    detail: str
    active_run_id: str
    status: str