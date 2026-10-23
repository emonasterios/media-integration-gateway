"""Pruebas de integración para el control de sincronización asíncrona del catálogo.

Cubre los 7 casos obligatorios usando SQLite en memoria y runners falsos,
sin tocar red real ni rutas de producción.

Todas las pruebas usan base de datos SQLite en memoria temporal y
inyectan runners simulados en el CatalogSyncService.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.catalog_sync import router as catalog_sync_router
from src.db.database import Base
from src.db.models import CatalogSyncRun
from src.main import create_app
from src.models.catalog_sync import CatalogSyncRunRead
from src.services.catalog_sync import (
    ActiveRunConflictError,
    ActiveSyncAlreadyRunningError,
    CatalogSyncService,
)


# ---------------------------------------------------------------------------
# Helpers para tests
# ---------------------------------------------------------------------------


async def _make_in_memory_db():
    """Crea un motor SQLite en memoria con el esquema completo."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


class FakeRunner:
    """Runner falso configurable para simular comportamiento de sincronización."""

    def __init__(
        self,
        pages: int = 2,
        items_per_page: int = 5,
        should_fail: bool = False,
        fail_after_pages: int = 0,
        delay: float = 0.0,
    ):
        self.pages = pages
        self.items_per_page = items_per_page
        self.should_fail = should_fail
        self.fail_after_pages = fail_after_pages
        self.delay = delay
        self.call_count = 0
        self.progress_calls: list[tuple[int, int]] = []

    async def __call__(
        self,
        progress_callback=None,
        allow_large_delete: bool = False,
        enrich_new: bool = False,
    ) -> None:
        self.call_count += 1
        for page in range(1, self.pages + 1):
            if self.delay:
                await asyncio.sleep(self.delay)

            if self.should_fail and page > self.fail_after_pages:
                raise RuntimeError(f"Fallo simulado en página {page}")

            items = page * self.items_per_page
            self.progress_calls.append((page, items))

            if progress_callback:
                await progress_callback(page, items)


class CancellableRunner:
    """Runner que puede ser cancelado externamente."""

    def __init__(self, delay: float = 0.1):
        self.delay = delay
        self.cancel_event = asyncio.Event()
        self.started = asyncio.Event()
        self.progress_calls: list[tuple[int, int]] = []

    async def __call__(
        self,
        progress_callback=None,
        allow_large_delete: bool = False,
        enrich_new: bool = False,
    ) -> None:
        self.started.set()
        for page in range(1, 10):  # Muchas páginas, pero se cancela
            try:
                await asyncio.wait_for(self.cancel_event.wait(), timeout=self.delay)
                # Si cancel_event se setea, salimos del wait y lanzamos CancelledError
                raise asyncio.CancelledError()
            except asyncio.TimeoutError:
                # Timeout normal, continuar procesando
                pass

            items = page * 3
            self.progress_calls.append((page, items))

            if progress_callback:
                await progress_callback(page, items)

    def cancel(self):
        self.cancel_event.set()


async def _make_test_app(session_factory, runner=None):
    """Crea una app FastAPI de prueba con el servicio inyectado."""
    if runner is None:
        runner = FakeRunner()

    service = CatalogSyncService(session_factory=session_factory, runner=runner)
    # Usar _build_app() para evitar el lifespan que toca la BD de producción
    from src.main import _build_app
    app = _build_app()
    app.state.catalog_sync_service = service
    app.state.session_factory = session_factory
    return app, service


