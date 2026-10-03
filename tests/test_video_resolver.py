"""Tests unitarios para VideoResolver con mocks de httpx."""

import pytest
import httpx
from unittest.mock import AsyncMock, patch

from src.services.video_resolver import VideoResolver
from src.models.catalog import PlaybackDescriptor


# ----------------------------------------------------------------------
# Fixtures de HTML de prueba
# ----------------------------------------------------------------------
# El código busca patrones: token=... y pass_md5/...
# Estos fixtures deben coincidir con esos patrones regex

DOODSTREAM_EMBED_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Doodstream Video</title>
</head>
<body>
    <script>
        // Configuración del player
        var config = { token: "abc123def456" };
        var pass_md5 = "xyz789";
    </script>
    <!-- token y pass_md5 también en HTML para que coincidan con regex -->
    <div data-token="token=abc123def456"></div>
    <div data-pass="pass_md5/xyz789"></div>
    <div id="player">Loading...</div>
</body>
</html>
"""

DOODSTREAM_EMBED_HTML_NO_TOKEN = """
<!DOCTYPE html>
<html>
<body>
    <script>
        var pass_md5 = "xyz789";
    </script>
    <div data-pass="pass_md5/xyz789"></div>
</body>
</html>
"""

DOODSTREAM_EMBED_HTML_NO_PASS_MD5 = """
<!DOCTYPE html>
<html>
<body>
    <script>
        var token = "abc123def456";
    </script>
    <div data-token="token=abc123def456"></div>
</body>
</html>
"""

DOODSTREAM_EMBED_HTML_ALT_FORMAT = """
<!DOCTYPE html>
<html>
<body>
    <div>
        token=abc123def456
        pass_md5/xyz789
    </div>
