"""Tests de integración para Cuevana3Adapter con HTML mock."""

import httpx
import pytest
from pytest_httpx import HTTPXMock

from src.adapters.cuevana3 import Cuevana3Adapter
from src.models.catalog import MediaType, SearchResult, MediaItem, PlaybackDescriptor


@pytest.fixture
def adapter() -> Cuevana3Adapter:
    return Cuevana3Adapter()


# HTML mock de catálogo con estructura .TPost real
CATALOG_HTML = """
<!DOCTYPE html>
<html>
<body>
    <div class="TPost">
        <a href="/pelicula/the-matrix-1999/">
            <figure class="Objf">
                <img src="/uploads/matrix.jpg" alt="The Matrix">
            </figure>
            <div class="title">1999 The Matrix</div>
        </a>
    </div>
    <div class="TPost">
        <a href="/serie/breaking-bad-2008/">
            <figure class="Objf">
                <img src="/uploads/breakingbad.jpg" alt="Breaking Bad">
            </figure>
            <div class="title">2008 Breaking Bad</div>
        </a>
    </div>
    <div class="TPost">
        <a href="/pelicula/interstellar-2014/">
            <figure class="Objf">
                <img src="data:image/svg+xml;base64,PHN2Zz4..." alt="placeholder">
            </figure>
            <div class="title">2014 Interstellar</div>
        </a>
    </div>
</body>
</html>
"""

# HTML mock de página de película
MOVIE_DETAILS_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta property="og:image" content="https://cuevana3i.cc/uploads/interstellar-poster.jpg">
    <meta name="description" content="Un equipo de exploradores viaja a través de un agujero de gusano.">
</head>
<body>
    <article>
        <h1>Interstellar</h1>
        <p>Un equipo de exploradores viaja a través de un agujero de gusano en el espacio para asegurar la supervivencia de la humanidad.</p>
        <sectionfooter>
            <span>2h 49m</span>
            <span>2014</span>
            <span>HD</span>
        </sectionfooter>
        <div class="genres">
            <span>Género:</span>
            <a href="/genero/ciencia-ficcion/">Ciencia ficción</a>
            <a href="/genero/aventura/">Aventura</a>
        </div>
        <figure>
            <img src="/uploads/interstellar.jpg" alt="Interstellar">
        </figure>
        <ul class="servers">
            <li>
                <div class="_3CT5n_0" data-mdl="https://doodstream.com/e/abc123">
                    <img src="/flags/es.svg" alt="Español">
                    <span>Doodstream</span>
                </div>
            </li>
            <li>
                <div class="_3CT5n_0" data-url="https://voe.sx/e/def456">
                    <img src="/flags/la.svg" alt="Latino">
                    <span>Voe</span>
                </div>
            </li>
            <li>
                <div class="_3CT5n_0" onclick="loadPlayer('https://vidhide.com/e/ghi789')">
                    <img src="/flags/en.svg" alt="English">
                    <span>Vidhide</span>
                </div>
            </li>
        </ul>
    </article>
</body>
</html>
"""

# HTML mock de página de serie
SERIES_DETAILS_HTML = """
<!DOCTYPE html>
<html>
<body>
    <article>
        <h1>Breaking Bad</h1>
        <p>Un profesor de química diagnosticado con cáncer se une a un exalumno para fabricar metanfetamina.</p>
        <sectionfooter>
            <span>2008</span>
            <span>TV-MA</span>
        </sectionfooter>
    </article>
    <select id="season">
        <option value="1">Temporada 1</option>
        <option value="2">Temporada 2</option>
        <option value="3">Temporada 3</option>
    </select>
    <div class="episodes">
        <a href="/serie/breaking-bad-2008/temporada-1-capitulo-1/">Episodio 1</a>
        <a href="/serie/breaking-bad-2008/temporada-1-capitulo-2/">Episodio 2</a>
        <a href="/serie/breaking-bad-2008/temporada-1-capitulo-3/">Episodio 3</a>
    </div>
</body>
</html>
"""

# HTML mock con servidor en script inline
MOVIE_WITH_SCRIPT_SERVER = """
<!DOCTYPE html>
<html>
<body>
    <article>
        <h1>Test Movie</h1>
        <p>Sinopsis de prueba.</p>
        <sectionfooter>2024</sectionfooter>
    </article>
    <script>
        var servers = [
            {"name": "Doodstream", "url": "https://doodstream.com/e/xyz789"},
            {"name": "Voe", "url": "https://voe.sx/e/abc123"}
        ];
    </script>
</body>
</html>
"""

# HTML mock vacío (sin selectores esperados)
EMPTY_HTML = """
<!DOCTYPE html>
<html>
<body>
    <div class="other-content">No hay películas aquí</div>
