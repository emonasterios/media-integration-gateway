"""Tests de integración para Cuevana3Adapter con mocks HTTP."""

import pytest
import httpx
from unittest.mock import AsyncMock, patch
from bs4 import BeautifulSoup

from src.adapters.cuevana3 import Cuevana3Adapter
from src.models.catalog import MediaType, SearchResult, MediaItem, PlaybackDescriptor


# ----------------------------------------------------------------------
# HTML de prueba (fixtures)
# ----------------------------------------------------------------------

CATALOG_HTML = """
<!DOCTYPE html>
<html>
<body>
    <div class="TPost">
        <a href="/pelicula/pelicula-prueba-2026/">Película Prueba 2026
            <figure class="Objf">
                <img src="/img/poster1.jpg" alt="Película Prueba 2026" />
            </figure>
        </a>
    </div>
    <div class="TPost">
        <a href="/serie/serie-prueba-2026/">Serie Prueba 2026
            <figure class="Objf">
                <img src="/img/poster2.jpg" alt="Serie Prueba 2026" />
            </figure>
        </a>
    </div>
    <div class="TPost">
        <a href="/pelicula/sin-poster/">Sin Poster
            <!-- Sin imagen -->
        </a>
    </div>
    <div class="TPost">
        <a href="/pelicula/placeholder-poster/">Placeholder Poster
            <figure class="Objf">
                <img src="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=" data-src="/img/real-poster.jpg" alt="Placeholder" />
            </figure>
        </a>
    </div>
</body>
</html>
"""

DETAIL_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta property="og:image" content="https://cuevana3i.cc/img/detail-poster.jpg" />
    <meta name="description" content="Sinopsis de prueba desde meta" />
</head>
<body>
    <article>
        <h1>Pelicula Prueba 2026</h1>
        <p>Esta es la sinopsis de la película de prueba.</p>
        <sectionfooter>
            <span>2026</span>
            <span>1h 52m</span>
        </sectionfooter>
        <a href="/genero/accion/">Acción</a>
        <a href="/genero/aventura/">Aventura</a>
    </article>
</body>
</html>
"""

PLAYBACK_HTML = """
<!DOCTYPE html>
<html>
<body>
    <ul>
        <li>
            <div data-mdl="https://doodstream.com/e/abc123" onclick="player.load('https://doodstream.com/e/abc123')">
                <img src="/flags/es.svg" alt="Español" />
            </div>
        </li>
        <li>
            <div data-mdl="https://voe.sx/e/def456" onclick="player.load('https://voe.sx/e/def456')">
                <img src="/flags/en.svg" alt="English" />
            </div>
        </li>
        <li>
            <div data-mdl="https://vidhide.com/e/ghi789" onclick="player.load('https://vidhide.com/e/ghi789')">
                <img src="/flags/pt.svg" alt="Português" />
            </div>
        </li>
    </ul>
    <script>
        var serverUrl = "https://filemoon.sx/e/jkl012";
        var backupUrl = "https://streamtape.com/e/mno345";
    </script>
</body>
</html>
"""

PLAYBACK_HTML_NO_IFRAME = """
<!DOCTYPE html>
<html>
<body>
    <!-- Sin iframes en HTML estático -->
    <div class="server-list">
        <div class="_3CT5n_0" data-mdl="https://doodstream.com/e/xyz789"></div>
    </div>
    <script>
        window.__SERVERS__ = [
            {"url": "https://doodstream.com/e/xyz789", "lang": "es"},
            {"url": "https://voe.sx/e/abc999", "lang": "en"}
        ];
    </script>
</body>
</html>
"""

SEARCH_HTML = """
<!DOCTYPE html>
<html>
<body>
    <div class="TPost">
        <a href="/pelicula/busqueda-pelicula-2026/">Búsqueda Película 2026
            <figure class="Objf">
                <img src="/img/search1.jpg" alt="Búsqueda Película 2026" />
            </figure>
        </a>
    </div>
    <div class="TPost">
        <a href="/serie/busqueda-serie-2026/">Búsqueda Serie 2026
            <figure class="Objf">
                <img src="/img/search2.jpg" alt="Búsqueda Serie 2026" />
            </figure>
        </a>
    </div>
</body>
</html>
"""

SEARCH_EMPTY_HTML = """
<!DOCTYPE html>
<html>
<body>
    <div class="no-results">No se encontraron resultados</div>
</body>
</html>
"""

SEARCH_PLACEHOLDER_POSTER_HTML = """
<!DOCTYPE html>
<html>
<body>
    <div class="TPost">
        <a href="/pelicula/placeholder-test/">Placeholder Test
            <figure class="Objf">
                <img src="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=" data-src="/img/real-poster.jpg" alt="Placeholder" />
            </figure>
        </a>
    </div>