def _test_client(app) -> AsyncClient:
    """Cliente ASGI que comparte el event loop de pytest y de las tareas del servicio."""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# 1. test_start_run_returns_202_immediately
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_run_returns_202_immediately():
    """Verifica respuesta 202 con UUID y status pending, sin bloquearse con runners lentos."""
    engine, factory = await _make_in_memory_db()

    # Runner lento (con delay) para verificar que la respuesta es inmediata
    slow_runner = FakeRunner(pages=3, items_per_page=10, delay=0.5)
    app, service = await _make_test_app(factory, slow_runner)

    try:
        async with _test_client(app) as client:
            import time
            start = time.monotonic()
            response = await client.post("/api/v1/catalog-sync/runs")
            elapsed = time.monotonic() - start

            # Debe responder 202 inmediatamente (< 0.2s, no esperar al runner)
            assert response.status_code == 202, f"Expected 202, got {response.status_code}: {response.text}"
            assert elapsed < 0.2, f"Response took too long: {elapsed:.3f}s (runner has 0.5s delay)"

            data = response.json()
            assert "id" in data
            assert data["status"] == "pending"
            assert data["active_slot"] == 1
            assert data["pages_completed"] == 0
            assert data["items_discovered"] == 0
            assert data["created_at"] is not None
            assert data["started_at"] is None
            assert data["finished_at"] is None
            assert data["error"] is None

            # Verificar en BD
            run_id = data["id"]
            async with factory() as db:
                run = await db.get(CatalogSyncRun, run_id)
            assert run is not None
            assert run.status == "pending"
            assert run.active_slot == 1

    finally:
        await service.shutdown()
        await engine.dispose()


# ---------------------------------------------------------------------------
# 2. test_concurrent_start_returns_409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_start_returns_409():
    """Dos llamadas concurrentes a service.start() resultan en un éxito y un ActiveRunConflictError / HTTP 409."""
    engine, factory = await _make_in_memory_db()
    runner = FakeRunner(pages=2, items_per_page=5)
    app, service = await _make_test_app(factory, runner)

    try:
        async with _test_client(app) as client:
            # Primera llamada - debe tener éxito
            r1 = await client.post("/api/v1/catalog-sync/runs")
            assert r1.status_code == 202
            first_run = r1.json()
            first_run_id = first_run["id"]

            # Segunda llamada concurrente - debe fallar con 409
            r2 = await client.post("/api/v1/catalog-sync/runs")
            assert r2.status_code == 409
            error_data = r2.json()
            # El error viene anidado en 'detail' por HTTPException
            detail = error_data.get("detail", error_data)
            if isinstance(detail, dict):
                assert detail["active_run_id"] == first_run_id
                assert detail["status"] in ("pending", "running")
            else:
                assert error_data["active_run_id"] == first_run_id
                assert error_data["status"] in ("pending", "running")

            # Verificar que solo hay UNA ejecución activa en BD
            async with factory() as db:
                result = await db.execute(
                    select(CatalogSyncRun).where(CatalogSyncRun.active_slot == 1)
                )
                active_runs = result.scalars().all()
                assert len(active_runs) == 1
                assert active_runs[0].id == first_run_id

    finally:
        await service.shutdown()
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_start_service_level_returns_409():
    """Test a nivel de servicio: dos start() concurrentes -> uno éxito, uno ActiveRunConflictError."""
    engine, factory = await _make_in_memory_db()
    runner = FakeRunner(pages=2, items_per_page=5)
    service = CatalogSyncService(session_factory=factory, runner=runner)

    try:
        # Ejecutar dos start() concurrentes
        results = await asyncio.gather(
            service.start(),
            service.start(),
            return_exceptions=True,
        )

        # Exactamente uno debe ser éxito (CatalogSyncRun), otro ActiveRunConflictError
        successes = [r for r in results if isinstance(r, CatalogSyncRun)]
        conflicts = [r for r in results if isinstance(r, (ActiveRunConflictError, ActiveSyncAlreadyRunningError))]

        assert len(successes) == 1, f"Expected 1 success, got {len(successes)}"
        assert len(conflicts) == 1, f"Expected 1 conflict, got {len(conflicts)}"

        # El conflicto debe contener el ID de la ejecución activa
        conflict = conflicts[0]
        assert conflict.active_run_id == successes[0].id
        assert conflict.status == successes[0].status

    finally:
        await service.shutdown()
        await engine.dispose()


