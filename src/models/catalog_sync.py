"""Esquemas Pydantic para ejecuciones de sincronización del catálogo.

Exponen únicamente el estado observable de una ejecución; nunca trazas,
variables de entorno ni secretos.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CatalogSyncRunRead(BaseModel):
    """Vista pública de una ejecución de sincronización del catálogo."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    active_slot: Optional[int] = None
    checkpoint_path: Optional[str] = None
    pages_completed: int = 0
    items_discovered: int = 0
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