</body>
</html>
"""


class TestCuevana3Search:
    """Tests para search() y get_catalog()."""

    @pytest.mark.asyncio
    async def test_search_returns_items_with_correct_selectors(self, adapter: Cuevana3Adapter, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="https://cuevana3i.cc/buscar/?q=matrix",
            method="GET",
            text=CATALOG_HTML,
        )

        result = await adapter.search("matrix")

        assert isinstance(result, SearchResult)
        assert result.total == 3
        assert len(result.items) == 3

        # Verificar primer item (película)
        item1 = result.items[0]
        assert item1.media_id == "cuevana3:the-matrix-1999"
        assert item1.title == "The Matrix"
        assert item1.year == 1999
        assert item1.media_type == MediaType.MOVIE
        assert item1.poster_url == "https://cuevana3i.cc/uploads/matrix.jpg"
        assert item1.provider == "cuevana3"

        # Verificar segundo item (serie)
        item2 = result.items[1]
        assert item2.media_id == "cuevana3:breaking-bad-2008"
        assert item2.title == "Breaking Bad"
        assert item2.year == 2008
        assert item2.media_type == MediaType.SERIES

        # Verificar tercer item (placeholder SVG ignorado)
        item3 = result.items[2]
        assert item3.title == "Interstellar"
        assert item3.year == 2014
        assert item3.poster_url is None  # placeholder data:image ignorado

    @pytest.mark.asyncio
    async def test_get_catalog_returns_movies(self, adapter: Cuevana3Adapter, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="https://cuevana3i.cc/peliculas/",
            method="GET",
            text=CATALOG_HTML,
        )

        items = await adapter.get_catalog()

        assert len(items) == 3
        assert all(item.media_type in (MediaType.MOVIE, MediaType.SERIES) for item in items)
        assert items[0].title == "The Matrix"
        assert items[1].title == "Breaking Bad"

    @pytest.mark.asyncio
    async def test_get_catalog_with_category(self, adapter: Cuevana3Adapter, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="https://cuevana3i.cc/genero/accion/",
            method="GET",
            text=CATALOG_HTML,
        )

        items = await adapter.get_catalog("accion")
        assert len(items) == 3

    @pytest.mark.asyncio
    async def test_search_timeout_returns_empty(self, adapter: Cuevana3Adapter, httpx_mock: HTTPXMock):
        httpx_mock.add_exception(httpx.TimeoutException("Timeout"))

        result = await adapter.search("test")
        assert result.total == 0
        assert len(result.items) == 0


class TestCuevana3Details:
    """Tests para get_details()."""

    @pytest.mark.asyncio
    async def test_get_details_movie_extracts_all_fields(self, adapter: Cuevana3Adapter, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="https://cuevana3i.cc/pelicula/interstellar-2014/",
            method="GET",
            text=MOVIE_DETAILS_HTML,
        )

        item = await adapter.get_details("cuevana3:interstellar-2014")

        assert item.media_id == "cuevana3:interstellar-2014"
        assert item.title == "Interstellar"
        assert item.year == 2014
        assert item.media_type == MediaType.MOVIE
        assert "exploradores" in item.overview.lower()
        assert item.poster_url == "https://cuevana3i.cc/uploads/interstellar-poster.jpg"

    @pytest.mark.asyncio
    async def test_get_details_series(self, adapter: Cuevana3Adapter, httpx_mock: HTTPXMock):
        # El adapter intenta primero /pelicula/ y luego /serie/
        httpx_mock.add_response(
            url="https://cuevana3i.cc/pelicula/breaking-bad-2008/",
            method="GET",
            status_code=404,
        )
        httpx_mock.add_response(
            url="https://cuevana3i.cc/serie/breaking-bad-2008/",
            method="GET",
            text=SERIES_DETAILS_HTML,
        )

        item = await adapter.get_details("cuevana3:breaking-bad-2008")

        assert item.media_id == "cuevana3:breaking-bad-2008"
        assert item.title == "Breaking Bad"
        assert item.year == 2008
        assert item.media_type == MediaType.SERIES
        assert "química" in item.overview.lower()

    @pytest.mark.asyncio
    async def test_get_details_timeout_raises(self, adapter: Cuevana3Adapter, httpx_mock: HTTPXMock):
        # Mockear ambos endpoints para que fallen
        httpx_mock.add_exception(httpx.TimeoutException("Timeout"))
        httpx_mock.add_exception(httpx.TimeoutException("Timeout"))

        with pytest.raises(ValueError, match="Timeout"):
            await adapter.get_details("cuevana3:test")


class TestCuevana3SeasonsEpisodes:
    """Tests para get_seasons() y get_episodes()."""

    @pytest.mark.asyncio
    async def test_get_seasons_from_select(self, adapter: Cuevana3Adapter, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="https://cuevana3i.cc/serie/breaking-bad-2008/",
            method="GET",
            text=SERIES_DETAILS_HTML,
        )

        seasons = await adapter.get_seasons("cuevana3:breaking-bad-2008")

        assert len(seasons) == 3
        assert seasons[0].season_number == 1
        assert seasons[1].season_number == 2
        assert seasons[2].season_number == 3

    @pytest.mark.asyncio
    async def test_get_episodes_from_pattern(self, adapter: Cuevana3Adapter, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="https://cuevana3i.cc/serie/breaking-bad-2008/",
            method="GET",
            text=SERIES_DETAILS_HTML,
        )

        episodes = await adapter.get_episodes("cuevana3:breaking-bad-2008", 1)

        assert len(episodes) == 3
        assert episodes[0].episode_number == 1
        assert episodes[0].season_number == 1
        assert episodes[0].title == "Episodio 1"
        assert episodes[0].provider_id == "temporada-1-capitulo-1"
        assert episodes[1].provider_id == "temporada-1-capitulo-2"


class TestCuevana3ResolvePlayback:
    """Tests para resolve_playback()."""

    @pytest.mark.asyncio
    async def test_resolve_playback_from_data_mdl(self, adapter: Cuevana3Adapter, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="https://cuevana3i.cc/pelicula/interstellar-2014/",
            method="GET",
            text=MOVIE_DETAILS_HTML,
        )

        result = await adapter.resolve_playback("cuevana3:interstellar-2014")

        assert isinstance(result, PlaybackDescriptor)
        assert result.protocol == "embed"
        assert result.url == "https://doodstream.com/e/abc123"
        assert result.headers["Referer"] == "https://cuevana3i.cc"

    @pytest.mark.asyncio
    async def test_resolve_playback_from_data_url(self, adapter: Cuevana3Adapter, httpx_mock: HTTPXMock):
        """Test fallback a data-url cuando data-mdl no está."""
        html = MOVIE_DETAILS_HTML.replace('data-mdl="https://doodstream.com/e/abc123"', 'data-url="https://voe.sx/e/def456"')
        httpx_mock.add_response(
            url="https://cuevana3i.cc/pelicula/test/",
            method="GET",
            text=html,
        )

        result = await adapter.resolve_playback("cuevana3:test")
        assert result.url == "https://voe.sx/e/def456"

    @pytest.mark.asyncio
    async def test_resolve_playback_from_onclick(self, adapter: Cuevana3Adapter, httpx_mock: HTTPXMock):
        """Test extracción desde onclick."""
        html = (
            MOVIE_DETAILS_HTML
            .replace('data-mdl="https://doodstream.com/e/abc123"', '')
            .replace('data-url="https://voe.sx/e/def456"', '')
        )
        # El adapter intenta primero /pelicula/ y luego /serie/
        httpx_mock.add_response(
            url="https://cuevana3i.cc/pelicula/test/",
            method="GET",
            text=html,
        )

        result = await adapter.resolve_playback("cuevana3:test")
        assert result.url == "https://vidhide.com/e/ghi789"

    @pytest.mark.asyncio
    async def test_resolve_playback_from_script(self, adapter: Cuevana3Adapter, httpx_mock: HTTPXMock):
        """Test extracción desde script inline."""
        httpx_mock.add_response(
            url="https://cuevana3i.cc/pelicula/test/",
            method="GET",
            text=MOVIE_WITH_SCRIPT_SERVER,
        )

        result = await adapter.resolve_playback("cuevana3:test")
        assert result.url == "https://doodstream.com/e/xyz789"

    @pytest.mark.asyncio
    async def test_resolve_playback_no_server_raises(self, adapter: Cuevana3Adapter, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="https://cuevana3i.cc/pelicula/empty/",
            method="GET",
            text=EMPTY_HTML,
        )

        with pytest.raises(ValueError, match="No se encontró fuente"):
            await adapter.resolve_playback("cuevana3:empty")

    @pytest.mark.asyncio
    async def test_resolve_playback_timeout_raises(self, adapter: Cuevana3Adapter, httpx_mock: HTTPXMock):
        httpx_mock.add_exception(httpx.TimeoutException("Timeout"))
        httpx_mock.add_exception(httpx.TimeoutException("Timeout"))

        with pytest.raises(ValueError, match="Timeout"):
            await adapter.resolve_playback("cuevana3:test")


class TestCuevana3ErrorHandling:
    """Tests de manejo de errores y casos borde."""

    @pytest.mark.asyncio
    async def test_empty_html_returns_empty_catalog(self, adapter: Cuevana3Adapter, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="https://cuevana3i.cc/peliculas/",
            method="GET",
            text=EMPTY_HTML,
        )

        items = await adapter.get_catalog()
        assert items == []

    @pytest.mark.asyncio
    async def test_http_error_returns_empty(self, adapter: Cuevana3Adapter, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="https://cuevana3i.cc/peliculas/",
            method="GET",
            status_code=500,
        )

        items = await adapter.get_catalog()
        assert items == []

    @pytest.mark.asyncio
    async def test_search_http_error_returns_empty(self, adapter: Cuevana3Adapter, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="https://cuevana3i.cc/buscar/?q=test",
            method="GET",
            status_code=403,
        )

        result = await adapter.search("test")
        assert result.total == 0
        assert len(result.items) == 0

    async def test_close_closes_client(self, adapter: Cuevana3Adapter):
        await adapter.close()
        assert adapter._client.is_closed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])