# ---------------------------------------------------------------------------
# 3. test_runner_progress_and_completion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_progress_and_completion():
    """Runner simulado emite 2 páginas, actualiza conteos en BD y finaliza en completed liberando active_slot."""
    engine, factory = await _make_in_memory_db()
    runner = FakeRunner(pages=2, items_per_page=5, delay=0.01)
    app, service = await _make_test_app(factory, runner)

    # Crear checkpoint válido en disco para que el servicio lo detecte como completado
    import tempfile
    from src.services.catalog_checkpoint import CatalogCheckpoint, save_checkpoint
    with tempfile.TemporaryDirectory() as tmpdir:
        checkpoint_path = Path(tmpdir) / "cuevana3_checkpoint.json"
        checkpoint = CatalogCheckpoint(
            provider="cuevana3",
            category=None,
            initial_path="/peliculas/",
            next_page=None,
            pages_completed=[1, 2],
            items=[],
            status="complete",
            stop_reason="natural_end",
        )
        save_checkpoint(checkpoint, checkpoint_path)

        # Parchear load_checkpoint para que use nuestro checkpoint temporal
        from src.services import catalog_checkpoint as cp_module
        original_load = cp_module.load_checkpoint
        def mock_load_checkpoint(path):
            if path.name == "cuevana3_checkpoint.json":
                return original_load(checkpoint_path)
            return original_load(path)

        try:
            with patch("src.services.catalog_checkpoint.load_checkpoint", mock_load_checkpoint):
                async with _test_client(app) as client:
                    # Iniciar sincronización
                    response = await client.post("/api/v1/catalog-sync/runs")
                    assert response.status_code == 202
                    run_id = response.json()["id"]

                    # Esperar a que termine (el runner es rápido)
                    await asyncio.sleep(0.2)

                    # Verificar estado final vía endpoint
                    response = await client.get(f"/api/v1/catalog-sync/runs/{run_id}")
                    assert response.status_code == 200
                    data = response.json()

                    assert data["status"] == "completed"
                    assert data["pages_completed"] == 2
                    assert data["items_discovered"] == 10  # 2 páginas * 5 items
                    assert data["active_slot"] is None  # CRÍTICO: debe ser None en estado terminal
                    assert data["finished_at"] is not None
                    assert data["error"] is None

                    # Verificar en BD directamente
                    async with factory() as db:
                        run = await db.get(CatalogSyncRun, run_id)
                    assert run.status == "completed"
                    assert run.pages_completed == 2
                    assert run.items_discovered == 10
                    assert run.active_slot is None  # CRÍTICO
                    assert run.finished_at is not None

        finally:
            await service.shutdown()
            await engine.dispose()


# ---------------------------------------------------------------------------
# 4. test_runner_failure_frees_slot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_failure_frees_slot():
    """Runner que lanza excepción pasa a failed, guarda error acotado y libera slot (active_slot=None)."""
    engine, factory = await _make_in_memory_db()
    # Runner que falla en la página 2
    runner = FakeRunner(pages=5, items_per_page=3, should_fail=True, fail_after_pages=1, delay=0.01)
    app, service = await _make_test_app(factory, runner)

    try:
        async with _test_client(app) as client:
            response = await client.post("/api/v1/catalog-sync/runs")
            assert response.status_code == 202
            run_id = response.json()["id"]

            # Esperar a que falle
            await asyncio.sleep(0.2)

            # Verificar estado final
            response = await client.get(f"/api/v1/catalog-sync/runs/{run_id}")
            assert response.status_code == 200
            data = response.json()

            assert data["status"] == "failed"
            assert data["active_slot"] is None  # CRÍTICO: liberado tras fallo
            assert data["finished_at"] is not None
            assert data["error"] is not None
            assert len(data["error"]) <= 500  # Error acotado sin tracebacks
            assert "Fallo simulado" in data["error"]

            # Verificar en BD
            async with factory() as db:
                run = await db.get(CatalogSyncRun, run_id)
            assert run.status == "failed"
            assert run.active_slot is None  # CRÍTICO
            assert run.error is not None
            assert len(run.error) <= 500

            # Verificar que se puede iniciar una NUEVA ejecución tras el fallo
            response2 = await client.post("/api/v1/catalog-sync/runs")
            assert response2.status_code == 202
            new_run_id = response2.json()["id"]
            assert new_run_id != run_id

    finally:
        await service.shutdown()
        await engine.dispose()


