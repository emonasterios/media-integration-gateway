"""Servicio de control de sincronización asíncrona del catálogo."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.db.models import CatalogSyncRun


class ActiveSyncAlreadyRunningError(Exception):
    """Excepción lanzada cuando ya hay una sincronización activa."""

    def __init__(self, active_run_id: str, status: str):
        self.active_run_id = active_run_id
        self.status = status
        super().__init__(f"Active sync run already exists: {active_run_id} ({status})")


ActiveRunConflictError = ActiveSyncAlreadyRunningError


class CatalogSyncService:
    """Servicio que gestiona la concurrencia, persistencia y ciclo de vida de tareas de sincronización."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        runner: Optional[callable] = None,
    ):
        self._session_factory = session_factory
        self._requires_complete_checkpoint = runner is None
        if runner is None:
            from scripts.sync_catalog import sync_catalog

            async def default_runner(progress_callback=None, allow_large_delete=False, enrich_new=False):
                return await sync_catalog(
                    on_page_progress=progress_callback,
                    allow_large_delete=allow_large_delete,
                    enrich_new=enrich_new,
                )
            self._runner = default_runner
        else:
            self._runner = runner
        self._running_tasks: set[asyncio.Task] = set()

    async def recover_interrupted_runs(self) -> int:
        """Recupera ejecuciones interrumpidas tras reinicio del proceso."""
        async with self._session_factory() as db:
            result = await db.execute(
                select(CatalogSyncRun).where(
                    (CatalogSyncRun.status.in_(["pending", "running"]))
                    | (CatalogSyncRun.active_slot.isnot(None))
                )
            )
            interrupted_runs = result.scalars().all()

            count = 0
            now = datetime.now(timezone.utc)
            for run in interrupted_runs:
                run.status = "interrupted"
                run.error = "Interrupted by system restart"
                run.active_slot = None
                run.finished_at = now
                count += 1

            if count > 0:
                await db.commit()

            return count

    async def start(self) -> CatalogSyncRun:
        """Inicia una nueva sincronización o lanza error si ya hay una activa."""
        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with self._session_factory() as db:
            new_run = CatalogSyncRun(
                id=run_id,
                status="pending",
                active_slot=1,
                created_at=now,
                pages_completed=0,
                items_discovered=0,
            )
            db.add(new_run)
            try:
                await db.commit()
                await db.refresh(new_run)
            except IntegrityError:
                await db.rollback()
                # Buscar la ejecución activa existente
                result = await db.execute(
                    select(CatalogSyncRun).where(CatalogSyncRun.active_slot == 1)
                )
                existing_run = result.scalars().first()
                if existing_run:
                    raise ActiveSyncAlreadyRunningError(active_run_id=existing_run.id, status=existing_run.status)
                # Si no hay run existente pero falló la integridad, relanzar
                raise

        # Si la inserción tuvo éxito, crear tarea en segundo plano
        task = asyncio.create_task(self._execute_run(run_id))
        self._running_tasks.add(task)
        task.add_done_callback(self._running_tasks.discard)

        return new_run

    async def _execute_run(self, run_id: str) -> None:
        """Ejecuta el trabajo de sincronización en segundo plano."""
        now = datetime.now(timezone.utc)

        # Transición a running
        async with self._session_factory() as db:
            result = await db.execute(
                select(CatalogSyncRun).where(CatalogSyncRun.id == run_id)
            )
            run = result.scalar_one_or_none()
            if run:
                run.status = "running"
                run.started_at = now
                run.last_activity_at = now
                await db.commit()

        # Callback async de progreso
        async def on_progress(pages: int, items: int) -> None:
            progress_now = datetime.now(timezone.utc)
            async with self._session_factory() as db:
                result = await db.execute(
                    select(CatalogSyncRun).where(CatalogSyncRun.id == run_id)
                )
                run = result.scalar_one_or_none()
                if run:
                    run.pages_completed = pages
                    run.items_discovered = items
                    run.last_activity_at = progress_now
                    await db.commit()

        try:
            # Ejecutar el runner inyectado pasándole el callback
            runner_result = await self._runner(
                progress_callback=on_progress,
                allow_large_delete=False,
                enrich_new=False,
            )

            # Si el runner finaliza con checkpoint y este cumple status == "complete" y stop_reason == "natural_end"
            async with self._session_factory() as db:
                query_result = await db.execute(
                    select(CatalogSyncRun).where(CatalogSyncRun.id == run_id)
                )
                run = query_result.scalar_one_or_none()
                if run:
                    checkpoint = runner_result
                    if checkpoint is None and not self._requires_complete_checkpoint:
                        run.status = "completed"
                    elif (
                        getattr(checkpoint, "status", None) == "complete"
                        and getattr(checkpoint, "stop_reason", None) == "natural_end"
                    ):
                        run.status = "completed"
                    else:
                        run.status = "interrupted"
                        run.error = "Ejecución terminada sin parada natural completa"
                    run.finished_at = datetime.now(timezone.utc)
                    run.active_slot = None
                    await db.commit()

        except asyncio.CancelledError:
            # Transición terminal: interrupted
            async with self._session_factory() as db:
                result = await db.execute(
                    select(CatalogSyncRun).where(CatalogSyncRun.id == run_id)
                )
                run = result.scalar_one_or_none()
                if run:
                    run.status = "interrupted"
                    run.error = "Task cancelled"
                    run.finished_at = datetime.now(timezone.utc)
                    run.active_slot = None
                    await db.commit()
            raise

        except Exception as exc:
            # Transición terminal: failed
            async with self._session_factory() as db:
                result = await db.execute(
                    select(CatalogSyncRun).where(CatalogSyncRun.id == run_id)
                )
                run = result.scalar_one_or_none()
                if run:
                    run.status = "failed"
                    run.error = str(exc)[:500]
                    run.finished_at = datetime.now(timezone.utc)
                    run.active_slot = None
                    await db.commit()

    async def get_latest_run(self) -> Optional[CatalogSyncRun]:
        """Obtiene la ejecución más reciente por created_at."""
        async with self._session_factory() as db:
            result = await db.execute(
                select(CatalogSyncRun)
                .order_by(CatalogSyncRun.created_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def get_run(self, run_id: str) -> Optional[CatalogSyncRun]:
        """Obtiene una ejecución por su ID."""
        async with self._session_factory() as db:
            result = await db.execute(
                select(CatalogSyncRun).where(CatalogSyncRun.id == run_id)
            )
            return result.scalar_one_or_none()

    async def shutdown(self) -> None:
        """Cancela todas las tareas activas y espera a que terminen."""
        for task in list(self._running_tasks):
            task.cancel()
        await asyncio.gather(*self._running_tasks, return_exceptions=True)