</body>
</html>
"""

PASS_MD5_RESPONSE = "https://cdn.doodstream.com/video/"


# ----------------------------------------------------------------------
# Helpers de mock
# ----------------------------------------------------------------------

class MockResponse:
    def __init__(self, text: str, status_code: int = 200, url: str = "https://doodstream.com/e/abc123"):
        self.text = text
        self.status_code = status_code
        self._url = url

    @property
    def url(self):
        return self._url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("Error", request=None, response=self)


@pytest.fixture
def resolver():
    """Fixture que provee un VideoResolver con cliente mockeado."""
    resolver = VideoResolver()
    # Reemplazar el cliente HTTP con un mock que tenga headers
    from unittest.mock import MagicMock
    mock_client = AsyncMock()
    mock_client.headers = MagicMock()
    mock_client.headers.get = MagicMock(return_value="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    resolver._client = mock_client
    yield resolver


# ----------------------------------------------------------------------
# Tests de is_doodstream (método estático)
# ----------------------------------------------------------------------

def test_is_doodstream_true():
    """Verificar dominios válidos de Doodstream/Playmogo."""
    valid_urls = [
        "https://doodstream.com/e/abc123",
        "https://playmogo.com/e/def456",
        "https://dood.la/e/ghi789",
        "https://d000d.com/e/jkl012",
        "https://dood.ws/e/mno345",
        "https://dood.yt/e/pqr678",
        "https://dooood.com/e/stu901",
        "http://doodstream.com/e/abc123",  # http también
        "https://doodstream.com/embed/abc123",  # rutas diferentes
    ]
    for url in valid_urls:
        assert VideoResolver.is_doodstream(url), f"Debería ser True para: {url}"


def test_is_doodstream_false():
    """Verificar dominios que NO corresponden a Doodstream/Playmogo."""
    invalid_urls = [
        "https://voe.sx/e/abc123",
        "https://vidhide.com/e/def456",
        "https://example.com/video",
        "https://filemoon.sx/e/ghi789",
        "https://streamtape.com/e/jkl012",
        "https://youtube.com/watch?v=abc",
        "https://netflix.com/title/123",
    ]
    for url in invalid_urls:
        assert not VideoResolver.is_doodstream(url), f"Debería ser False para: {url}"


# ----------------------------------------------------------------------
# Tests de resolve_doodstream
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_doodstream_success(resolver):
    """Simular respuesta HTML con token y pass_md5, y respuesta del endpoint pass_md5 con URL base CDN."""
    # Configurar respuestas mock en secuencia
    # 1. Primera llamada: GET a la página de embed
    # 2. Segunda llamada: GET a pass_md5
    mock_responses = [
        MockResponse(DOODSTREAM_EMBED_HTML, url="https://doodstream.com/e/abc123"),
        MockResponse(PASS_MD5_RESPONSE, url="https://doodstream.com/e/pass_md5/xyz789"),
    ]
    resolver._client.get.side_effect = mock_responses

    result = await resolver.resolve_doodstream("https://doodstream.com/e/abc123")

    # Verificar resultado
    assert result is not None
    assert isinstance(result, PlaybackDescriptor)
    assert result.protocol == "mp4"
    
    # Verificar que la URL contiene token, expiry y sufijo aleatorio de 10 caracteres
    assert "token=abc123def456" in result.url
    assert "expiry=" in result.url
    
    # Extraer sufijo aleatorio (10 caracteres alfanuméricos entre la URL base y ?token=)
    import re
    # La URL debe ser: https://cdn.doodstream.com/video/{random10}?token=...&expiry=...
    match = re.search(r'https://cdn\.doodstream\.com/video/([a-zA-Z0-9]{10})\?token=', result.url)
    assert match, f"URL no tiene sufijo aleatorio de 10 caracteres: {result.url}"
    random_suffix = match.group(1)
    assert len(random_suffix) == 10
    assert random_suffix.isalnum()
    
    # Verificar header Referer correcto (base_url = page_url sin el último segmento)
    # page_url = https://doodstream.com/e/abc123 -> base_url = https://doodstream.com/e
    assert result.headers.get("Referer") == "https://doodstream.com/e"
    
    # Verificar que se hicieron las dos llamadas esperadas
    assert resolver._client.get.call_count == 2
    
    # Verificar primera llamada (embed page)
    call1_args = resolver._client.get.call_args_list[0]
    assert call1_args[0][0] == "https://doodstream.com/e/abc123"
    
    # Verificar segunda llamada (pass_md5) con header Referer
    # base_url = page_url.rsplit('/', 1)[0] = https://doodstream.com/e
    # pass_url = f"{base_url}/pass_md5/{pass_path}" = https://doodstream.com/e/pass_md5/xyz789
    call2_args = resolver._client.get.call_args_list[1]
    assert call2_args[0][0] == "https://doodstream.com/e/pass_md5/xyz789"
    assert call2_args[1]["headers"]["Referer"] == "https://doodstream.com/e/abc123"


@pytest.mark.asyncio
async def test_resolve_doodstream_no_token(resolver):
    """HTML sin token retorna None."""
    resolver._client.get.return_value = MockResponse(DOODSTREAM_EMBED_HTML_NO_TOKEN)

    result = await resolver.resolve_doodstream("https://doodstream.com/e/abc123")

    assert result is None
    assert resolver._client.get.call_count == 1


@pytest.mark.asyncio
async def test_resolve_doodstream_no_pass_md5(resolver):
    """HTML sin pass_md5 retorna None."""
    resolver._client.get.return_value = MockResponse(DOODSTREAM_EMBED_HTML_NO_PASS_MD5)

    result = await resolver.resolve_doodstream("https://doodstream.com/e/abc123")

    assert result is None
    assert resolver._client.get.call_count == 1


@pytest.mark.asyncio
async def test_resolve_doodstream_http_error(resolver):
    """Excepción HTTP en la petición inicial retorna None."""
    resolver._client.get.side_effect = httpx.HTTPError("Connection error")

    result = await resolver.resolve_doodstream("https://doodstream.com/e/abc123")

    assert result is None
    assert resolver._client.get.call_count == 1


@pytest.mark.asyncio
async def test_resolve_doodstream_pass_md5_error(resolver):
    """Excepción HTTP en la petición pass_md5 retorna None."""
    # Primera llamada OK, segunda falla
    mock_responses = [
        MockResponse(DOODSTREAM_EMBED_HTML, url="https://doodstream.com/e/abc123"),
        httpx.HTTPError("Connection error"),
    ]
    resolver._client.get.side_effect = mock_responses

    result = await resolver.resolve_doodstream("https://doodstream.com/e/abc123")

    assert result is None
    assert resolver._client.get.call_count == 2


@pytest.mark.asyncio
async def test_resolve_doodstream_invalid_pass_md5_response(resolver):
    """Respuesta de pass_md5 no válida (no empieza por http) retorna None."""
    mock_responses = [
        MockResponse(DOODSTREAM_EMBED_HTML, url="https://doodstream.com/e/abc123"),
        MockResponse("invalid_response_not_url", url="https://doodstream.com/e/pass_md5/xyz789"),
    ]
    resolver._client.get.side_effect = mock_responses

    result = await resolver.resolve_doodstream("https://doodstream.com/e/abc123")

    assert result is None
    assert resolver._client.get.call_count == 2


@pytest.mark.asyncio
async def test_resolve_doodstream_alternative_token_format(resolver):
    """Token y pass_md5 en formato alternativo (sin 'var')."""
    mock_responses = [
        MockResponse(DOODSTREAM_EMBED_HTML_ALT_FORMAT, url="https://playmogo.com/e/abc123"),
        MockResponse(PASS_MD5_RESPONSE, url="https://playmogo.com/e/pass_md5/xyz789"),
    ]
    resolver._client.get.side_effect = mock_responses

    result = await resolver.resolve_doodstream("https://playmogo.com/e/abc123")

    assert result is not None
    assert result.protocol == "mp4"
    assert "token=abc123def456" in result.url
    # page_url = https://playmogo.com/e/abc123 -> base_url = https://playmogo.com/e
    assert result.headers.get("Referer") == "https://playmogo.com/e"


@pytest.mark.asyncio
async def test_resolve_doodstream_different_domain(resolver):
    """Verificar que funciona con diferentes dominios Doodstream."""
    domains = ["dood.la", "d000d.com", "dood.ws", "dood.yt", "dooood.com"]
    
    for domain in domains:
        embed_url = f"https://{domain}/e/test123"
        mock_responses = [
            MockResponse(DOODSTREAM_EMBED_HTML, url=embed_url),
            MockResponse(PASS_MD5_RESPONSE, url=f"https://{domain}/e/pass_md5/xyz789"),
        ]
        resolver._client.get.side_effect = mock_responses
        resolver._client.reset_mock()

        result = await resolver.resolve_doodstream(embed_url)

        assert result is not None, f"Falló para dominio: {domain}"
        assert result.protocol == "mp4"
        assert f"Referer" in result.headers
        # base_url = https://{domain}/e (sin el último segmento)
        assert result.headers["Referer"] == f"https://{domain}/e"


# ----------------------------------------------------------------------
# Test de close
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_calls_aclose(resolver):
    """Verificar que close() llama a aclose() del cliente."""
    await resolver.close()
    resolver._client.aclose.assert_awaited_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])