# ---------------------------------------------------------------------------
# 5. test_runner_cancellation_frees_slot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_cancellation_frees_slot():
    """Tarea cancelada pasa a interrupted, libera active_slot y permite nueva ejecución."""
    engine, factory = await _make_in_memory_db()
    runner = CancellableRunner(delay=0.05)
    app, service = await _make_test_app(factory, runner)

    try:
        async with _test_client(app) as client:
            response = await client.post("/api/v1/catalog-sync/runs")
            assert response.status_code == 202
            run_id = response.json()["id"]

            # Esperar a que el runner empiece
            await runner.started.wait()
            await asyncio.sleep(0.05)

            # Cancelar la tarea vía shutdown del servicio (simula reinicio/apagado)
            await service.shutdown()

            # Verificar estado final
            response = await client.get(f"/api/v1/catalog-sync/runs/{run_id}")
            assert response.status_code == 200
            data = response.json()

            assert data["status"] == "interrupted"
            assert data["active_slot"] is None  # CRÍTICO: liberado tras cancelación
            assert data["finished_at"] is not None
            assert data["error"] is not None
            assert "cancelled" in data["error"].lower() or "cancelled" in data["error"].lower()

            # Verificar en BD
            async with factory() as db:
                run = await db.get(CatalogSyncRun, run_id)
            assert run.status == "interrupted"
            assert run.active_slot is None  # CRÍTICO
            assert run.error is not None

            # Verificar que se puede iniciar una NUEVA ejecución tras cancelación
            # (crear nuevo servicio porque el anterior se shutdown)
            new_service = CatalogSyncService(session_factory=factory, runner=FakeRunner(pages=1, delay=0.01))
            app.state.catalog_sync_service = new_service

            response2 = await client.post("/api/v1/catalog-sync/runs")
            assert response2.status_code == 202
            new_run_id = response2.json()["id"]
            assert new_run_id != run_id

            await new_service.shutdown()

    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 6. test_startup_recovery_cleans_orphaned_runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_startup_recovery_cleans_orphaned_runs():
    """Registros pending/running previos pasan a interrupted al recuperar; completed no se alteran."""
    engine, factory = await _make_in_memory_db()

    # Crear registros directamente en BD simulando estado previo al reinicio
    now = datetime.now(timezone.utc)
    async with factory() as db:
        # Run completed - NO debe tocarse
        completed_run = CatalogSyncRun(
            id="completed-run-1",
            status="completed",
            active_slot=None,
            created_at=now,
            pages_completed=10,
            items_discovered=100,
            finished_at=now,
        )
        # Run pending - debe pasar a interrupted
        pending_run = CatalogSyncRun(
            id="pending-run-1",
            status="pending",
            active_slot=1,
            created_at=now,
            pages_completed=0,
            items_discovered=0,
        )
        # Run running - debe pasar a interrupted
        running_run = CatalogSyncRun(
            id="running-run-1",
            status="running",
            # La recuperación también debe reparar estados activos cuyo slot
            # haya quedado inconsistente tras una caída.
            active_slot=None,
            created_at=now,
            started_at=now,
            pages_completed=3,
            items_discovered=30,
            last_activity_at=now,
        )
        db.add_all([completed_run, pending_run, running_run])
        await db.commit()

    # Crear servicio y ejecutar recuperación (como en lifespan)
    runner = FakeRunner(pages=1, delay=0.01)
    service = CatalogSyncService(session_factory=factory, runner=runner)

    try:
        recovered_count = await service.recover_interrupted_runs()
        assert recovered_count == 2  # pending + running

        # Verificar estados finales
        async with factory() as db:
            completed = await db.get(CatalogSyncRun, "completed-run-1")
            pending = await db.get(CatalogSyncRun, "pending-run-1")
            running = await db.get(CatalogSyncRun, "running-run-1")

        # completed no se altera
        assert completed.status == "completed"
        assert completed.active_slot is None
        assert completed.pages_completed == 10
        assert completed.items_discovered == 100

        # pending -> interrupted
        assert pending.status == "interrupted"
        assert pending.active_slot is None
        assert pending.error == "Interrupted by system restart"
        assert pending.finished_at is not None

        # running -> interrupted
        assert running.status == "interrupted"
        assert running.active_slot is None
        assert running.error == "Interrupted by system restart"
        assert running.finished_at is not None

        # Verificar que se puede iniciar nueva ejecución tras recuperación
        new_run = await service.start()
        assert new_run.status == "pending"
        assert new_run.active_slot == 1

    finally:
        await service.shutdown()
        await engine.dispose()


