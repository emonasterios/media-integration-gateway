"""Tests de integración sin red para el inventario por categorías.

Valida el refactorizado del inventario (`src/services/catalog_inventory.py`)
que persiste en SQLite y recorre estrictamente ``1..last_page`` obtenido de
la paginación numérica (``a.page-link`` / ``.page-numbers``), sin usar
``a.next``, sin abrir fichas individuales (``get_details``) ni resolvers de
video (``resolve_playback``).

La suite usa ``unittest.mock`` (AsyncMock) para simular las respuestas HTTP,
siguiendo el patrón de fixtures ya existente en ``tests/test_cuevana3.py``.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.adapters.cuevana3 import (
    Cuevana3Adapter,
    extract_last_page,
    extract_menu_categories,
)
from src.services.catalog_inventory import (
    CatalogInventoryDB,
    CatalogInventoryService,
    get_inventory_status,
)


# ----------------------------------------------------------------------
# Helpers HTML
# ----------------------------------------------------------------------

def make_menu_html(categories: list[tuple[str, str]]) -> str:
    """Genera HTML con enlaces ``/genero/<slug>/`` y nombre visible.

    Args:
        categories: lista de pares ``(slug, name)``.

    Returns:
        HTML con anclas de menú de categorías.
    """
    parts = ["<!DOCTYPE html><html><body>"]
    for slug, name in categories:
        parts.append(
            f'<a href="/genero/{slug}/" class="nav-categories">'
            f'{name}</a>'
        )
    parts.append("</body></html>")
    return "\n".join(parts)


def make_pagination_bar(current: int, last_page: int) -> str:
    """Genera HTML de paginación numérica con ``a.page-link``.

    Incluye un enlace a la última página (``a.next.page-numbers``) con
    ``last_page + 1`` para verificar que ``extract_last_page`` ignora ``a.next``
    y solo toma el número máximo de los enlaces numéricos.
    """
    parts = ['<nav class="pagination">']
    # Enlaces numéricos reales: 1..last_page
    for p in range(1, last_page + 1):
        cls = "page-link active" if p == current else "page-link"
        parts.append(
            f'<a class="{cls}" href="/page/{p}/">{p}</a>'
        )
    # Enlace "next" que apunta a last_page + 1 (debe ser ignorado)
    parts.append(
        f'<a class="next page-numbers" '
        f'href="/page/{last_page + 1}/">Siguiente</a>'
    )
    parts.append('</nav>')
    return "\n".join(parts)


def make_listing_page(
    items: list[dict], last_page: int = 1, current_page: int = 1
) -> str:
    """Genera HTML de una página de listado con items y paginación numérica.

    Args:
        items: lista de dicts con ``href``, ``title``, ``year``, ``poster``.
        last_page: número máximo de página (para la barra de paginación).
        current_page: página actual (para marcar ``active``).
    """
    parts = [
        '<!DOCTYPE html><html><body>',
        '<div class="posts">',
    ]
    for item in items:
        href = item.get("href", f"/pelicula/{item['provider_id']}/")
        title = item.get("title", item.get("provider_id", ""))
        year = item.get("year", 2024)
        poster = item.get("poster", "/img/default.jpg")
        parts.append(
            f'<div class="TPost">'
            f'  <a href="{href}">{title}'
            f'    <figure class="Objf">'
            f'      <img src="{poster}" alt="{title}" />'
            f'    </figure>'
            f'  </a>'
            f'  <span class="Year">{year}</span>'
            f'</div>'
        )
    parts.append("</div>")  # /posts
    parts.append(make_pagination_bar(current_page, last_page))
    parts.append("</body></html>")
    return "\n".join(parts)


def make_item(
    provider_id: str,
    href: str | None = None,
    title: str | None = None,
    year: int = 2024,
    poster: str = "/img/poster.jpg",
    provider: str = "cuevana3",
) -> dict:
    """Crea un dict de item para ``make_listing_page``.

    Incluye la clave ``provider`` para que ``save_page_items`` persista
    correctamente (requiere ``provider`` y ``provider_id``).
    """
    return {
        "provider": provider,
        "provider_id": provider_id,
        "href": href or f"/pelicula/{provider_id}/",
        "title": title or provider_id,
        "year": year,
        "poster": poster,
    }


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------

@pytest.fixture
def adapter_mock() -> Cuevana3Adapter:
    """Provee un Cuevana3Adapter con cliente HTTP mockeado."""
    adapter = Cuevana3Adapter()
    adapter._client = AsyncMock()
    return adapter


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    """Ruta de un archivo SQLite temporal para el inventario."""
    return str(tmp_path / "inventory_test.sqlite")


@pytest.fixture
def service() -> CatalogInventoryService:
    return CatalogInventoryService()


@pytest.fixture(autouse=True)
def patch_sleep():
    """Evita delays reales entre páginas durante el inventario."""
    import src.services.catalog_inventory as inv_module

    async def _no_sleep(_: float) -> None:
        return None

    original = inv_module.asyncio.sleep
    inv_module.asyncio.sleep = _no_sleep
    yield
    inv_module.asyncio.sleep = original


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


class TestExtractMenuCategories:
    """Valida el parseo de categorías desde /genero/<slug>/."""

    def test_discover_and_deduplicate_categories_from_menu(self):
        """Verifica que parsea /genero/<slug>/ deduplicando por slug y
        preservando nombre y URL canónica."""
        html = make_menu_html([
            ("accion", "Acción"),
            ("accion", "Acción DUPLICADA"),  # slug repetido
            ("aventura", "Aventura"),
            ("terror", "Terror"),
            ("accion", "Acción REPETIDO"),  # slug repetido otra vez
        ])

        categories = extract_menu_categories(html, base_url="https://cuevana3i.cc")

        assert len(categories) == 3
        slugs = [c["slug"] for c in categories]
        assert slugs == ["accion", "aventura", "terror"]

        # Preserva el primer nombre limpio encontrado por slug
        assert categories[0]["name"] == "Acción"
        assert categories[1]["name"] == "Aventura"
        assert categories[2]["name"] == "Terror"

        # URL canónica absoluta con barra final
        assert categories[0]["url"] == "https://cuevana3i.cc/genero/accion/"
        assert categories[1]["url"] == "https://cuevana3i.cc/genero/aventura/"
        assert categories[2]["url"] == "https://cuevana3i.cc/genero/terror/"


class TestExtractLastPage:
    """Valida que extract_last_page toma el número máximo numérico."""

    def test_pagination_extracts_last_page_from_numeric_links(self):
        """Extrae el número más alto de a.page-link / .page-numbers."""
        html = make_pagination_bar(current=1, last_page=42)
        assert extract_last_page(html) == 42

    def test_pagination_ignores_next_link(self):
        """Nunca usa a.next para determinar el límite.

        El enlace 'next' apunta a last_page + 1; extract_last_page debe
        retornar last_page, no last_page + 1.
        """
        html = make_pagination_bar(current=42, last_page=42)
        # El enlace "next" href es /page/43/ (last_page + 1)
        assert extract_last_page(html) == 42

    def test_pagination_no_numeric_links_returns_1(self):
        """Sin paginación numérica, retorna 1."""
        html = (
            '<html><body>'
            '<a class="next page-numbers" href="/page/2/">Next</a>'
            '</body></html>'
        )
        assert extract_last_page(html) == 1


class TestRunInventoryPagination:
    """Valida el límite estricto de páginas y la no-solicitud de last_page+1."""

    @pytest.mark.asyncio
    async def test_pagination_extracts_last_page_and_limits_strictly(
        self, adapter_mock, db_path, service, tmp_path
    ):
        """Extrae el número más alto de la paginación y nunca solicita
        last_page + 1."""
        # Simular 3 categorías con 5 páginas cada una
        menu_html = make_menu_html([
            ("accion", "Acción"),
            ("comedia", "Comedia"),
        ])

        pages_requested: list[tuple[str, int]] = []

        def _make_items(cat: str, page: int) -> list[dict]:
            return [make_item(f"{cat}-p{page}-m{i}", title=f"Movie {cat} P{page} M{i}")
                    for i in range(2)]

        async def mock_get(url, *args, **kwargs):
            # /peliculas/ -> menú de categorías
            if url.rstrip("/") == "/peliculas" or url == "/peliculas/":
                return _mock_response(menu_html)

            # Extraer categoría y página de la URL
            m = re.match(r"^/genero/([^/]+)/?$", url)
            if m:
                # Página 1 (last_page se obtiene de aquí)
                cat = m.group(1)
                pages_requested.append((cat, 1))
                last_page = 5
                html = make_listing_page(_make_items(cat, 1),
                                         last_page=last_page, current_page=1)
                return _mock_response(html)

            m = re.match(r"^/genero/([^/]+)/page/(\d+)/?$", url)
            if m:
                cat = m.group(1)
                page = int(m.group(2))
                pages_requested.append((cat, page))
                html = make_listing_page(_make_items(cat, page),
                                         last_page=5, current_page=page)
                return _mock_response(html)

            raise httpx.HTTPError(f"URL inesperada: {url}")

        adapter_mock._client.get.side_effect = mock_get

        result = await service.run_inventory(db_path, adapter_mock)

        # Todas las categorías deben estar completas
        assert result["run_status"] == "complete"
        assert result["categories_completed"] == 2
        assert result["categories_total"] == 2
        assert result["unique_movies_count"] == 20  # 2 cats * 5 pages * 2 items

        # Verificar estrictamente 1..last_page por categoría (5 páginas cada una)
        # Nota: la implementación de run_inventory solicita página 1 dos veces:
        #   1) para extraer last_page (extract_last_page)
        #   2) para procesar el loop principal (page=1)
        # Las páginas 2..last_page se solicitan una sola vez.
        for cat in ("accion", "comedia"):
            cat_pages = sorted(p for (c, p) in pages_requested if c == cat)
            # Página 1 aparece dos veces (last_page + loop), 2..5 una vez
            assert cat_pages == [1, 1, 2, 3, 4, 5], (
                f"Categoría {cat}: páginas solicitadas={cat_pages}"
            )
            # Nunca se solicita last_page + 1 (6)
            assert 6 not in cat_pages

        # Verificar que solo se solicitaron páginas 1..last_page (nunca 6)
        all_pages = sorted(p for (_, p) in pages_requested)
        assert max(all_pages) == 5
        assert 6 not in all_pages


class TestResumeIncompleteCategory:
    """Valida el reanudado respetando páginas confirmadas."""

    @pytest.mark.asyncio
    async def test_resume_incomplete_category_skips_confirmed_pages(
        self, adapter_mock, db_path, service
    ):
        """Una categoría con páginas 1 y 2 confirmadas de 4 reanuda en página 3."""
        db = CatalogInventoryDB(db_path)
        db.init_db()

        # Pre-registrar una categoría "accion" con last_page=4 y confirmed_page=2
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO categories (slug, name, url, last_page, confirmed_page, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("accion", "Acción", "https://cuevana3i.cc/genero/accion/", 4, 2, "in_progress"),
            )
            conn.commit()
        finally:
            conn.close()

        # Insertar algunos items ya confirmados en páginas 1-2
        # (usar db.save_page_items en transacciones separadas)
        db.save_page_items("accion", 1, [
            make_item("prev-movie-1", title="Prev Movie 1"),
        ])
        db.save_page_items("accion", 2, [
            make_item("prev-movie-2", title="Prev Movie 2"),
        ])

        # El run debe estar in_progress (ya que no está complete)
        status = db.get_status()
        assert status["run_status"] != "complete"

        # Mock: solo debería solicitar página 3 y 4 (NO 1 ni 2)
        pages_requested: list[int] = []

        async def mock_get(url, *args, **kwargs):
            m = re.match(r"^/genero/accion/page/(\d+)/?$", url)
            if m:
                page = int(m.group(1))
                pages_requested.append(page)
                return _mock_response(make_listing_page(
                    [make_item(f"new-movie-{page}", title=f"New Movie {page}")],
                    last_page=4, current_page=page,
                ))
            raise httpx.HTTPError(f"URL inesperada: {url}")

        adapter_mock._client.get.side_effect = mock_get

        result = await service.run_inventory(db_path, adapter_mock)

        # Debería haber solicitado solo páginas 3 y 4
        assert pages_requested == [3, 4], f"Páginas solicitadas: {pages_requested}"

        # La categoría debería estar completa (4/4 páginas)
        assert result["run_status"] == "complete"
        assert result["categories_completed"] == 1
        assert result["categories_total"] == 1
        # 2 items previos + 2 items nuevos = 4
        assert result["unique_movies_count"] == 4


class TestSkipCompletedCategories:
    """Valida que categorías completas no hacen peticiones HTTP."""

    @pytest.mark.asyncio
    async def test_skip_completed_categories(
        self, adapter_mock, db_path, service
    ):
        """Una categoría con estado 'complete' no realiza peticiones HTTP."""
        db = CatalogInventoryDB(db_path)
        db.init_db()

        conn = sqlite3.connect(db_path)
        conn.execute("BEGIN IMMEDIATE")
        # Categoría ya completa
        conn.execute(
            "INSERT INTO categories (slug, name, url, last_page, confirmed_page, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("accion", "Acción", "https://cuevana3i.cc/genero/accion/", 3, 3, "complete"),
        )
        conn.execute(
            "INSERT INTO runs (status, error) VALUES (?, ?)",
            ("in_progress", None),
        )
        conn.commit()
        conn.close()

        # Mock que NO debería ser llamado
        mock_get = AsyncMock(side_effect=AssertionError("No deberían hacerse peticiones HTTP"))
        adapter_mock._client.get = mock_get

        result = await service.run_inventory(db_path, adapter_mock)

        # El run debería marcar complete sin peticiones HTTP
        assert result["run_status"] == "complete"
        assert result["categories_completed"] == 1
        assert result["categories_total"] == 1
        assert mock_get.await_count == 0


class TestDeduplicateMovies:
    """Valida deduplicación preservando múltiples categorías."""

    @pytest.mark.asyncio
    async def test_deduplicate_movies_preserve_multiple_categories(
        self, adapter_mock, db_path, service
    ):
        """Una película en dos categorías se guarda una vez en movies y
        mantiene ambas asociaciones en movie_categories."""
        menu_html = make_menu_html([
            ("accion", "Acción"),
            ("aventura", "Aventura"),
        ])

        # La misma película (same provider_id) aparece en ambas categorías
        shared_item = make_item(
            "shared-movie",
            href="/pelicula/shared-movie/",
            title="Shared Movie",
            year=2024,
        )

        async def mock_get(url, *args, **kwargs):
            if url.rstrip("/") == "/peliculas" or url == "/peliculas/":
                return _mock_response(menu_html)

            m = re.match(r"^/genero/([^/]+)/?$", url)
            if m:
                cat = m.group(1)
                html = make_listing_page([shared_item], last_page=1, current_page=1)
                return _mock_response(html)

            raise httpx.HTTPError(f"URL inesperada: {url}")

        adapter_mock._client.get.side_effect = mock_get

        result = await service.run_inventory(db_path, adapter_mock)

        assert result["run_status"] == "complete"
        # Solo 1 película única en movies
        assert result["unique_movies_count"] == 1

        # Verificar directamente en SQLite
        conn = sqlite3.connect(db_path)
        movies = conn.execute("SELECT provider, provider_id FROM movies").fetchall()
        assert len(movies) == 1
        assert movies[0] == ("cuevana3", "shared-movie")

        # La película debe estar asociada a ambas categorías
        cats = conn.execute(
            "SELECT category_slug FROM movie_categories WHERE provider=? AND provider_id=?",
            ("cuevana3", "shared-movie"),
        ).fetchall()
        cat_slugs = sorted(r[0] for r in cats)
        assert cat_slugs == ["accion", "aventura"], f"Asociaciones: {cat_slugs}"
        conn.close()


class TestExcludeSeries:
    """Valida que series (/serie/) se excluyen estrictamente."""

    @pytest.mark.asyncio
    async def test_exclude_series(self, adapter_mock, db_path, service):
        """Los elementos con URL de serie se descartan."""
        menu_html = make_menu_html([("accion", "Acción")])

        movie_item = make_item(
            "real-movie", href="/pelicula/real-movie/", title="Real Movie", year=2024
        )
        series_item = make_item(
            "fake-series", href="/serie/fake-series/", title="Fake Series", year=2025
        )

        async def mock_get(url, *args, **kwargs):
            if url.rstrip("/") == "/peliculas" or url == "/peliculas/":
                return _mock_response(menu_html)
            m = re.match(r"^/genero/([^/]+)/?$", url)
            if m:
                # Primera página con ambos tipos de items
                html = make_listing_page(
                    [movie_item, series_item], last_page=1, current_page=1
                )
                return _mock_response(html)
            raise httpx.HTTPError(f"URL inesperada: {url}")

        adapter_mock._client.get.side_effect = mock_get

        result = await service.run_inventory(db_path, adapter_mock)

        assert result["run_status"] == "complete"
        # Solo 1 película única (la serie debe estar excluida)
        assert result["unique_movies_count"] == 1

        conn = sqlite3.connect(db_path)
        movies = conn.execute(
            "SELECT provider_id FROM movies WHERE provider='cuevana3'"
        ).fetchall()
        provider_ids = [r[0] for r in movies]
        assert "real-movie" in provider_ids
        assert "fake-series" not in provider_ids, "La serie no debe guardarse"

        # Verificar que la categoría no contiene la serie
        mc_count = conn.execute(
            "SELECT COUNT(*) FROM movie_categories "
            "WHERE provider='cuevana3' AND provider_id='fake-series'"
        ).fetchone()[0]
        assert mc_count == 0
        conn.close()


class TestPrematureFailure:
    """Valida que errores/empties antes de last_page marcan incomplete."""

    @pytest.mark.asyncio
    async def test_premature_empty_page_or_error_marks_incomplete(
        self, adapter_mock, db_path, service
    ):
        """Un error HTTP o respuesta vacía antes de last_page no borra el
        progreso confirmado y deja el run y la categoría como incomplete."""
        menu_html = make_menu_html([("accion", "Acción")])

        async def mock_get(url, *args, **kwargs):
            if url.rstrip("/") == "/peliculas" or url == "/peliculas/":
                return _mock_response(menu_html)

            # Página 1 con last_page=4 (paginación anuncia 4)
            m = re.match(r"^/genero/([^/]+)/?$", url)
            if m:
                html = make_listing_page(
                    [make_item("movie-p1", title="Movie P1")],
                    last_page=4, current_page=1,
                )
                return _mock_response(html)

            # Página 2: timeout (error HTTP antes de last_page)
            m = re.match(r"^/genero/([^/]+)/page/(\d+)/?$", url)
            if m:
                page = int(m.group(2))
                if page == 2:
                    raise httpx.TimeoutException("Timeout simulado")
                raise httpx.HTTPError(f"URL inesperada: {url}")

            raise httpx.HTTPError(f"URL inesperada: {url}")

        adapter_mock._client.get.side_effect = mock_get

        result = await service.run_inventory(db_path, adapter_mock)

        # El run debe estar incomplete
        assert result["run_status"] == "incomplete"

        # La categoría debe estar marcada como incomplete
        conn = sqlite3.connect(db_path)
        cat_row = conn.execute(
            "SELECT status, confirmed_page, last_page FROM categories WHERE slug='accion'"
        ).fetchone()
        assert cat_row is not None
        assert cat_row[0] == "incomplete", f"status={cat_row[0]}"
        # confirmed_page debe preservar el progreso de página 1
        assert cat_row[1] == 1, f"confirmed_page={cat_row[1]}"
        # last_page debe estar fijado en 4
        assert cat_row[2] == 4, f"last_page={cat_row[2]}"

        # El item de la página 1 debe estar preservado
        movies = conn.execute(
            "SELECT provider_id FROM movies WHERE provider='cuevana3'"
        ).fetchall()
        provider_ids = [r[0] for r in movies]
        assert "movie-p1" in provider_ids, "El progreso de página 1 debe preservarse"
        conn.close()

    @pytest.mark.asyncio
    async def test_premature_empty_page_marks_incomplete(
        self, adapter_mock, db_path, service
    ):
        """Una página vacía antes de last_page marca incomplete sin borrar progreso."""
        menu_html = make_menu_html([("accion", "Acción")])

        async def mock_get(url, *args, **kwargs):
            if url.rstrip("/") == "/peliculas" or url == "/peliculas/":
                return _mock_response(menu_html)

            # Página 1 normal
            m = re.match(r"^/genero/([^/]+)/?$", url)
            if m:
                html = make_listing_page(
                    [make_item("movie-p1", title="Movie P1")],
                    last_page=3, current_page=1,
                )
                return _mock_response(html)

            # Página 2: respuesta vacía (sin items, pero con paginación)
            m = re.match(r"^/genero/([^/]+)/page/(\d+)/?$", url)
            if m:
                page = int(m.group(2))
                if page == 2:
                    # HTML con paginación pero sin div.TPost
                    html = (
                        '<html><body>'
                        + make_pagination_bar(current=2, last_page=3)
                        + '</body></html>'
                    )
                    return _mock_response(html)
                raise httpx.HTTPError(f"URL inesperada: {url}")

            raise httpx.HTTPError(f"URL inesperada: {url}")

        adapter_mock._client.get.side_effect = mock_get

        result = await service.run_inventory(db_path, adapter_mock)

        assert result["run_status"] == "incomplete"

        conn = sqlite3.connect(db_path)
        cat_row = conn.execute(
            "SELECT status, confirmed_page FROM categories WHERE slug='accion'"
        ).fetchone()
        assert cat_row[0] == "incomplete"
        # confirmed_page preserva la página 1
        assert cat_row[1] == 1

        # El ítem de página 1 se preserva
        movies = conn.execute(
            "SELECT provider_id FROM movies WHERE provider='cuevana3'"
        ).fetchall()
        provider_ids = [r[0] for r in movies]
        assert "movie-p1" in provider_ids
        conn.close()


class TestRunCompletion:
    """Valida que el run pasa a complete solo si todas las categorías terminan."""

    @pytest.mark.asyncio
    async def test_run_marks_complete_only_when_all_categories_finish(
        self, adapter_mock, db_path, service
    ):
        """El run pasa a 'complete' únicamente tras completar todas las
        categorías; si una falla, queda 'incomplete'."""
        menu_html = make_menu_html([
            ("accion", "Acción"),
            ("comedia", "Comedia"),
        ])

        async def mock_get(url, *args, **kwargs):
            if url.rstrip("/") == "/peliculas" or url == "/peliculas/":
                return _mock_response(menu_html)

            # Acción: 2 páginas, completa correctamente
            m = re.match(r"^/genero/accion/page/(\d+)/?$", url)
            if m:
                page = int(m.group(1))
                html = make_listing_page(
                    [make_item(f"accion-m{page}", title=f"Accion Movie {page}")],
                    last_page=2, current_page=page,
                )
                return _mock_response(html)

            m = re.match(r"^/genero/accion/?$", url)
            if m:
                html = make_listing_page(
                    [make_item("accion-m1", title="Accion Movie 1")],
                    last_page=2, current_page=1,
                )
                return _mock_response(html)

            # Comedia: página 1 OK, página 2 falla (timeout)
            m = re.match(r"^/genero/comedia/page/(\d+)/?$", url)
            if m:
                page = int(m.group(1))
                if page == 2:
                    raise httpx.TimeoutException("Timeout simulado")
                return _mock_response("error")

            # Comedia página 1
            return _mock_response(make_listing_page(
                [make_item("comedia-m1", title="Comedia Movie 1")],
                last_page=2, current_page=1,
            ))

        adapter_mock._client.get.side_effect = mock_get

        result = await service.run_inventory(db_path, adapter_mock)

        # El run debe estar incomplete porque comedia falló
        assert result["run_status"] == "incomplete"

        conn = sqlite3.connect(db_path)
        cats = conn.execute(
            "SELECT slug, status FROM categories ORDER BY slug"
        ).fetchall()
        cat_dict = dict(cats)
        assert cat_dict["accion"] == "complete"
        assert cat_dict["comedia"] == "incomplete"
        conn.close()

    @pytest.mark.asyncio
    async def test_run_all_categories_complete_marks_run_complete(
        self, adapter_mock, db_path, service
    ):
        """Cuando todas las categorías terminan, el run pasa a complete."""
        menu_html = make_menu_html([
            ("accion", "Acción"),
            ("comedia", "Comedia"),
            ("terror", "Terror"),
        ])

        async def mock_get(url, *args, **kwargs):
            if url.rstrip("/") == "/peliculas" or url == "/peliculas/":
                return _mock_response(menu_html)

            m = re.match(r"^/genero/([^/]+)/?$", url)
            if m:
                cat = m.group(1)
                return _mock_response(make_listing_page(
                    [make_item(f"{cat}-m1", title=f"{cat} Movie 1")],
                    last_page=1, current_page=1,
                ))

            raise httpx.HTTPError(f"URL inesperada: {url}")

        adapter_mock._client.get.side_effect = mock_get

        result = await service.run_inventory(db_path, adapter_mock)

        assert result["run_status"] == "complete"
        assert result["categories_completed"] == 3
        assert result["categories_total"] == 3
        assert result["unique_movies_count"] == 3


class TestStatusOffline:
    """Valida que la consulta de estado lee de SQLite sin peticiones de red."""

    @pytest.mark.asyncio
    async def test_status_query_works_offline(self, db_path, service, adapter_mock):
        """get_inventory_status lee de SQLite sin realizar peticiones de red."""
        db = CatalogInventoryDB(db_path)
        db.init_db()

        # Insertar datos directamente para simular un inventario parcial
        db.save_page_items("accion", 1, [
            make_item("movie-1", title="Movie 1"),
            make_item("movie-2", title="Movie 2"),
        ])
        db.save_page_items("accion", 2, [
            make_item("movie-3", title="Movie 3"),
        ])
        # Marcar accion como complete (2 de 2)
        conn = sqlite3.connect(db_path)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE categories SET last_page=2, confirmed_page=2, status='complete' WHERE slug='accion'"
        )
        conn.commit()
        conn.close()

        # Insertar run
        conn = sqlite3.connect(db_path)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO runs (status, error) VALUES ('complete', NULL)"
        )
        conn.commit()
        conn.close()

        # get_inventory_status no debe tocar el adapter
        status = get_inventory_status(db_path)

        assert status["run_status"] == "complete"
        assert status["categories_completed"] == 1
        assert status["categories_total"] == 1
        assert status["unique_movies_count"] == 3

        # Asegurar que el adapter no fue llamado
        if adapter_mock._client:
            assert adapter_mock._client.get.await_count == 0

    @pytest.mark.asyncio
    async def test_status_query_empty_db(self, db_path):
        """get_inventory_status funciona incluso con DB vacía (sin runs)."""
        db = CatalogInventoryDB(db_path)
        db.init_db()

        status = get_inventory_status(db_path)
        assert status["run_status"] == "in_progress"
        assert status["categories_total"] == 0
        assert status["categories_completed"] == 0
        assert status["unique_movies_count"] == 0
        assert status["current_category"] is None
        assert status["last_error"] is None


class TestNoDetailOrPlaybackCalls:
    """Valida que durante el recorrido no se invocan get_details ni
    resolve_playback."""

    @pytest.mark.asyncio
    async def test_no_detail_or_playback_calls(self, adapter_mock, db_path, service):
        """Durante todo el recorrido no se invocan métodos de detalles
        individuales ni resolvers de reproducción."""
        menu_html = make_menu_html([("accion", "Acción")])

        pages_requested = [0]

        async def mock_get(url, *args, **kwargs):
            pages_requested[0] += 1
            if pages_requested[0] == 1:
                return _mock_response(menu_html)
            # Página 1 de acción con 2 items
            return _mock_response(make_listing_page(
                [make_item("movie-1", title="Movie 1"),
                 make_item("movie-2", title="Movie 2")],
                last_page=1, current_page=1,
            ))

        adapter_mock._client.get.side_effect = mock_get

        # Espiar get_details y resolve_playback en el adapter
        adapter_mock.get_details = AsyncMock(side_effect=AssertionError(
            "get_details no debe invocarse durante el inventario"
        ))
        adapter_mock.resolve_playback = AsyncMock(side_effect=AssertionError(
            "resolve_playback no debe invocarse durante el inventario"
        ))

        result = await service.run_inventory(db_path, adapter_mock)

        assert result["run_status"] == "complete"
        # Verificar que get_details y resolve_playback nunca fueron llamados
        adapter_mock.get_details.assert_not_called()
        adapter_mock.resolve_playback.assert_not_called()


# ----------------------------------------------------------------------
# Helpers internos
# ----------------------------------------------------------------------

def _mock_response(text: str, status_code: int = 200) -> MagicMock:
    """Crea un mock de respuesta HTTP con .text y raise_for_status()."""
    resp = MagicMock()
    resp.text = text
    resp.status_code = status_code

    def raise_for_status():
        if status_code >= 400:
            raise httpx.HTTPStatusError(
                "Error",
                request=None,
                response=resp,
            )

    resp.raise_for_status = raise_for_status
    return resp
