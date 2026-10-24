"""Pruebas de sincronización incremental e idempotencia del catálogo.

Cubre la persistencia por página, la reanudación/replay sin duplicados, la
normalización de títulos con año pegado y las condiciones de parada del
crawler (página repetida, N páginas sin novedades y límite de páginas),
verificando que ninguna parada artificial habilita bajas.

Todas las pruebas usan SQLite en memoria o archivos en ``tmp_path``; nunca
tocan ``data/gateway.db`` ni dejan checkpoints en el directorio de trabajo.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.adapters.cuevana3 import Cuevana3Adapter
from src.db.database import Base
from src.db.models import CatalogSyncPage, CatalogSyncRun, Media, Source
from src.services.catalog_checkpoint import (
    CatalogCheckpoint,
    IncompleteSnapshotError,
    save_checkpoint,
    validate_for_reconciliation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _page_html(items: list[tuple[str, str, int | None]], next_href: str | None) -> str:
    """Construye el HTML de una página de catálogo.

    ``items`` es una lista de ``(title, href, year)``. ``next_href`` es el
    enlace ``a.next.page-numbers`` (``None`` para el fin natural).
    """
    posts = []
    for title, href, year in items:
        year_span = f'<span class="Year">{year}</span>' if year is not None else ""
        posts.append(
            f'<div class="TPost"><a href="{href}">{title}</a>'
            f'<figure class="Objf"><img src="https://example.com/poster.jpg"></figure>'
            f"{year_span}</div>"
        )
    body = "".join(posts)
    if next_href:
        body += f'<a class="next page-numbers" href="{next_href}">Siguiente</a>'
    return f"<html><body>{body}</body></html>"


def _build_pages(
    page_items: list[list[tuple[str, str, int | None]]],
    next_links: list[str | None],
) -> dict[str, str]:
    """Construye un mapa ``page_path -> html`` para el cliente simulado."""
    pages: dict[str, str] = {}
    for i, (items, nxt) in enumerate(zip(page_items, next_links), start=1):
        path = "/peliculas/" if i == 1 else f"/peliculas/page/{i}/"
        pages[path] = _page_html(items, nxt)
    return pages


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    """Cliente HTTP simulado que sirve páginas por ruta."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.requests: list[str] = []

    async def get(self, page_path: str) -> _FakeResponse:
        self.requests.append(page_path)
        return _FakeResponse(self.pages[page_path])


