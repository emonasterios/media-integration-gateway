"""Tests de integración para Cuevana3Adapter con mocks HTTP."""

import pytest
import httpx
import re
from unittest.mock import AsyncMock, patch
from bs4 import BeautifulSoup

from src.adapters.cuevana3 import Cuevana3Adapter, CatalogCrawlError
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
async def test_get_catalog_follows_next_until_it_disappears(adapter, monkeypatch):
    """La paginación no tiene un máximo fijo y deduplica por provider_id."""
    first = CATALOG_HTML.replace(
        "</body>",
        '<a class="next page-numbers" href="/peliculas/page/2/"></a></body>',
    )
    second = CATALOG_HTML
    adapter._client.get.side_effect = [MockResponse(first), MockResponse(second)]

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("src.adapters.cuevana3.asyncio.sleep", no_sleep)
    items = await adapter.get_catalog()

    assert len(items) == 4
    assert adapter._client.get.await_count == 2


@pytest.mark.asyncio
async def test_get_catalog_failure_after_first_page_is_explicit(adapter, monkeypatch):
    """Un fallo intermedio no puede parecer un catálogo completo."""
    from src.adapters.cuevana3 import CatalogCrawlError

    first = CATALOG_HTML.replace(
        "</body>",
        '<a class="next page-numbers" href="/peliculas/page/2/"></a></body>',
    )
    calls = 0

    async def first_then_timeout(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockResponse(first)
        raise httpx.TimeoutException("Timeout")

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("src.adapters.cuevana3.asyncio.sleep", no_sleep)
    adapter._client.get.side_effect = first_then_timeout
    with pytest.raises(CatalogCrawlError, match="snapshot incompleto"):
        await adapter.get_catalog()
    assert adapter._client.get.await_count == 4


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

    # Con paginación el adapter hace varias llamadas; verificar que la primera
    # fue a la URL de categoría
    adapter._client.get.assert_any_call("/genero/accion/")
    assert len(items) >= 1


@pytest.mark.asyncio
async def test_get_catalog_timeout_is_explicit(adapter):
    """Un timeout no se confunde con un catálogo vacío completo."""
    from src.adapters.cuevana3 import CatalogCrawlError

    adapter._client.get.side_effect = httpx.TimeoutException("Timeout")

    with pytest.raises(CatalogCrawlError, match="snapshot incompleto"):
        await adapter.get_catalog()


@pytest.mark.asyncio
async def test_get_catalog_http_error_is_explicit(adapter):
    """Un error HTTP no se confunde con un catálogo vacío completo."""
    from src.adapters.cuevana3 import CatalogCrawlError

    adapter._client.get.side_effect = httpx.HTTPError("Connection error")

    with pytest.raises(CatalogCrawlError, match="snapshot incompleto"):
        await adapter.get_catalog()


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

    # Ya no hay fallback a embed: mockear la resolución directa del resolver
    mock_direct = PlaybackDescriptor(
        protocol="mp4",
        url="https://cdn.example.com/video.mp4?token=abc&expiry=123",
        headers={"Referer": "https://doodstream.com"},
    )
    adapter._video_resolver.resolve_doodstream = AsyncMock(return_value=mock_direct)

    result = await adapter.resolve_playback("cuevana3:pelicula-prueba-2026")

    assert isinstance(result, PlaybackDescriptor)
    assert result.protocol == "mp4"
    assert result.url == mock_direct.url
    adapter._video_resolver.resolve_doodstream.assert_awaited_once_with(
        "https://doodstream.com/e/abc123"
    )


@pytest.mark.asyncio
async def test_resolve_playback_from_div_data_mdl(adapter):
    """Validar resolve_playback con div._3CT5n_0 y data-mdl (sin iframe)."""
    adapter._client.get.return_value = MockResponse(PLAYBACK_HTML_NO_IFRAME)

    # Ya no hay fallback a embed: mockear la resolución directa del resolver
    mock_direct = PlaybackDescriptor(
        protocol="mp4",
        url="https://cdn.example.com/video.mp4?token=abc&expiry=123",
        headers={"Referer": "https://doodstream.com"},
    )
    adapter._video_resolver.resolve_doodstream = AsyncMock(return_value=mock_direct)

    result = await adapter.resolve_playback("cuevana3:pelicula-prueba-2026")

    assert isinstance(result, PlaybackDescriptor)
    assert result.protocol == "mp4"
    assert result.url == mock_direct.url
    adapter._video_resolver.resolve_doodstream.assert_awaited_once_with(
        "https://doodstream.com/e/xyz789"
    )


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

    # filemoon no tiene resolver directo y ya no existe fallback a embed:
    # el candidato se extrae del script pero la resolución lanza ValueError
    with pytest.raises(ValueError, match="Ningún servidor funcionó"):
        await adapter.resolve_playback("cuevana3:pelicula-prueba-2026")


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

    mock_direct = PlaybackDescriptor(
        protocol="mp4",
        url="https://cdn.example.com/video.mp4?token=abc&expiry=123",
        headers={"Referer": "https://doodstream.com"},
    )
    adapter._video_resolver.resolve_doodstream = AsyncMock(return_value=mock_direct)

    result = await adapter.resolve_playback("cuevana3:pelicula-prueba-2026")

    assert isinstance(result, PlaybackDescriptor)
    assert result.protocol == "mp4"
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

    # get_catalog - el fallo es explícito para impedir sincronizaciones destructivas
    from src.adapters.cuevana3 import CatalogCrawlError
    with pytest.raises(CatalogCrawlError, match="snapshot incompleto"):
        await adapter.get_catalog()

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
    """Validar que si VideoResolver devuelve None NO hay fallback a embed (ValueError)."""
    from unittest.mock import AsyncMock
    
    # Mockear VideoResolver para devolver None (fallo en resolución directa)
    adapter._video_resolver.resolve_doodstream = AsyncMock(return_value=None)
    
    # HTML con servidor Doodstream
    adapter._client.get.return_value = MockResponse(PLAYBACK_HTML)

    # Sin fallback a embed: la resolución fallida lanza ValueError
    with pytest.raises(ValueError, match="Ningún servidor funcionó"):
        await adapter.resolve_playback("cuevana3:pelicula-prueba-2026")
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


# ----------------------------------------------------------------------
# Tests de descubrimiento reanudable (discover_resumable)
# ----------------------------------------------------------------------


@pytest.fixture
async def adapter_with_mock():
    """Fixture que provee un Cuevana3Adapter con cliente HTTP mockeado."""
    adapter = Cuevana3Adapter()
    adapter._client = AsyncMock()
    yield adapter
    await adapter.close()


# HTML helper para páginas de catálogo simuladas

def make_catalog_page(items: list[dict], next_href: str | None = None) -> str:
    """Genera HTML de página de catálogo con los items dados y link next opcional."""
    html_parts = ["<!DOCTYPE html><html><body>"]
    for item in items:
        href = item.get("href", f"/pelicula/{item['provider_id']}/")
        title = item.get("title", item["provider_id"])
        poster = item.get("poster", "/img/poster.jpg")
        year = item.get("year", 2024)
        media_type = item.get("media_type", "movie")
        html_parts.append(
            f'<div class="TPost">'
            f'  <a href="{href}">{title}'
            f'    <figure class="Objf">'
            f'      <img src="{poster}" alt="{title}" />'
            f'    </figure>'
            f'  </a>'
            f'  <span class="Year">{year}</span>'
            f'</div>'
        )
    if next_href:
        html_parts.append(f'<a class="next page-numbers" href="{next_href}"></a>')
    html_parts.append("</body></html>")
    return "\n".join(html_parts)


@pytest.mark.asyncio
async def test_cuevana3_discover_resumable_more_than_20_pages_complete(adapter_with_mock, tmp_path):
    """Procesa más de 20 páginas consecutivas y finaliza con status complete."""
    adapter = adapter_with_mock
    num_pages = 22
    items_per_page = 3
    total_items = num_pages * items_per_page

    # Preparar mocks: 22 páginas con next_href hasta la última
    async def mock_get(url, *args, **kwargs):
        page_num = int(re.search(r'page/(\d+)', url).group(1)) if 'page/' in url else 1
        next_href = f"/peliculas/page/{page_num + 1}/" if page_num < num_pages else None
        items = [
            {
                "provider_id": f"movie-{page_num}-{i}",
                "title": f"Movie {page_num}-{i}",
                "poster": f"/img/poster-{page_num}-{i}.jpg",
                "year": 2024,
                "media_type": "movie",
                "href": f"/pelicula/movie-{page_num}-{i}/",
            }
            for i in range(items_per_page)
        ]
        return MockResponse(make_catalog_page(items, next_href))

    adapter._client.get.side_effect = mock_get

    # Desactivar sleep
    async def no_sleep(_):
        return None
    import src.adapters.cuevana3 as cuevana3_module
    original_sleep = cuevana3_module.asyncio.sleep
    cuevana3_module.asyncio.sleep = no_sleep
    try:
        checkpoint_path = tmp_path / "checkpoint_22pages.json"
        checkpoint = await adapter.discover_resumable(checkpoint_path=checkpoint_path, page_limit=None)

        # Verificaciones
        assert checkpoint.status == "complete"
        assert checkpoint.next_page is None
        assert len(checkpoint.pages_completed) == num_pages
        assert len(checkpoint.items) == total_items
        assert checkpoint.pages_completed == list(range(1, num_pages + 1))

        # Verificar que se llamó al cliente HTTP para cada página
        assert adapter._client.get.await_count == num_pages
    finally:
        cuevana3_module.asyncio.sleep = original_sleep


@pytest.mark.asyncio
async def test_cuevana3_discover_resumable_intermediate_failure_retries_and_incomplete(adapter_with_mock, tmp_path):
    """Falla persistente en página intermedia agota 3 reintentos y deja checkpoint incomplete."""
    adapter = adapter_with_mock

    call_count = [0]

    async def mock_get(url, *args, **kwargs):
        call_count[0] += 1
        page_num = int(re.search(r'page/(\d+)', url).group(1)) if 'page/' in url else 1

        if page_num == 5:
            # Página 5: fallar siempre (3 reintentos)
            raise httpx.TimeoutException("Timeout simulado en página 5")

        # Páginas 1-4: éxito
        items = [
            {
                "provider_id": f"movie-{page_num}-{i}",
                "title": f"Movie {page_num}-{i}",
                "poster": f"/img/poster-{page_num}-{i}.jpg",
                "year": 2024,
                "media_type": "movie",
                "href": f"/pelicula/movie-{page_num}-{i}/",
            }
            for i in range(3)
        ]
        next_href = f"/peliculas/page/{page_num + 1}/"
        return MockResponse(make_catalog_page(items, next_href))

    adapter._client.get.side_effect = mock_get

    # Desactivar sleep
    import src.adapters.cuevana3 as cuevana3_module
    original_sleep = cuevana3_module.asyncio.sleep
    async def no_sleep(_):
        return None
    cuevana3_module.asyncio.sleep = no_sleep
    try:
        checkpoint_path = tmp_path / "checkpoint_fail_page5.json"
        with pytest.raises(CatalogCrawlError, match="Error en página 5"):
            await adapter.discover_resumable(checkpoint_path=checkpoint_path, page_limit=None)
    finally:
        cuevana3_module.asyncio.sleep = original_sleep

    # Verificar checkpoint guardado: 4 páginas completadas, next_page = página 5
    from src.services.catalog_checkpoint import load_checkpoint
    saved = load_checkpoint(checkpoint_path)
    assert saved.status == "incomplete"
    assert saved.next_page == "/peliculas/page/5/"
    assert len(saved.pages_completed) == 4
    assert saved.pages_completed == [1, 2, 3, 4]
    assert len(saved.items) == 12  # 4 páginas * 3 items

    # Verificar 3 reintentos en página 5 + 4 páginas exitosas = 7 llamadas totales
    # (4 páginas * 1 intento + 1 página * 3 reintentos = 7)
    assert call_count[0] == 7


@pytest.mark.asyncio
async def test_cuevana3_discover_resumable_resume_skips_confirmed_pages(adapter_with_mock, tmp_path):
    """Reanudar desde checkpoint incomplete no vuelve a solicitar páginas ya confirmadas."""
    adapter = adapter_with_mock

    # 1. Crear checkpoint incompleto simulado (páginas 1-4 completadas, next_page = 5)
    from src.services.catalog_checkpoint import CatalogCheckpoint, save_checkpoint
    initial_ckpt = CatalogCheckpoint(
        provider="cuevana3",
        category=None,
        initial_path="/peliculas/",
        next_page="/peliculas/page/5/",
        pages_completed=[1, 2, 3, 4],
        items=[
            {
                "provider": "cuevana3",
                "provider_id": f"movie-{p}-{i}",
                "title": f"Movie {p}-{i}",
                "url": f"https://cuevana3i.cc/pelicula/movie-{p}-{i}/",
                "poster": f"https://cuevana3i.cc/img/poster-{p}-{i}.jpg",
                "media_type": "movie",
                "year": 2024,
                "category": None,
            }
            for p in range(1, 5) for i in range(3)
        ],
        status="incomplete",
    )
    checkpoint_path = tmp_path / "checkpoint_resume.json"
    save_checkpoint(initial_ckpt, checkpoint_path)

    # 2. Mock: páginas 5-7 exitosas, página 8 final (sin next)
    call_count = [0]
    pages_requested = []

    async def mock_get(url, *args, **kwargs):
        call_count[0] += 1
        page_num = int(re.search(r'page/(\d+)', url).group(1)) if 'page/' in url else 1
        pages_requested.append(page_num)

        items = [
            {
                "provider_id": f"movie-{page_num}-{i}",
                "title": f"Movie {page_num}-{i}",
                "poster": f"/img/poster-{page_num}-{i}.jpg",
                "year": 2024,
                "media_type": "movie",
                "href": f"/pelicula/movie-{page_num}-{i}/",
            }
            for i in range(3)
        ]
        next_href = f"/peliculas/page/{page_num + 1}/" if page_num < 7 else None
        return MockResponse(make_catalog_page(items, next_href))

    adapter._client.get.side_effect = mock_get

    # Desactivar sleep
    import src.adapters.cuevana3 as cuevana3_module
    original_sleep = cuevana3_module.asyncio.sleep
    async def no_sleep(_):
        return None
    cuevana3_module.asyncio.sleep = no_sleep
    try:
        checkpoint = await adapter.discover_resumable(checkpoint_path=checkpoint_path, page_limit=None)
    finally:
        cuevana3_module.asyncio.sleep = original_sleep

    # Verificaciones
    assert checkpoint.status == "complete"
    assert len(checkpoint.pages_completed) == 7  # 4 previas + 3 nuevas
    assert checkpoint.pages_completed == [1, 2, 3, 4, 5, 6, 7]
    assert len(checkpoint.items) == 21  # 7 páginas * 3 items

    # CRITICAL: Solo se deben haber solicitado páginas 5, 6, 7 (NO 1-4)
    assert pages_requested == [5, 6, 7], f"Páginas solicitadas: {pages_requested}"
    assert call_count[0] == 3


@pytest.mark.asyncio
async def test_cuevana3_discover_resumable_second_failure_preserves_checkpoint(adapter_with_mock, tmp_path):
    """Segunda falla al reanudar preserva items acumulados y mantiene incomplete."""
    adapter = adapter_with_mock

    # 1. Checkpoint con 7 páginas completadas (páginas 1-7)
    from src.services.catalog_checkpoint import CatalogCheckpoint, save_checkpoint, load_checkpoint
    initial_ckpt = CatalogCheckpoint(
        provider="cuevana3",
        category=None,
        initial_path="/peliculas/",
        next_page="/peliculas/page/8/",
        pages_completed=[1, 2, 3, 4, 5, 6, 7],
        items=[
            {
                "provider": "cuevana3",
                "provider_id": f"movie-{p}-{i}",
                "title": f"Movie {p}-{i}",
                "url": f"https://cuevana3i.cc/pelicula/movie-{p}-{i}/",
                "poster": f"https://cuevana3i.cc/img/poster-{p}-{i}.jpg",
                "media_type": "movie",
                "year": 2024,
                "category": None,
            }
            for p in range(1, 8) for i in range(2)
        ],  # 7 páginas * 2 = 14 items
        status="incomplete",
    )
    checkpoint_path = tmp_path / "checkpoint_second_fail.json"
    save_checkpoint(initial_ckpt, checkpoint_path)

    # 2. Reanudar y fallar en página 8 (3 reintentos)
    call_count = [0]

    async def mock_get(url, *args, **kwargs):
        call_count[0] += 1
        page_num = int(re.search(r'page/(\d+)', url).group(1)) if 'page/' in url else 1

        if page_num == 8:
            raise httpx.TimeoutException("Timeout simulado en página 8")

        # No debería llegar aquí porque la reanudación empieza en página 8
        items = []
        return MockResponse(make_catalog_page(items, None))

    adapter._client.get.side_effect = mock_get

    import src.adapters.cuevana3 as cuevana3_module
    original_sleep = cuevana3_module.asyncio.sleep
    async def no_sleep(_):
        return None
    cuevana3_module.asyncio.sleep = no_sleep
    try:
        with pytest.raises(CatalogCrawlError, match="Error en página 8"):
            await adapter.discover_resumable(checkpoint_path=checkpoint_path, page_limit=None)
    finally:
        cuevana3_module.asyncio.sleep = original_sleep

    # Verificar checkpoint resultante: items preservados, status incomplete, next_page = 8
    saved = load_checkpoint(checkpoint_path)
    assert saved.status == "incomplete"
    assert saved.next_page == "/peliculas/page/8/"
    assert saved.pages_completed == [1, 2, 3, 4, 5, 6, 7]
    assert len(saved.items) == 14  # Items originales preservados

    # Verificar que los items específicos están intactos
    provider_ids = {(item["provider"], item["provider_id"]) for item in saved.items}
    for p in range(1, 8):
        for i in range(2):
            assert ("cuevana3", f"movie-{p}-{i}") in provider_ids

    # 3 reintentos en página 8
    assert call_count[0] == 3


@pytest.mark.asyncio
async def test_cuevana3_discover_resumable_deduplication_across_pages(adapter_with_mock, tmp_path):
    """Películas con URLs repetidas entre páginas y tras reanudación aparecen una sola vez."""
    adapter = adapter_with_mock

    # 1. Checkpoint con 3 páginas, algunas items repetidos en página 3
    from src.services.catalog_checkpoint import CatalogCheckpoint, save_checkpoint, load_checkpoint
    initial_ckpt = CatalogCheckpoint(
        provider="cuevana3",
        category=None,
        initial_path="/peliculas/",
        next_page="/peliculas/page/4/",
        pages_completed=[1, 2, 3],
        items=[
            # Página 1: movie-A, movie-B
            {"provider": "cuevana3", "provider_id": "movie-A", "title": "Movie A",
             "url": "https://cuevana3i.cc/pelicula/movie-A/", "poster": "https://cuevana3i.cc/img/a.jpg",
             "media_type": "movie", "year": 2024, "category": None},
            {"provider": "cuevana3", "provider_id": "movie-B", "title": "Movie B",
             "url": "https://cuevana3i.cc/pelicula/movie-B/", "poster": "https://cuevana3i.cc/img/b.jpg",
             "media_type": "movie", "year": 2024, "category": None},
            # Página 2: movie-C, movie-D
            {"provider": "cuevana3", "provider_id": "movie-C", "title": "Movie C",
             "url": "https://cuevana3i.cc/pelicula/movie-C/", "poster": "https://cuevana3i.cc/img/c.jpg",
             "media_type": "movie", "year": 2024, "category": None},
            {"provider": "cuevana3", "provider_id": "movie-D", "title": "Movie D",
             "url": "https://cuevana3i.cc/pelicula/movie-D/", "poster": "https://cuevana3i.cc/img/d.jpg",
             "media_type": "movie", "year": 2024, "category": None},
            # Página 3: movie-E, movie-A (duplicado con página 1)
            {"provider": "cuevana3", "provider_id": "movie-E", "title": "Movie E",
             "url": "https://cuevana3i.cc/pelicula/movie-E/", "poster": "https://cuevana3i.cc/img/e.jpg",
             "media_type": "movie", "year": 2024, "category": None},
            {"provider": "cuevana3", "provider_id": "movie-A", "title": "Movie A (dup)",
             "url": "https://cuevana3i.cc/pelicula/movie-A/", "poster": "https://cuevana3i.cc/img/a.jpg",
             "media_type": "movie", "year": 2024, "category": None},
        ],
        status="incomplete",
    )
    checkpoint_path = tmp_path / "checkpoint_dedup.json"
    save_checkpoint(initial_ckpt, checkpoint_path)

    # 2. Reanudar: página 4 tiene movie-B (dup con pág 1) y movie-F (nuevo)
    #    página 5 es la última
    call_count = [0]

    async def mock_get(url, *args, **kwargs):
        call_count[0] += 1
        page_num = int(re.search(r'page/(\d+)', url).group(1)) if 'page/' in url else 1

        if page_num == 4:
            items = [
                {
                    "provider_id": "movie-B",  # Duplicado
                    "title": "Movie B (dup)",
                    "poster": "/img/b.jpg",
                    "year": 2024,
                    "media_type": "movie",
                    "href": "/pelicula/movie-B/",
                },
                {
                    "provider_id": "movie-F",  # Nuevo
                    "title": "Movie F",
                    "poster": "/img/f.jpg",
                    "year": 2024,
                    "media_type": "movie",
                    "href": "/pelicula/movie-F/",
                },
            ]
            next_href = "/peliculas/page/5/"
            return MockResponse(make_catalog_page(items, next_href))
        elif page_num == 5:
            items = [
                {
                    "provider_id": "movie-G",
                    "title": "Movie G",
                    "poster": "/img/g.jpg",
                    "year": 2024,
                    "media_type": "movie",
                    "href": "/pelicula/movie-G/",
                },
            ]
            next_href = None  # Última página
            return MockResponse(make_catalog_page(items, next_href))
        return MockResponse(make_catalog_page([], None))

    adapter._client.get.side_effect = mock_get

    import src.adapters.cuevana3 as cuevana3_module
    original_sleep = cuevana3_module.asyncio.sleep
    async def no_sleep(_):
        return None
    cuevana3_module.asyncio.sleep = no_sleep
    try:
        checkpoint = await adapter.discover_resumable(checkpoint_path=checkpoint_path, page_limit=None)
    finally:
        cuevana3_module.asyncio.sleep = original_sleep

    # Verificaciones finales
    assert checkpoint.status == "complete"
    assert checkpoint.pages_completed == [1, 2, 3, 4, 5]

    # Debe haber exactamente 7 items únicos: A, B, C, D, E, F, G
    assert len(checkpoint.items) == 7
    provider_ids = {(item["provider"], item["provider_id"]) for item in checkpoint.items}
    expected_ids = {("cuevana3", pid) for pid in ["movie-A", "movie-B", "movie-C", "movie-D", "movie-E", "movie-F", "movie-G"]}
    assert provider_ids == expected_ids

    # Verificar que no hay duplicados: cada provider_id aparece una vez
    from collections import Counter
    pid_counts = Counter(item["provider_id"] for item in checkpoint.items)
    assert all(count == 1 for count in pid_counts.values()), f"Duplicados encontrados: {pid_counts}"

    # 2 llamadas HTTP (páginas 4 y 5)
    assert call_count[0] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