# ---------------------------------------------------------------------------
# 7. test_get_latest_and_get_by_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_latest_and_get_by_id():
    """Cubre respuestas 200 y 404 para ambos endpoints GET."""
    engine, factory = await _make_in_memory_db()
    runner = FakeRunner(pages=1, delay=0.01)
    app, service = await _make_test_app(factory, runner)

    try:
        async with _test_client(app) as client:
            # --- Sin ejecuciones: 404 en /latest ---
            response = await client.get("/api/v1/catalog-sync/runs/latest")
            assert response.status_code == 404
            assert "No catalog sync runs found" in response.json()["detail"]

            # --- Sin ejecuciones: 404 en /runs/{id} ---
            response = await client.get("/api/v1/catalog-sync/runs/non-existent-id")
            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()

            # --- Crear una ejecución ---
            response = await client.post("/api/v1/catalog-sync/runs")
            assert response.status_code == 202
            run_id = response.json()["id"]

            # --- GET /latest -> 200 ---
            response = await client.get("/api/v1/catalog-sync/runs/latest")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == run_id
            assert data["status"] == "pending"

            # --- GET /runs/{id} -> 200 ---
            response = await client.get(f"/api/v1/catalog-sync/runs/{run_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == run_id
            assert data["status"] == "pending"
            assert data["active_slot"] == 1

            # --- Esperar a que complete ---
            await asyncio.sleep(0.1)

            # Verificar que /latest devuelve la completada
            response = await client.get("/api/v1/catalog-sync/runs/latest")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == run_id
            assert data["status"] == "completed"
            assert data["active_slot"] is None

    finally:
        await service.shutdown()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Verificación de entorno limpio (ninguna conexión externa / rutas producción)
# ---------------------------------------------------------------------------


def test_clean_environment_no_production_paths():
    """Verifica que los tests no dejan archivos en rutas de producción ni hacen conexiones externas."""
    repo_root = Path(__file__).resolve().parent.parent

    # No debe haber gateway.db en data/
    assert not (repo_root / "data" / "gateway.db").exists(), "No debe crearse data/gateway.db en tests"

    # No debe haber checkpoints en directorio de trabajo
    for directory in (repo_root, repo_root / "data"):
        if directory.exists():
            checkpoints = list(directory.glob("*checkpoint*.json"))
            assert not checkpoints, f"Checkpoints encontrados en {directory}: {checkpoints}"


# ---------------------------------------------------------------------------
# Tests adicionales de validación de esquema de respuesta (Pydantic)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_schema_validation():
    """Verifica que las respuestas cumplen el esquema CatalogSyncRunRead."""
    engine, factory = await _make_in_memory_db()
    runner = FakeRunner(pages=1, delay=0.01)
    app, service = await _make_test_app(factory, runner)

    try:
        async with _test_client(app) as client:
            # POST /runs
            response = await client.post("/api/v1/catalog-sync/runs")
            assert response.status_code == 202
            run_data = response.json()

            # Validar contra modelo Pydantic
            run_read = CatalogSyncRunRead.model_validate(run_data)
            assert run_read.id == run_data["id"]
            assert run_read.status == "pending"
            assert run_read.active_slot == 1

            # Esperar completación
            await asyncio.sleep(0.1)

            # GET /runs/{id}
            response = await client.get(f"/api/v1/catalog-sync/runs/{run_read.id}")
            assert response.status_code == 200
            run_read = CatalogSyncRunRead.model_validate(response.json())
            assert run_read.status == "completed"
            assert run_read.active_slot is None

            # GET /latest
            response = await client.get("/api/v1/catalog-sync/runs/latest")
            assert response.status_code == 200
            run_read = CatalogSyncRunRead.model_validate(response.json())
            assert run_read.status == "completed"

    finally:
        await service.shutdown()
        await engine.dispose()