</body>
</html>
"""

# ----------------------------------------------------------------------
# Helpers de mock
# ----------------------------------------------------------------------

class MockResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("Error", request=None, response=self)


@pytest.fixture
def adapter():
    """Fixture que provee un Cuevana3Adapter con cliente mockeado."""
    adapter = Cuevana3Adapter()
    # Reemplazar el cliente HTTP con un mock
    adapter._client = AsyncMock()
    yield adapter


# ----------------------------------------------------------------------
# Tests de catálogo (get_catalog)
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_catalog_movies(adapter):
    """Validar que get_catalog extrae título, poster y slug correctamente."""
    # Mock: página 1 tiene items, página 2 vacía (fin de paginación)
    call_count = [0]
    async def mock_get(url, *args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return MockResponse(CATALOG_HTML)
        return MockResponse("<html><body></body></html>")

    adapter._client.get.side_effect = mock_get

    items = await adapter.get_catalog()

    assert len(items) == 4
    # Primera película - el año está al final, no se quita del título
    assert items[0].title == "Película Prueba 2026"
    assert items[0].year == 2026
    assert items[0].media_type == MediaType.MOVIE
    assert items[0].poster_url == "https://cuevana3i.cc/img/poster1.jpg"
    assert items[0].provider_id == "pelicula-prueba-2026"
    assert items[0].media_id == "cuevana3:pelicula-prueba-2026"
    assert items[0].provider == "cuevana3"
    # Segunda: serie
    assert items[1].title == "Serie Prueba 2026"
    assert items[1].year == 2026
    assert items[1].media_type == MediaType.SERIES
    assert items[1].provider_id == "serie-prueba-2026"
    # Tercera: sin poster
    assert items[2].poster_url is None
    # Cuarta: placeholder SVG -> data-src fallback
    assert items[3].poster_url == "https://cuevana3i.cc/img/real-poster.jpg"


@pytest.mark.asyncio
async def test_get_catalog_with_category(adapter):
    """Validar get_catalog con categoría específica."""
    call_count = [0]
    async def mock_get(url, *args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return MockResponse(CATALOG_HTML)
        return MockResponse("<html><body></body></html>")

    adapter._client.get.side_effect = mock_get

    items = await adapter.get_catalog(category="accion")

    adapter._client.get.assert_called_once_with("/genero/accion/")
    assert len(items) >= 1


@pytest.mark.asyncio
async def test_get_catalog_timeout_returns_empty(adapter):
    """Simular timeout y verificar que devuelve lista vacía sin excepción."""
    adapter._client.get.side_effect = httpx.TimeoutException("Timeout")

    items = await adapter.get_catalog()

    assert items == []


@pytest.mark.asyncio
async def test_get_catalog_http_error_returns_empty(adapter):
    """Simular error HTTP y verificar que devuelve lista vacía."""
    adapter._client.get.side_effect = httpx.HTTPError("Connection error")

    items = await adapter.get_catalog()

    assert items == []


# ----------------------------------------------------------------------
# Tests de detalles (get_details)
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_details_movie(adapter):
    """Validar que get_details extrae título, sinopsis, año y duración."""
    adapter._client.get.return_value = MockResponse(DETAIL_HTML)

    item = await adapter.get_details("cuevana3:pelicula-prueba-2026")

    assert item.title == "Pelicula Prueba 2026"
    assert item.media_type == MediaType.MOVIE
    assert item.year == 2026
    assert item.overview == "Esta es la sinopsis de la película de prueba."
    assert item.poster_url == "https://cuevana3i.cc/img/detail-poster.jpg"
    assert item.provider_id == "pelicula-prueba-2026"


@pytest.mark.asyncio
async def test_get_details_series(adapter):
    """Validar get_details para series (ruta /serie/)."""
    series_html = DETAIL_HTML.replace("Pelicula Prueba 2026", "Serie Prueba 2026").replace(
        "/genero/accion/", "/genero/accion/"
    )
    # Cambiar respuesta para que intente serie primero
    call_count = [0]
    
    async def mock_get(url, *args, **kwargs):
        call_count[0] += 1
        if "/pelicula/" in url:
            return MockResponse("<html><body>Not found</body></html>", 404)
        return MockResponse(series_html)
    
    adapter._client.get.side_effect = mock_get

    item = await adapter.get_details("cuevana3:serie-prueba-2026")

    assert item.media_type == MediaType.SERIES
    assert item.title == "Serie Prueba 2026"


@pytest.mark.asyncio
async def test_get_details_timeout_raises(adapter):
    """Simular timeout en todos los intentos y verificar ValueError."""
    adapter._client.get.side_effect = httpx.TimeoutException("Timeout")

    with pytest.raises(ValueError, match="Timeout accediendo"):
        await adapter.get_details("cuevana3:no-existe")


# ----------------------------------------------------------------------
# Tests de resolución de reproducción (resolve_playback)
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_playback_from_data_mdl(adapter):
    """Validar resolve_playback resuelve servidores usando data-mdl (sin iframe inicial)."""
    adapter._client.get.return_value = MockResponse(PLAYBACK_HTML)

    result = await adapter.resolve_playback("cuevana3:pelicula-prueba-2026")

    assert isinstance(result, PlaybackDescriptor)
    assert result.protocol == "embed"
    assert "doodstream.com" in result.url
    assert result.headers.get("Referer") == "https://cuevana3i.cc"


@pytest.mark.asyncio
async def test_resolve_playback_from_div_data_mdl(adapter):
    """Validar resolve_playback con div._3CT5n_0 y data-mdl (sin iframe)."""
    adapter._client.get.return_value = MockResponse(PLAYBACK_HTML_NO_IFRAME)

    result = await adapter.resolve_playback("cuevana3:pelicula-prueba-2026")

    assert isinstance(result, PlaybackDescriptor)
    assert result.protocol == "embed"
    assert "doodstream.com" in result.url


@pytest.mark.asyncio
async def test_resolve_playback_from_scripts(adapter):
    """Validar fallback a búsqueda en scripts inline."""
    # HTML sin lista ul/li, solo scripts
    html_no_list = """
    <!DOCTYPE html>
    <html><body>
        <script>
            var serverUrl = "https://filemoon.sx/e/jkl012";
        </script>
    </body></html>
    """
    adapter._client.get.return_value = MockResponse(html_no_list)

    result = await adapter.resolve_playback("cuevana3:pelicula-prueba-2026")

    assert isinstance(result, PlaybackDescriptor)
    assert "filemoon.sx" in result.url


@pytest.mark.asyncio
async def test_resolve_playback_timeout_raises(adapter):
    """Simular timeout en todos los intentos de resolución."""
    adapter._client.get.side_effect = httpx.TimeoutException("Timeout")

    with pytest.raises(ValueError, match="Timeout resolviendo reproducción"):
        await adapter.resolve_playback("cuevana3:pelicula-prueba-2026")


@pytest.mark.asyncio
async def test_resolve_playback_http_error_continues(adapter):
    """Simular error HTTP en película y éxito en serie."""
    call_count = [0]
    
    async def mock_get(url, *args, **kwargs):
        call_count[0] += 1
        if "/pelicula/" in url:
            raise httpx.HTTPError("Not found")
        return MockResponse(PLAYBACK_HTML)
    
    adapter._client.get.side_effect = mock_get

    result = await adapter.resolve_playback("cuevana3:pelicula-prueba-2026")

    assert isinstance(result, PlaybackDescriptor)
    assert call_count[0] == 2  # Intentó película y luego serie


# ----------------------------------------------------------------------
# Tests de búsqueda (search)
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_returns_results(adapter):
    """Validar search extrae resultados correctamente."""
    adapter._client.get.return_value = MockResponse(SEARCH_HTML)

    result = await adapter.search("prueba")

    assert isinstance(result, SearchResult)
    assert result.query == "prueba"
    assert result.total == 2
    assert len(result.items) == 2
    assert result.items[0].title == "Búsqueda Película 2026"
    assert result.items[0].year == 2026
    assert result.items[0].media_type == MediaType.MOVIE
    assert result.items[1].media_type == MediaType.SERIES


@pytest.mark.asyncio
async def test_search_empty_results(adapter):
    """Validar search con resultados vacíos."""
    adapter._client.get.return_value = MockResponse(SEARCH_EMPTY_HTML)

    result = await adapter.search("noexiste")

    assert result.total == 0
    assert result.items == []


@pytest.mark.asyncio
async def test_search_timeout_returns_empty(adapter):
    """Simular timeout en búsqueda."""
    adapter._client.get.side_effect = httpx.TimeoutException("Timeout")

    result = await adapter.search("timeout")

    assert result.total == 0
    assert result.items == []


@pytest.mark.asyncio
async def test_search_placeholder_poster_fallback(adapter):
    """Validar fallback data-src cuando src es placeholder SVG."""
    adapter._client.get.return_value = MockResponse(SEARCH_PLACEHOLDER_POSTER_HTML)

    result = await adapter.search("placeholder")

    assert result.total == 1
    assert result.items[0].poster_url == "https://cuevana3i.cc/img/real-poster.jpg"


# ----------------------------------------------------------------------
# Test de manejo de timeout general
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_timeout_handling_all_methods(adapter):
    """Test integral: simular fallo de timeout de httpx en todos los métodos públicos."""
    adapter._client.get.side_effect = httpx.TimeoutException("Timeout")

    # get_catalog - captura timeout y devuelve lista vacía
    catalog = await adapter.get_catalog()
    assert catalog == []

    # search - captura timeout y devuelve resultado vacío
    search = await adapter.search("test")
    assert search.items == []
    assert search.total == 0

    # get_details - captura timeout y lanza ValueError
    with pytest.raises(ValueError, match="Timeout accediendo"):
        await adapter.get_details("cuevana3:test")

    # resolve_playback - captura timeout y lanza ValueError
    with pytest.raises(ValueError, match="Timeout resolviendo reproducción"):
        await adapter.resolve_playback("cuevana3:test")

    # get_seasons - ahora captura timeout vía _fetch_with_flare_fallback y devuelve []
    adapter._client.get.side_effect = httpx.TimeoutException("Timeout")
    seasons = await adapter.get_seasons("cuevana3:serie-test")
    assert seasons == []

    # get_episodes - ahora captura timeout vía _fetch_with_flare_fallback y devuelve []
    episodes = await adapter.get_episodes("cuevana3:serie-test", 1)
    assert episodes == []


# ----------------------------------------------------------------------
# Test de estructura de datos
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_media_item_structure(adapter):
    """Validar que MediaItem tiene la estructura correcta según modelos."""
    adapter._client.get.return_value = MockResponse(CATALOG_HTML)

    items = await adapter.get_catalog()

    for item in items:
        assert isinstance(item, MediaItem)
        assert item.media_id.startswith("cuevana3:")
        assert item.provider == "cuevana3"
        assert item.provider_id
        assert item.title
        assert item.media_type in (MediaType.MOVIE, MediaType.SERIES)
        # year puede ser None
        # poster_url puede ser None


# ----------------------------------------------------------------------
# Tests de integración con VideoResolver
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_playback_direct_video_doodstream(adapter):
    """Validar resolución directa de video Doodstream via VideoResolver."""
    from unittest.mock import AsyncMock
    
    # Mockear el VideoResolver para devolver un PlaybackDescriptor directo
    mock_direct = PlaybackDescriptor(
        protocol="mp4",
        url="https://cdn.example.com/video.mp4?token=abc&expiry=123",
        headers={"Referer": "https://playmogo.com"},
    )
    adapter._video_resolver.resolve_doodstream = AsyncMock(return_value=mock_direct)
    
    # HTML con enlace a doodstream
    adapter._client.get.return_value = MockResponse(PLAYBACK_HTML)

    result = await adapter.resolve_playback("cuevana3:pelicula-prueba-2026")

    assert isinstance(result, PlaybackDescriptor)
    assert result.protocol == "mp4"
    assert result.url == "https://cdn.example.com/video.mp4?token=abc&expiry=123"
    assert result.headers.get("Referer") == "https://playmogo.com"
    adapter._video_resolver.resolve_doodstream.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_playback_doodstream_fallback_on_failure(adapter):
    """Validar fallback a embed cuando VideoResolver devuelve None."""
    from unittest.mock import AsyncMock
    
    # Mockear VideoResolver para devolver None (fallo en resolución directa)
    adapter._video_resolver.resolve_doodstream = AsyncMock(return_value=None)
    
    # HTML con servidor Doodstream
    adapter._client.get.return_value = MockResponse(PLAYBACK_HTML)

    result = await adapter.resolve_playback("cuevana3:pelicula-prueba-2026")

    assert isinstance(result, PlaybackDescriptor)
    assert result.protocol == "embed"
    assert "doodstream.com" in result.url
    adapter._video_resolver.resolve_doodstream.assert_awaited_once()


@pytest.mark.asyncio
async def test_adapter_close_closes_video_resolver(adapter):
    """Validar que adapter.close() cierra el VideoResolver."""
    from unittest.mock import AsyncMock
    
    # Mockear close del VideoResolver
    adapter._video_resolver.close = AsyncMock()
    # El cliente HTTP ya está mockeado en el fixture

    await adapter.close()

    adapter._video_resolver.close.assert_awaited_once()
    adapter._client.aclose.assert_awaited_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])