async def _make_db(db_path: Path):
    """Crea un motor SQLite temporal con el esquema completo."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


def _movie_item(provider_id: str, title: str, year: int | None = None) -> dict:
    """Construye un ítem de catálogo tipo película."""
    return {
        "provider": "cuevana3",
        "provider_id": provider_id,
        "title": title,
        "url": f"https://example.com/pelicula/{provider_id}/",
        "poster": "https://example.com/poster.jpg",
        "media_type": "movie",
        "year": year,
        "category": None,
    }


async def _counts(factory) -> tuple[int, int]:
    """Devuelve (n_media, n_sources) en la BD temporal."""
    async with factory() as db:
        media = await db.scalar(select(func.count()).select_from(Media))
        sources = await db.scalar(select(func.count()).select_from(Source))
    return int(media or 0), int(sources or 0)


async def _sync_run(factory, run_id: str) -> CatalogSyncRun | None:
    async with factory() as db:
        return await db.get(CatalogSyncRun, run_id)


async def _sync_pages(factory, run_id: str) -> list[CatalogSyncPage]:
    async with factory() as db:
        result = await db.execute(select(CatalogSyncPage).where(CatalogSyncPage.run_id == run_id))
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# 1. Persistencia incremental por página
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_incremental_upsert_per_page(tmp_path: Path) -> None:
    """Tras la página 1 las películas ya están confirmadas antes de la página 2."""
    from scripts.sync_catalog import persist_page_batch

    engine, factory = await _make_db(tmp_path / "test.db")
    checkpoint_path = tmp_path / "ckpt.json"

    page1 = [
        ("Pelicula Uno", "/pelicula/uno/", 2020),
        ("Pelicula Dos", "/pelicula/dos/", 2021),
    ]
    page2 = [
        ("Pelicula Tres", "/pelicula/tres/", 2022),
        ("Pelicula Cuatro", "/pelicula/cuatro/", 2023),
    ]
    pages = _build_pages(
        [page1, page2],
        ["/peliculas/page/2/", None],
    )
    adapter = Cuevana3Adapter()
    adapter._client = _FakeClient(pages)

    page1_confirmed_before_page2 = False

    async def on_page(items, checkpoint) -> None:
        await persist_page_batch(factory, items, checkpoint, checkpoint_path)
        if checkpoint.pages_completed == [1]:
            # La página 1 ya debe estar confirmada en la BD antes de la página 2.
            media, _ = await _counts(factory)
            assert media == len(page1)
            nonlocal page1_confirmed_before_page2
            page1_confirmed_before_page2 = True

    try:
        with patch("src.adapters.cuevana3.asyncio.sleep", new=AsyncMock(return_value=None)):
            checkpoint = await adapter.discover_resumable(
                checkpoint_path=checkpoint_path,
                on_page=on_page,
            )
    finally:
        await engine.dispose()

    assert page1_confirmed_before_page2 is True
    assert checkpoint.status == "complete"
    assert checkpoint.stop_reason == "natural_end"
    media, sources = await _counts(factory)
    assert media == 4
    assert sources == 4


# ---------------------------------------------------------------------------
# 2. Reanudación y replay idempotente
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_and_replay_idempotency(tmp_path: Path) -> None:
    """Reanudar o repetir una página no duplica registros en Media ni Source."""
    from scripts.sync_catalog import persist_page_batch

    engine, factory = await _make_db(tmp_path / "test.db")
    checkpoint_path = tmp_path / "ckpt.json"

    page1 = [
        ("Pelicula Uno", "/pelicula/uno/", 2020),
        ("Pelicula Dos", "/pelicula/dos/", 2021),
    ]
    page2 = [
        ("Pelicula Tres", "/pelicula/tres/", 2022),
    ]
    page1_items = [
        _movie_item("uno", "Pelicula Uno", 2020),
        _movie_item("dos", "Pelicula Dos", 2021),
    ]
    page2_items = [_movie_item("tres", "Pelicula Tres", 2022)]

    # --- Primera corrida: página 1 persistida, luego parada artificial. ---
    ckpt1 = CatalogCheckpoint(
        provider="cuevana3",
        category=None,
        initial_path="/peliculas/",
        next_page="/peliculas/page/2/",
        pages_completed=[1],
        items=page1_items,
        status="incomplete",
    )
    await persist_page_batch(factory, page1_items, ckpt1, checkpoint_path)
    save_checkpoint(ckpt1, checkpoint_path)

    # --- Reanudación: solo se procesa la página 2 (next_page del checkpoint). ---
    pages = {"/peliculas/page/2/": _page_html(page2, None)}
    adapter = Cuevana3Adapter()
    adapter._client = _FakeClient(pages)

    try:
        with patch("src.adapters.cuevana3.asyncio.sleep", new=AsyncMock(return_value=None)):
            checkpoint = await adapter.discover_resumable(
                checkpoint_path=checkpoint_path,
                on_page=lambda items, ckpt: persist_page_batch(factory, items, ckpt, checkpoint_path),
            )
    finally:
        await engine.dispose()

    assert checkpoint.status == "complete"
    assert checkpoint.stop_reason == "natural_end"
    media, sources = await _counts(factory)
    assert media == 3
    assert sources == 3

    # --- Replay: repetir la carga de la misma página no duplica nada. ---
    replay_dir = tmp_path / "replay"
    replay_dir.mkdir()
    engine2, factory2 = await _make_db(replay_dir / "replay.db")
    try:
        ckpt_replay = CatalogCheckpoint(
            provider="cuevana3",
            category=None,
            initial_path="/peliculas/",
            next_page=None,
            pages_completed=[1],
            items=[_movie_item("uno", "Pelicula Uno", 2020)],
            status="incomplete",
        )
        added1, _ = await persist_page_batch(factory2, page1_items, ckpt_replay, tmp_path / "replay.json")
        added2, _ = await persist_page_batch(factory2, page1_items, ckpt_replay, tmp_path / "replay.json")
        assert added1 == len(page1_items)
        assert added2 == 0  # segunda carga: todo actualizado, nada nuevo
        media, sources = await _counts(factory2)
        assert media == len(page1_items)
        assert sources == len(page1_items)
    finally:
        await engine2.dispose()


# ---------------------------------------------------------------------------
# 3. Normalización de títulos con año pegado
# ---------------------------------------------------------------------------


def test_title_normalization() -> None:
    """Un ítem con año 2018 y título '2018Aquaman' se persiste como 'Aquaman';
    '2020Aquaman' con año 2018 no se altera."""
    # Regla implementada por _normalize_title_with_year.
    assert Cuevana3Adapter._normalize_title_with_year("2018Aquaman", 2018) == "Aquaman"
    assert Cuevana3Adapter._normalize_title_with_year("2020Aquaman", 2018) == "2020Aquaman"


@pytest.mark.asyncio
async def test_title_normalization_persisted(tmp_path: Path) -> None:
    """El título normalizado llega a la BD a través del flujo de descubrimiento."""
    from scripts.sync_catalog import persist_page_batch

    engine, factory = await _make_db(tmp_path / "test.db")
    checkpoint_path = tmp_path / "ckpt.json"

    # "2018Aquaman" con span.Year=2018 -> debe persistirse como "Aquaman".
    pages = _build_pages(
        [[("2018Aquaman", "/pelicula/aquaman/", 2018)]],
        [None],
    )
    adapter = Cuevana3Adapter()
    adapter._client = _FakeClient(pages)

    try:
        with patch("src.adapters.cuevana3.asyncio.sleep", new=AsyncMock(return_value=None)):
            checkpoint = await adapter.discover_resumable(
                checkpoint_path=checkpoint_path,
                on_page=lambda items, ckpt: persist_page_batch(factory, items, ckpt, checkpoint_path),
            )
    finally:
        await engine.dispose()

    assert checkpoint.items[0]["title"] == "Aquaman"
    async with factory() as db:
        media = (await db.execute(select(Media))).scalars().first()
    assert media is not None
    assert media.title == "Aquaman"


# ---------------------------------------------------------------------------
# 4. Condiciones de parada del crawler
# ---------------------------------------------------------------------------


async def _run_discover(pages: dict[str, str], page_limit: int | None = None):
    """Ejecuta discover_resumable con un cliente simulado y sin delays."""
    adapter = Cuevana3Adapter()
    adapter._client = _FakeClient(pages)
    checkpoint_path = Path("/tmp") / "test_catalog_sync_stop.json"
    try:
        with patch("src.adapters.cuevana3.asyncio.sleep", new=AsyncMock(return_value=None)):
            return await adapter.discover_resumable(
                checkpoint_path=checkpoint_path,
                page_limit=page_limit,
            )
    finally:
        checkpoint_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_stop_conditions_repeated_page() -> None:
    """Página repetida detiene el crawler con stop_reason='repeated_page'."""
    page1 = [("A", "/pelicula/a/", 2020), ("B", "/pelicula/b/", 2021)]
    page2 = [("A", "/pelicula/a/", 2020), ("B", "/pelicula/b/", 2021)]
    pages = _build_pages([page1, page2], ["/peliculas/page/2/", "/peliculas/page/3/"])

    checkpoint = await _run_discover(pages)

    assert checkpoint.status == "incomplete"
    assert checkpoint.stop_reason == "repeated_page"
    # Jamás apto para bajas: la reconciliación debe rechazarlo.
    with pytest.raises(IncompleteSnapshotError):
        validate_for_reconciliation(checkpoint, expected_provider="cuevana3")


@pytest.mark.asyncio
async def test_pages_without_new_items_continue_to_natural_end() -> None:
    """Páginas sin novedades no detienen el crawler antes del fin natural."""
    # Página 1 introduce A,B,C. Las páginas 2-4 solo reordenan subconjuntos
    # ya vistos (sin ítems nuevos y sin repetir la huella exacta de una página).
    page1 = [("A", "/pelicula/a/", 2020), ("B", "/pelicula/b/", 2021), ("C", "/pelicula/c/", 2022)]
    page2 = [("A", "/pelicula/a/", 2020), ("B", "/pelicula/b/", 2021)]
    page3 = [("A", "/pelicula/a/", 2020), ("C", "/pelicula/c/", 2022)]
    page4 = [("B", "/pelicula/b/", 2021), ("C", "/pelicula/c/", 2022)]
    page5 = [("A", "/pelicula/a/", 2020)]
    pages = _build_pages(
        [page1, page2, page3, page4, page5],
        [
            "/peliculas/page/2/",
            "/peliculas/page/3/",
            "/peliculas/page/4/",
            "/peliculas/page/5/",
            None,
        ],
    )

    checkpoint = await _run_discover(pages)

    assert checkpoint.status == "complete"
    assert checkpoint.stop_reason == "natural_end"
    validate_for_reconciliation(checkpoint, expected_provider="cuevana3")


@pytest.mark.asyncio
async def test_stop_conditions_max_pages() -> None:
    """El fusible max_pages detiene el crawler con stop_reason='max_pages'."""
    page1 = [("A", "/pelicula/a/", 2020)]
    page2 = [("B", "/pelicula/b/", 2021)]
    page3 = [("C", "/pelicula/c/", 2022)]
    pages = _build_pages(
        [page1, page2, page3],
        ["/peliculas/page/2/", "/peliculas/page/3/", "/peliculas/page/4/"],
    )

    checkpoint = await _run_discover(pages, page_limit=2)

    assert checkpoint.status == "incomplete"
    assert checkpoint.stop_reason == "max_pages"
    assert checkpoint.pages_completed == [1, 2]
    with pytest.raises(IncompleteSnapshotError):
        validate_for_reconciliation(checkpoint, expected_provider="cuevana3")


# ---------------------------------------------------------------------------
# 5. Entorno limpio
# ---------------------------------------------------------------------------


def test_clean_environment() -> None:
    """El test no deja data/gateway.db ni checkpoints en el directorio de trabajo."""
    repo_root = Path(__file__).resolve().parent.parent
    assert not (repo_root / "data" / "gateway.db").exists()
    for directory in (repo_root, repo_root / "data"):
        if directory.exists():
            assert not list(directory.glob("*checkpoint*.json"))


# ---------------------------------------------------------------------------
# 6. Sincronización de page_url (PASO 4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_page_url_persisted_on_creation(tmp_path: Path) -> None:
    """Al crear una fuente nueva, page_url se guarda con el valor de item["url"]"""
    from scripts.sync_catalog import persist_page_batch

    engine, factory = await _make_db(tmp_path / "test.db")
    checkpoint_path = tmp_path / "ckpt.json"

    # Ítem con url (URL completa de la página del contenido)
    items = [
        {
            "provider": "cuevana3",
            "provider_id": "movie-1",
            "title": "Pelicula Test",
            "url": "https://cuevana3.io/pelicula/movie-1/",
            "poster": "https://example.com/poster.jpg",
            "media_type": "movie",
            "year": 2023,
            "category": None,
        }
    ]

    ckpt = CatalogCheckpoint(
        provider="cuevana3",
        category=None,
        initial_path="/peliculas/",
        next_page=None,
        pages_completed=[1],
        items=items,
        status="incomplete",
    )

    added, updated = await persist_page_batch(factory, items, ckpt, checkpoint_path)
    assert added == 1
    assert updated == 0

    async with factory() as db:
        source = (await db.execute(select(Source))).scalars().first()
    assert source is not None
    assert source.page_url == "https://cuevana3.io/pelicula/movie-1/"

    await engine.dispose()


@pytest.mark.asyncio
async def test_page_url_updated_on_existing_source(tmp_path: Path) -> None:
    """Al actualizar una fuente existente con nuevo item["url"], page_url se actualiza."""
    from scripts.sync_catalog import persist_page_batch

    engine, factory = await _make_db(tmp_path / "test.db")
    checkpoint_path = tmp_path / "ckpt.json"

    # Primera carga: crea la fuente con page_url inicial
    items_v1 = [
        {
            "provider": "cuevana3",
            "provider_id": "movie-1",
            "title": "Pelicula Test",
            "url": "https://cuevana3.io/pelicula/movie-1/",
            "poster": "https://example.com/poster.jpg",
            "media_type": "movie",
            "year": 2023,
            "category": None,
        }
    ]
    ckpt1 = CatalogCheckpoint(
        provider="cuevana3",
        category=None,
        initial_path="/peliculas/",
        next_page=None,
        pages_completed=[1],
        items=items_v1,
        status="incomplete",
    )
    await persist_page_batch(factory, items_v1, ckpt1, checkpoint_path)

    # Segunda carga: mismo provider_id pero URL distinta (ej. cambio de dominio/ruta)
    items_v2 = [
        {
            "provider": "cuevana3",
            "provider_id": "movie-1",
            "title": "Pelicula Test",
            "url": "https://nuevo-dominio.io/pelicula/movie-1/",
            "poster": "https://example.com/poster.jpg",
            "media_type": "movie",
            "year": 2023,
            "category": None,
        }
    ]
    ckpt2 = CatalogCheckpoint(
        provider="cuevana3",
        category=None,
        initial_path="/peliculas/",
        next_page=None,
        pages_completed=[1],
        items=items_v2,
        status="incomplete",
    )
    added, updated = await persist_page_batch(factory, items_v2, ckpt2, checkpoint_path)
    assert added == 0
    assert updated == 1

    async with factory() as db:
        source = (await db.execute(select(Source))).scalars().first()
    assert source.page_url == "https://nuevo-dominio.io/pelicula/movie-1/"

    await engine.dispose()


@pytest.mark.asyncio
async def test_page_url_preserved_when_incoming_none_or_missing(tmp_path: Path) -> None:
    """Si el lote entrante no trae url o viene None, page_url preexistente se conserva."""
    from scripts.sync_catalog import persist_page_batch

    engine, factory = await _make_db(tmp_path / "test.db")
    checkpoint_path = tmp_path / "ckpt.json"

    # Crear fuente con page_url inicial
    items_v1 = [
        {
            "provider": "cuevana3",
            "provider_id": "movie-1",
            "title": "Pelicula Test",
            "url": "https://original.io/pelicula/movie-1/",
            "poster": "https://example.com/poster.jpg",
            "media_type": "movie",
            "year": 2023,
            "category": None,
        }
    ]
    ckpt1 = CatalogCheckpoint(
        provider="cuevana3",
        category=None,
        initial_path="/peliculas/",
        next_page=None,
        pages_completed=[1],
        items=items_v1,
        status="incomplete",
    )
    await persist_page_batch(factory, items_v1, ckpt1, checkpoint_path)

    # Actualización SIN url en el item
    items_v2_no_url = [
        {
            "provider": "cuevana3",
            "provider_id": "movie-1",
            "title": "Pelicula Test Actualizada",
            # "url" omitido intencionalmente
            "poster": "https://example.com/poster-new.jpg",
            "media_type": "movie",
            "year": 2023,
            "category": None,
        }
    ]
    ckpt2 = CatalogCheckpoint(
        provider="cuevana3",
        category=None,
        initial_path="/peliculas/",
        next_page=None,
        pages_completed=[1],
        items=items_v2_no_url,
        status="incomplete",
    )
    await persist_page_batch(factory, items_v2_no_url, ckpt2, checkpoint_path)

    async with factory() as db:
        source = (await db.execute(select(Source))).scalars().first()
    assert source.page_url == "https://original.io/pelicula/movie-1/"

    # Actualización con url = None explícito
    items_v3_none = [
        {
            "provider": "cuevana3",
            "provider_id": "movie-1",
            "title": "Pelicula Test v3",
            "url": None,
            "poster": "https://example.com/poster-v3.jpg",
            "media_type": "movie",
            "year": 2023,
            "category": None,
        }
    ]
    ckpt3 = CatalogCheckpoint(
        provider="cuevana3",
        category=None,
        initial_path="/peliculas/",
        next_page=None,
        pages_completed=[1],
        items=items_v3_none,
        status="incomplete",
    )
    await persist_page_batch(factory, items_v3_none, ckpt3, checkpoint_path)

    async with factory() as db:
        source = (await db.execute(select(Source))).scalars().first()
    assert source.page_url == "https://original.io/pelicula/movie-1/"

    await engine.dispose()


@pytest.mark.asyncio
async def test_sync_from_checkpoint_backward_compatibility_no_url(tmp_path: Path) -> None:
    """Checkpoint antiguo sin campo url en los items no rompe la reconciliacion."""
    from scripts.sync_catalog import sync_from_checkpoint
    from src.services.catalog_checkpoint import CatalogCheckpoint, save_checkpoint

    engine, factory = await _make_db(tmp_path / "test.db")
    checkpoint_path = tmp_path / "ckpt_old.json"

    # Simular checkpoint antiguo (sin campo 'url' en los items)
    # Como fue guardado antes de que existiera el campo
    old_items = [
        {
            "provider": "cuevana3",
            "provider_id": "movie-old",
            "title": "Pelicula Antigua",
            # Sin campo 'url' - compatibilidad hacia atras
            "poster": "https://example.com/old.jpg",
            "media_type": "movie",
            "year": 2020,
            "category": None,
        }
    ]
    old_checkpoint = CatalogCheckpoint(
        provider="cuevana3",
        category=None,
        initial_path="/peliculas/",
        next_page=None,
        pages_completed=[1, 2, 3],
        items=old_items,
        status="complete",
        stop_reason="natural_end",
    )
    save_checkpoint(old_checkpoint, checkpoint_path)

    # Ejecutar reconciliación desde ese checkpoint - no debe fallar.
    # sync_from_checkpoint usa AsyncSessionLocal; la redirigimos a la BD temporal
    # para no tocar la base de datos real.
    with patch("scripts.sync_catalog.AsyncSessionLocal", factory):
        await sync_from_checkpoint(
            checkpoint_path,
            limit=None,
            dry_run=False,  # Sin dry_run para que se persista
            allow_large_delete=False,
            enrich_new=False,
        )

    # Verificar que la fuente se creó (sin page_url porque no venía en el item)
    async with factory() as db:
        source = (await db.execute(select(Source))).scalars().first()
    assert source is not None
    assert source.url == "movie-old"
    assert source.page_url is None  # No había url en el checkpoint antiguo

    await engine.dispose()


@pytest.mark.asyncio
async def test_transactional_page_commit(tmp_path: Path) -> None:
    from scripts.sync_catalog import persist_page_batch

    engine, factory = await _make_db(tmp_path / "test.db")
    checkpoint_path = tmp_path / "ckpt.json"
    run_id = "run-commit"
    async with factory() as db:
        db.add(CatalogSyncRun(id=run_id, status="running", phase="discovering", checkpoint_path=str(checkpoint_path)))
        await db.commit()

    items = [_movie_item("m-1", "Pelicula 1", 2024)]
    checkpoint = CatalogCheckpoint(provider="cuevana3", category=None, initial_path="/peliculas/", next_page=None, pages_completed=[1], items=items, status="incomplete")
    await persist_page_batch(factory, items, checkpoint, checkpoint_path, run_id=run_id, page_number=1, page_url="/peliculas/", next_page_url=None)

    media, sources = await _counts(factory)
    assert media == 1
    assert sources == 1
    pages = await _sync_pages(factory, run_id)
    assert len(pages) == 1
    page = pages[0]
    assert page.page_number == 1
    assert page.seen == 1
    assert page.unique == 1
    assert page.inserted == 1
    run = await _sync_run(factory, run_id)
    assert run is not None
    assert run.items_seen == 1
    assert run.items_unique == 1
    assert run.items_inserted == 1
    assert run.items_updated == 0
    assert run.items_unchanged == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_rollback_on_failure(tmp_path: Path) -> None:
    from scripts.sync_catalog import persist_page_batch

    engine, factory = await _make_db(tmp_path / "test.db")
    checkpoint_path = tmp_path / "ckpt.json"
    run_id = "run-rollback"
    async with factory() as db:
        db.add(CatalogSyncRun(id=run_id, status="running", phase="discovering", checkpoint_path=str(checkpoint_path)))
        await db.commit()

    items = [_movie_item("m-1", "Pelicula 1", 2024)]
    checkpoint = CatalogCheckpoint(provider="cuevana3", category=None, initial_path="/peliculas/", next_page=None, pages_completed=[1], items=items, status="incomplete")

    with patch("scripts.sync_catalog.save_checkpoint", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            await persist_page_batch(factory, items, checkpoint, checkpoint_path, run_id=run_id, page_number=1, page_url="/peliculas/", next_page_url=None)

    media, sources = await _counts(factory)
    assert media == 1
    assert sources == 1
    assert len(await _sync_pages(factory, run_id)) == 1
    run = await _sync_run(factory, run_id)
    assert run is not None
    assert run.items_seen == 1
    assert not checkpoint_path.exists()
    await engine.dispose()


@pytest.mark.asyncio
async def test_idempotent_replay(tmp_path: Path) -> None:
    from scripts.sync_catalog import persist_page_batch

    engine, factory = await _make_db(tmp_path / "test.db")
    checkpoint_path = tmp_path / "ckpt.json"
    run_id = "run-replay"
    async with factory() as db:
        db.add(CatalogSyncRun(id=run_id, status="running", phase="discovering", checkpoint_path=str(checkpoint_path)))
        await db.commit()

    items = [_movie_item("m-1", "Pelicula 1", 2024)]
    checkpoint = CatalogCheckpoint(provider="cuevana3", category=None, initial_path="/peliculas/", next_page=None, pages_completed=[1], items=items, status="incomplete")
    await persist_page_batch(factory, items, checkpoint, checkpoint_path, run_id=run_id, page_number=1, page_url="/peliculas/", next_page_url=None)
    before = await _sync_run(factory, run_id)
    await persist_page_batch(factory, items, checkpoint, checkpoint_path, run_id=run_id, page_number=1, page_url="/peliculas/", next_page_url=None)

    media, sources = await _counts(factory)
    assert media == 1
    assert sources == 1
    run = await _sync_run(factory, run_id)
    assert run is not None
    assert run.items_seen == 2
    assert run.items_unique == 2
    assert run.items_inserted == 1
    assert len(await _sync_pages(factory, run_id)) == 1
    assert before is not None and before.items_seen == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_counters_updated_vs_unchanged(tmp_path: Path) -> None:
    from scripts.sync_catalog import persist_page_batch

    engine, factory = await _make_db(tmp_path / "test.db")
    checkpoint_path = tmp_path / "ckpt.json"
    run_id = "run-counters"
    async with factory() as db:
        db.add(CatalogSyncRun(id=run_id, status="running", phase="discovering", checkpoint_path=str(checkpoint_path)))
        await db.commit()

    base_item = _movie_item("m-1", "Pelicula 1", 2024)
    checkpoint = CatalogCheckpoint(provider="cuevana3", category=None, initial_path="/peliculas/", next_page=None, pages_completed=[1], items=[base_item], status="incomplete")
    await persist_page_batch(factory, [base_item], checkpoint, checkpoint_path, run_id=run_id, page_number=1, page_url="/peliculas/", next_page_url=None)
    same_item = dict(base_item)
    await persist_page_batch(factory, [same_item], checkpoint, checkpoint_path, run_id=run_id, page_number=2, page_url="/peliculas/page/2/", next_page_url=None)
    changed_item = dict(base_item)
    changed_item["title"] = "Pelicula 1 Remaster"
    await persist_page_batch(factory, [changed_item], checkpoint, checkpoint_path, run_id=run_id, page_number=3, page_url="/peliculas/page/3/", next_page_url=None)

    run = await _sync_run(factory, run_id)
    assert run is not None
    assert run.items_unchanged >= 1
    assert run.items_updated >= 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_resume_from_next_page(tmp_path: Path) -> None:
    from scripts.sync_catalog import persist_page_batch

    engine, factory = await _make_db(tmp_path / "test.db")
    checkpoint_path = tmp_path / "ckpt.json"
    run_id = "run-resume"
    async with factory() as db:
        db.add(CatalogSyncRun(id=run_id, status="running", phase="discovering", checkpoint_path=str(checkpoint_path)))
        await db.commit()

    page1 = [_movie_item("m-1", "Pelicula 1", 2024)]
    page2 = [_movie_item("m-2", "Pelicula 2", 2025)]
    checkpoint = CatalogCheckpoint(provider="cuevana3", category=None, initial_path="/peliculas/", next_page="/peliculas/page/2/", pages_completed=[1], items=page1, status="incomplete")
    await persist_page_batch(factory, page1, checkpoint, checkpoint_path, run_id=run_id, page_number=1, page_url="/peliculas/", next_page_url="/peliculas/page/2/")
    await persist_page_batch(factory, page2, checkpoint, checkpoint_path, run_id=run_id, page_number=2, page_url="/peliculas/page/2/", next_page_url=None)

    media, sources = await _counts(factory)
    assert media == 2
    assert sources == 2
    run = await _sync_run(factory, run_id)
    assert run is not None
    assert run.items_inserted == 2
    assert run.pages_completed == 2
    assert len(await _sync_pages(factory, run_id)) == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_persist_page_batch_records_positive_presence(tmp_path: Path) -> None:
    from scripts.sync_catalog import persist_page_batch

    engine, factory = await _make_db(tmp_path / "presence-new.db")
    checkpoint_path = tmp_path / "presence-new.json"
    item = _movie_item("presence-new", "Presente", 2026)
    checkpoint = CatalogCheckpoint(
        provider="cuevana3",
        category=None,
        initial_path="/peliculas/",
        pages_completed=[1],
        items=[item],
        status="incomplete",
    )

    await persist_page_batch(
        factory, [item], checkpoint, checkpoint_path, run_id="test-run-1"
    )

    async with factory() as db:
        source = (await db.execute(select(Source))).scalar_one()
        assert source.catalog_presence == "present"
        assert source.last_seen_at is not None
        assert source.last_seen_run_id == "test-run-1"
        assert source.missing_since is None
        assert source.consecutive_misses == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_persist_page_batch_restores_missing_without_metadata_change(
    tmp_path: Path,
) -> None:
    from scripts.sync_catalog import persist_page_batch

    engine, factory = await _make_db(tmp_path / "presence-return.db")
    checkpoint_path = tmp_path / "presence-return.json"
    item = _movie_item("presence-return", "Regresa", 2026)
    checkpoint = CatalogCheckpoint(
        provider="cuevana3",
        category=None,
        initial_path="/peliculas/",
        pages_completed=[1],
        items=[item],
        status="incomplete",
    )
    await persist_page_batch(factory, [item], checkpoint, checkpoint_path)
    missing_since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with factory() as db:
        source = (await db.execute(select(Source))).scalar_one()
        source.catalog_presence = "missing"
        source.missing_since = missing_since
        source.consecutive_misses = 2
        await db.commit()

    added, updated = await persist_page_batch(
        factory, [item], checkpoint, checkpoint_path, run_id="test-run-return"
    )

    assert (added, updated) == (0, 1)
    async with factory() as db:
        source = (await db.execute(select(Source))).scalar_one()
        assert source.catalog_presence == "present"
        assert source.last_seen_at is not None
        assert source.last_seen_run_id == "test-run-return"
        assert source.missing_since is None
        assert source.consecutive_misses == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_sync_from_checkpoint_records_and_restores_positive_presence(
    tmp_path: Path,
) -> None:
    from scripts.sync_catalog import sync_from_checkpoint

    engine, factory = await _make_db(tmp_path / "presence-checkpoint.db")
    checkpoint_path = tmp_path / "presence-checkpoint.json"
    returning = _movie_item("returning", "Regresa", 2025)
    new_item = _movie_item("new", "Nueva", 2026)
    checkpoint = CatalogCheckpoint(
        provider="cuevana3",
        category=None,
        initial_path="/peliculas/",
        pages_completed=[1],
        items=[returning, new_item],
        status="complete",
        stop_reason="natural_end",
    )
    save_checkpoint(checkpoint, checkpoint_path)
    async with factory() as db:
        media = Media(
            title="Regresa",
            original_title="Regresa",
            media_type="movie",
            year=2025,
        )
        media.sources.append(
            Source(
                provider="cuevana3",
                url="returning",
                page_url=returning["url"],
                quality="auto",
                language="es",
                catalog_presence="missing",
                missing_since=datetime(2026, 1, 1, tzinfo=timezone.utc),
                consecutive_misses=2,
            )
        )
        db.add(media)
        await db.commit()

    with patch("scripts.sync_catalog.AsyncSessionLocal", factory):
        await sync_from_checkpoint(checkpoint_path, run_id="checkpoint-run")

    async with factory() as db:
        sources = {
            source.url: source
            for source in (await db.execute(select(Source))).scalars().all()
        }
        assert set(sources) == {"returning", "new"}
        for source in sources.values():
            assert source.catalog_presence == "present"
            assert source.last_seen_at is not None
            assert source.last_seen_run_id == "checkpoint-run"
            assert source.missing_since is None
            assert source.consecutive_misses == 0
    await engine.dispose()
