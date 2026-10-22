"""Pruebas unitarias para checkpoints de catálogo y reconciliación segura."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.services.catalog_checkpoint import (
    CHECKPOINT_VERSION,
    CatalogCheckpoint,
    CheckpointCorruptedError,
    IncompleteSnapshotError,
    IncompatibleCheckpointError,
    add_items_deduplicated,
    load_checkpoint,
    save_checkpoint,
    validate_for_reconciliation,
)


def test_save_and_load_checkpoint_atomic(tmp_path: Path) -> None:
    """Guardar un checkpoint con save_checkpoint y verificar con load_checkpoint."""
    checkpoint_path = tmp_path / "checkpoint.json"

    checkpoint = CatalogCheckpoint(
        version=CHECKPOINT_VERSION,
        provider="cuevana3",
        category="accion",
        initial_path="/peliculas/",
        next_page="/peliculas/page/2/",
        pages_completed=[1],
        items=[
            {
                "provider": "cuevana3",
                "provider_id": "/pelicula/1/",
                "title": "Test Movie",
                "url": "https://example.com/1",
                "poster": "https://example.com/poster1.jpg",
                "category": "accion",
                "media_type": "movie",
            }
        ],
        status="incomplete",
    )

    save_checkpoint(checkpoint, checkpoint_path)

    loaded = load_checkpoint(checkpoint_path)

    assert loaded.version == checkpoint.version
    assert loaded.provider == checkpoint.provider
    assert loaded.category == checkpoint.category
    assert loaded.initial_path == checkpoint.initial_path
    assert loaded.next_page == checkpoint.next_page
    assert loaded.pages_completed == checkpoint.pages_completed
    assert loaded.items == checkpoint.items
    assert loaded.status == checkpoint.status


def test_atomic_write_preserves_previous_file_on_error(tmp_path: Path) -> None:
    """Verificar que un error en escritura atómica preserva el archivo original."""
    checkpoint_path = tmp_path / "checkpoint.json"

    # Checkpoint inicial válido
    initial_checkpoint = CatalogCheckpoint(
        version=CHECKPOINT_VERSION,
        provider="cuevana3",
        category="accion",
        initial_path="/peliculas/",
        pages_completed=[1, 2, 3],
        items=[
            {"provider": "cuevana3", "provider_id": f"/pelicula/{i}/", "title": f"Movie {i}"}
            for i in range(1, 4)
        ],
        status="complete",
    )
    save_checkpoint(initial_checkpoint, checkpoint_path)

    # Verificar que el checkpoint inicial se puede cargar
    loaded = load_checkpoint(checkpoint_path)
    assert len(loaded.items) == 3
    assert loaded.pages_completed == [1, 2, 3]

    # Simular error durante escritura atómica: hacer que os.replace falle
    # Sobrescribimos el directorio para que os.replace falle
    import os

    # Bloquear el directorio eliminando permisos de escritura temporalmente
    original_mode = checkpoint_path.parent.stat().st_mode
    try:
        os.chmod(checkpoint_path.parent, 0o555)  # Solo lectura

        new_checkpoint = CatalogCheckpoint(
            version=CHECKPOINT_VERSION,
            provider="cuevana3",
            category="accion",
            initial_path="/peliculas/",
            pages_completed=[1, 2, 3, 4],
            items=[
                {"provider": "cuevana3", "provider_id": f"/pelicula/{i}/", "title": f"Movie {i}"}
                for i in range(1, 5)
            ],
            status="complete",
        )

        # La escritura debe fallar
        with pytest.raises(OSError):
            save_checkpoint(new_checkpoint, checkpoint_path)
    finally:
        # Restaurar permisos
        os.chmod(checkpoint_path.parent, original_mode)

    # Verificar que el archivo original sigue intacto
    loaded = load_checkpoint(checkpoint_path)
    assert len(loaded.items) == 3
    assert loaded.pages_completed == [1, 2, 3]


def test_add_items_deduplicated_preserves_order_and_uniqueness() -> None:
    """Verificar que add_items_deduplicated respeta orden y descarta duplicados."""
    existing = [
        {"provider": "cuevana3", "provider_id": "/a/", "title": "A"},
        {"provider": "cuevana3", "provider_id": "/b/", "title": "B"},
    ]

    new_items = [
        {"provider": "cuevana3", "provider_id": "/b/", "title": "B Duplicate"},
        {"provider": "cuevana3", "provider_id": "/c/", "title": "C"},
        {"provider": "cuevana3", "provider_id": "/a/", "title": "A Duplicate"},
        {"provider": "cuevana3", "provider_id": "/d/", "title": "D"},
    ]

    merged = add_items_deduplicated(existing, new_items)

    # Orden: A, B (existentes), C, D (nuevos en orden de llegada)
    assert [item["provider_id"] for item in merged] == ["/a/", "/b/", "/c/", "/d/"]
    assert len(merged) == 4

    # Verificar que los títulos de los originales se preservan
    assert merged[0]["title"] == "A"
    assert merged[1]["title"] == "B"
    assert merged[2]["title"] == "C"
    assert merged[3]["title"] == "D"


def test_load_checkpoint_rejects_incompatible_version(tmp_path: Path) -> None:
    """Falla si version != 1 al cargar el checkpoint."""
    checkpoint_path = tmp_path / "checkpoint.json"
    
    # Escribir JSON con versión incompatible directamente
    corrupt_data = {
        "version": 999,
        "provider": "cuevana3",
        "category": "accion",
        "initial_path": "/peliculas/",
        "pages_completed": [1, 2, 3],
        "items": [],
        "status": "complete",
    }
    checkpoint_path.write_text(json.dumps(corrupt_data), encoding="utf-8")

    with pytest.raises(CheckpointCorruptedError) as exc_info:
        load_checkpoint(checkpoint_path)

    assert "Versión de checkpoint incompatible" in str(exc_info.value)


def test_validate_for_reconciliation_rejects_mismatched_provider() -> None:
    """Falla si el proveedor no coincide."""
    checkpoint = CatalogCheckpoint(
        version=CHECKPOINT_VERSION,
        provider="otro_proveedor",
        category="accion",
        initial_path="/peliculas/",
        pages_completed=[1, 2, 3],
        items=[],
        status="complete",
    )

    with pytest.raises(IncompatibleCheckpointError) as exc_info:
        validate_for_reconciliation(checkpoint, expected_provider="cuevana3", expected_category="accion")

    assert "Proveedor del checkpoint" in str(exc_info.value)
    assert "otro_proveedor" in str(exc_info.value)


def test_validate_for_reconciliation_rejects_mismatched_category() -> None:
    """Falla si la categoría esperada no coincide con la del checkpoint."""
    checkpoint = CatalogCheckpoint(
        version=CHECKPOINT_VERSION,
        provider="cuevana3",
        category="drama",
        initial_path="/peliculas/",
        pages_completed=[1, 2, 3],
        items=[],
        status="complete",
    )

    with pytest.raises(IncompatibleCheckpointError) as exc_info:
        validate_for_reconciliation(checkpoint, expected_provider="cuevana3", expected_category="accion")

    assert "Categoría del checkpoint" in str(exc_info.value)
    assert "drama" in str(exc_info.value)
    assert "accion" in str(exc_info.value)


def test_validate_for_reconciliation_rejects_incomplete_status() -> None:
    """Lanza IncompleteSnapshotError al validar checkpoint con status incomplete."""
    checkpoint = CatalogCheckpoint(
        version=CHECKPOINT_VERSION,
        provider="cuevana3",
        category="accion",
        initial_path="/peliculas/",
        next_page="/peliculas/page/2/",
        pages_completed=[1],
        items=[{"provider": "cuevana3", "provider_id": "/a/", "title": "A"}],
        status="incomplete",
    )

    with pytest.raises(IncompleteSnapshotError) as exc_info:
        validate_for_reconciliation(checkpoint, expected_provider="cuevana3", expected_category="accion")

    assert "Snapshot incompleto" in str(exc_info.value)
    assert "incomplete" in str(exc_info.value)


@pytest.mark.asyncio
async def test_sync_from_checkpoint_does_not_open_db_on_invalid_checkpoint(tmp_path: Path) -> None:
    """Verificar que sync_from_checkpoint no abre BD si el checkpoint es inválido."""
    from scripts.sync_catalog import sync_from_checkpoint

    checkpoint_path = tmp_path / "invalid_checkpoint.json"

    # Checkpoint con status incomplete (no válido para reconciliación)
    checkpoint = CatalogCheckpoint(
        version=CHECKPOINT_VERSION,
        provider="cuevana3",
        category="accion",
        initial_path="/peliculas/",
        next_page="/peliculas/page/2/",
        pages_completed=[1],
        items=[{"provider": "cuevana3", "provider_id": "/a/", "title": "A"}],
        status="incomplete",
    )
    save_checkpoint(checkpoint, checkpoint_path)

    # Mockear AsyncSessionLocal para verificar que NO se llama
    with patch("scripts.sync_catalog.AsyncSessionLocal") as mock_session_local:
        mock_session_local.return_value.__aenter__ = AsyncMock()
        mock_session_local.return_value.__aexit__ = AsyncMock()

        # Ejecutar y esperar que falle con código 1 (sys.exit)
        with pytest.raises(SystemExit) as exc_info:
            await sync_from_checkpoint(checkpoint_path)

        assert exc_info.value.code == 1

        # Verificar que AsyncSessionLocal NUNCA fue llamado
        mock_session_local.assert_not_called()


@pytest.mark.asyncio
async def test_sync_from_checkpoint_does_not_open_db_on_corrupted_checkpoint(tmp_path: Path) -> None:
    """Verificar que no abre BD si el checkpoint está corrupto."""
    from scripts.sync_catalog import sync_from_checkpoint

    checkpoint_path = tmp_path / "corrupted_checkpoint.json"

    # Escribir JSON corrupto directamente
    checkpoint_path.write_text("{ invalid json", encoding="utf-8")

    with patch("scripts.sync_catalog.AsyncSessionLocal") as mock_session_local:
        mock_session_local.return_value.__aenter__ = AsyncMock()
        mock_session_local.return_value.__aexit__ = AsyncMock()

        with pytest.raises(SystemExit) as exc_info:
            await sync_from_checkpoint(checkpoint_path)

        assert exc_info.value.code == 1
        mock_session_local.assert_not_called()


@pytest.mark.asyncio
async def test_sync_from_checkpoint_does_not_open_db_on_mismatched_category(tmp_path: Path) -> None:
    """Verificar que no abre BD si la categoría no coincide."""
    from scripts.sync_catalog import sync_from_checkpoint

    checkpoint_path = tmp_path / "mismatch_category.json"

    # Checkpoint con categoría diferente
    checkpoint = CatalogCheckpoint(
        version=CHECKPOINT_VERSION,
        provider="cuevana3",
        category="drama",
        initial_path="/peliculas/",
        pages_completed=[1, 2, 3],
        items=[{"provider": "cuevana3", "provider_id": "/a/", "title": "A"}],
        status="complete",
    )
    save_checkpoint(checkpoint, checkpoint_path)

    with patch("scripts.sync_catalog.AsyncSessionLocal") as mock_session_local:
        mock_session_local.return_value.__aenter__ = AsyncMock()
        mock_session_local.return_value.__aexit__ = AsyncMock()

        with pytest.raises(SystemExit) as exc_info:
            await sync_from_checkpoint(checkpoint_path, expected_category="accion")

        assert exc_info.value.code == 1
        mock_session_local.assert_not_called()


@pytest.mark.asyncio
async def test_sync_from_checkpoint_matching_category_uses_temp_db(tmp_path: Path) -> None:
    """Una categoría compatible llega a reconciliación y usa solo SQLite temporal."""
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import scripts.sync_catalog as sync_module
    from src.db.database import Base
    from src.db.models import Media

    checkpoint_path = tmp_path / "complete_checkpoint.json"
    database_path = tmp_path / "gateway.db"
    checkpoint = CatalogCheckpoint(
        provider="cuevana3",
        category="accion",
        initial_path="/genero/accion/",
        pages_completed=[1],
        items=[
            {
                "provider": "cuevana3",
                "provider_id": "pelicula-prueba",
                "title": "Película de prueba",
                "url": "https://example.invalid/pelicula-prueba/",
                "poster": "https://example.invalid/poster.jpg",
                "media_type": "movie",
                "year": 2026,
                "category": "accion",
            }
        ],
        status="complete",
    )
    save_checkpoint(checkpoint, checkpoint_path)

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    try:
        with patch.object(sync_module, "AsyncSessionLocal", session_factory):
            await sync_module.sync_from_checkpoint(
                checkpoint_path,
                dry_run=True,
                expected_category="accion",
            )

        async with session_factory() as session:
            count = await session.scalar(select(func.count()).select_from(Media))
        assert count == 0
    finally:
        await engine.dispose()


@pytest.fixture
def v1_checkpoint_json() -> dict:
    """Fixture: checkpoint formato v1 (con version=1, sin stop_reason)."""
    return {
        "version": 1,
        "provider": "cuevana3",
        "category": "accion",
        "initial_path": "/peliculas/",
        "next_page": "/peliculas/page/2/",
        "pages_completed": [1, 2, 3],
        "items": [
            {
                "provider": "cuevana3",
                "provider_id": "/pelicula/1/",
                "title": "Test Movie 1",
                "url": "https://example.com/1",
                "poster": "https://example.com/poster1.jpg",
                "category": "accion",
                "media_type": "movie",
            },
            {
                "provider": "cuevana3",
                "provider_id": "/pelicula/2/",
                "title": "Test Movie 2",
                "url": "https://example.com/2",
                "poster": "https://example.com/poster2.jpg",
                "category": "accion",
                "media_type": "movie",
            },
        ],
        "status": "complete",
    }


def test_load_checkpoint_v1_format(tmp_path: Path, v1_checkpoint_json: dict) -> None:
    """Cargar checkpoint formato v1 (sin version ni stop_reason) y comprobar que se carga sin perder páginas ni ítems."""
    checkpoint_path = tmp_path / "checkpoint_v1.json"
    checkpoint_path.write_text(json.dumps(v1_checkpoint_json), encoding="utf-8")

    loaded = load_checkpoint(checkpoint_path)

    # Debe actualizar version a la actual
    assert loaded.version == CHECKPOINT_VERSION
    assert loaded.provider == "cuevana3"
    assert loaded.category == "accion"
    assert loaded.initial_path == "/peliculas/"
    assert loaded.next_page == "/peliculas/page/2/"
    assert loaded.pages_completed == [1, 2, 3]
    assert len(loaded.items) == 2
    assert loaded.items[0]["provider_id"] == "/pelicula/1/"
    assert loaded.items[1]["provider_id"] == "/pelicula/2/"
    # stop_reason debe default a None (compatibilidad v1)
    assert loaded.stop_reason is None
    # status debe preservarse
    assert loaded.status == "complete"


def test_validate_for_reconciliation_accepts_natural_end() -> None:
    """validate_for_reconciliation devuelve True (no lanza) solo con status=complete y stop_reason=natural_end."""
    checkpoint = CatalogCheckpoint(
        version=CHECKPOINT_VERSION,
        provider="cuevana3",
        category="accion",
        initial_path="/peliculas/",
        pages_completed=[1, 2, 3],
        items=[{"provider": "cuevana3", "provider_id": "/a/", "title": "A"}],
        status="complete",
        stop_reason="natural_end",
    )
    # No debe lanzar excepción
    validate_for_reconciliation(checkpoint, expected_provider="cuevana3", expected_category="accion")


def test_validate_for_reconciliation_accepts_legacy_natural_end() -> None:
    """Compatibilidad legacy: next_page=None y stop_reason=None se acepta como fin natural."""
    checkpoint = CatalogCheckpoint(
        version=CHECKPOINT_VERSION,
        provider="cuevana3",
        category="accion",
        initial_path="/peliculas/",
        next_page=None,
        pages_completed=[1, 2, 3],
        items=[{"provider": "cuevana3", "provider_id": "/a/", "title": "A"}],
        status="complete",
        stop_reason=None,
    )
    # No debe lanzar excepción (compatibilidad v1/legacy)
    validate_for_reconciliation(checkpoint, expected_provider="cuevana3", expected_category="accion")


def test_validate_for_reconciliation_rejects_repeated_page() -> None:
    """validate_for_reconciliation rechaza stop_reason=repeated_page."""
    checkpoint = CatalogCheckpoint(
        version=CHECKPOINT_VERSION,
        provider="cuevana3",
        category="accion",
        initial_path="/peliculas/",
        pages_completed=[1, 2, 3],
        items=[{"provider": "cuevana3", "provider_id": "/a/", "title": "A"}],
        status="complete",
        stop_reason="repeated_page",
    )
    with pytest.raises(IncompleteSnapshotError) as exc_info:
        validate_for_reconciliation(checkpoint, expected_provider="cuevana3", expected_category="accion")
    assert "parada no natural" in str(exc_info.value)
    assert "repeated_page" in str(exc_info.value)


def test_validate_for_reconciliation_rejects_no_new_items() -> None:
    """validate_for_reconciliation rechaza stop_reason=no_new_items."""
    checkpoint = CatalogCheckpoint(
        version=CHECKPOINT_VERSION,
        provider="cuevana3",
        category="accion",
        initial_path="/peliculas/",
        pages_completed=[1, 2, 3],
        items=[{"provider": "cuevana3", "provider_id": "/a/", "title": "A"}],
        status="complete",
        stop_reason="no_new_items",
    )
    with pytest.raises(IncompleteSnapshotError) as exc_info:
        validate_for_reconciliation(checkpoint, expected_provider="cuevana3", expected_category="accion")
    assert "parada no natural" in str(exc_info.value)
    assert "no_new_items" in str(exc_info.value)


def test_validate_for_reconciliation_rejects_max_pages() -> None:
    """validate_for_reconciliation rechaza stop_reason=max_pages."""
    checkpoint = CatalogCheckpoint(
        version=CHECKPOINT_VERSION,
        provider="cuevana3",
        category="accion",
        initial_path="/peliculas/",
        pages_completed=[1, 2, 3],
        items=[{"provider": "cuevana3", "provider_id": "/a/", "title": "A"}],
        status="complete",
        stop_reason="max_pages",
    )
    with pytest.raises(IncompleteSnapshotError) as exc_info:
        validate_for_reconciliation(checkpoint, expected_provider="cuevana3", expected_category="accion")
    assert "parada no natural" in str(exc_info.value)
    assert "max_pages" in str(exc_info.value)


def test_validate_for_reconciliation_rejects_interrupted() -> None:
    """validate_for_reconciliation rechaza stop_reason=interrupted."""
    checkpoint = CatalogCheckpoint(
        version=CHECKPOINT_VERSION,
        provider="cuevana3",
        category="accion",
        initial_path="/peliculas/",
        pages_completed=[1, 2, 3],
        items=[{"provider": "cuevana3", "provider_id": "/a/", "title": "A"}],
        status="complete",
        stop_reason="interrupted",
    )
    with pytest.raises(IncompleteSnapshotError) as exc_info:
        validate_for_reconciliation(checkpoint, expected_provider="cuevana3", expected_category="accion")
    assert "parada no natural" in str(exc_info.value)
    assert "interrupted" in str(exc_info.value)


def test_validate_for_reconciliation_rejects_incomplete_status() -> None:
    """validate_for_reconciliation rechaza status=incomplete."""
    checkpoint = CatalogCheckpoint(
        version=CHECKPOINT_VERSION,
        provider="cuevana3",
        category="accion",
        initial_path="/peliculas/",
        next_page="/peliculas/page/2/",
        pages_completed=[1],
        items=[{"provider": "cuevana3", "provider_id": "/a/", "title": "A"}],
        status="incomplete",
        stop_reason=None,
    )
    with pytest.raises(IncompleteSnapshotError) as exc_info:
        validate_for_reconciliation(checkpoint, expected_provider="cuevana3", expected_category="accion")
    assert "Snapshot incompleto" in str(exc_info.value)
    assert "incomplete" in str(exc_info.value)


def test_checkpoint_serialization_includes_version_and_stop_reason(tmp_path: Path) -> None:
    """Verificar que la serialización y guardado del checkpoint persiste version y stop_reason."""
    checkpoint_path = tmp_path / "checkpoint_serialized.json"
    checkpoint = CatalogCheckpoint(
        version=CHECKPOINT_VERSION,
        provider="cuevana3",
        category="accion",
        initial_path="/peliculas/",
        pages_completed=[1, 2, 3],
        items=[{"provider": "cuevana3", "provider_id": "/a/", "title": "A"}],
        status="complete",
        stop_reason="natural_end",
    )
    save_checkpoint(checkpoint, checkpoint_path)

    # Leer el JSON crudo para verificar campos
    raw = checkpoint_path.read_text(encoding="utf-8")
    payload = json.loads(raw)

    assert payload["version"] == CHECKPOINT_VERSION
    assert payload["stop_reason"] == "natural_end"
    assert payload["status"] == "complete"
    assert payload["provider"] == "cuevana3"
    assert payload["category"] == "accion"
    assert len(payload["pages_completed"]) == 3
    assert len(payload["items"]) == 1

    # Cargar de nuevo y verificar round-trip
    loaded = load_checkpoint(checkpoint_path)
    assert loaded.version == CHECKPOINT_VERSION
    assert loaded.stop_reason == "natural_end"
    assert loaded.status == "complete"
    assert loaded.pages_completed == [1, 2, 3]
    assert len(loaded.items) == 1


def test_checkpoint_serialization_with_stop_reason_none(tmp_path: Path) -> None:
    """Verificar serialización con stop_reason=None."""
    checkpoint_path = tmp_path / "checkpoint_none_stop.json"
    checkpoint = CatalogCheckpoint(
        version=CHECKPOINT_VERSION,
        provider="cuevana3",
        category="accion",
        initial_path="/peliculas/",
        next_page=None,
        pages_completed=[1, 2],
        items=[{"provider": "cuevana3", "provider_id": "/a/", "title": "A"}],
        status="complete",
        stop_reason=None,
    )
    save_checkpoint(checkpoint, checkpoint_path)

    raw = checkpoint_path.read_text(encoding="utf-8")
    payload = json.loads(raw)

    assert payload["version"] == CHECKPOINT_VERSION
    assert "stop_reason" in payload, "stop_reason debe estar presente en el JSON"
    assert payload["stop_reason"] is None
    assert payload["next_page"] is None
    assert payload["status"] == "complete"

    loaded = load_checkpoint(checkpoint_path)
    assert loaded.version == CHECKPOINT_VERSION
    assert loaded.stop_reason is None
    assert loaded.next_page is None
    assert loaded.status == "complete"
