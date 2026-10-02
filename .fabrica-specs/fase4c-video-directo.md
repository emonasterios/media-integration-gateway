# Fase 4c: Resolución de video directo (Doodstream/Playmogo)

Implementar `resolve_direct_video()` en `Cuevana3Adapter` que extrae la URL `.mp4` real del CDN siguiendo la mecánica descubierta en el spike.

## Contexto

El spike (`docs/spike-video-extract.md`) documentó la cadena completa:

```
playmogo.com/e/{file_id}
  → HTML con Video.js + JS
  → GET /pass_md5/{path} → URL base del CDN
  → Construir: base + random(10) + ?token=...&expiry=timestamp
  → URL final .mp4 en cloudatacdn.com
```

El endpoint `resolve_playback()` actual devuelve `protocol="embed"` con la URL del servidor de embed. Este cambio agrega la capacidad de resolver el video directo cuando el servidor es Doodstream/Playmogo.

## Qué hacer

### Paso 1: Nuevo módulo `src/services/video_resolver.py`

Crear un servicio dedicado para la extracción de video directo de servidores de streaming.

```python
"""Resolución de URLs de video directo desde servidores de streaming."""

from __future__ import annotations

import logging
import random
import re
import string
import time
from typing import Optional
from urllib.parse import urljoin

import httpx

from src.models.catalog import PlaybackDescriptor

logger = logging.getLogger(__name__)

# Servidores que soportan resolución de video directo
DOODSTREAM_DOMAINS = ("doodstream.com", "dood.la", "dood.ws", "playmogo.com", "d000d.com", "dood.yt", "dooood.com")

class VideoResolver:
    """Resuelve URLs de video directo desde servidores tipo Doodstream."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=20.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
            },
        )

    async def resolve_doodstream(self, embed_url: str) -> Optional[PlaybackDescriptor]:
        """Resuelve URL de video directo desde Doodstream/Playmogo.

        Cadena de extracción:
        1. GET embed page → HTML con Video.js
        2. Extraer token y pass_md5 path del HTML
        3. GET /pass_md5/{path} con Referer → URL base del CDN
        4. Construir URL final: base + random(10) + ?token=...&expiry=...
        """
        # Normalizar URL: si es doodstream, seguir redirecciones hasta playmogo
        try:
            resp = await self._client.get(embed_url)
            page_url = str(resp.url)
            html = resp.text
        except Exception as e:
            logger.warning("Error accediendo a %s: %s", embed_url, e)
            return None

        # Extraer token del HTML
        token_match = re.search(r"token=([a-zA-Z0-9]+)", html)
        if not token_match:
            logger.debug("No se encontró token en %s", page_url)
            return None
        token = token_match.group(1)

        # Extraer pass_md5 path
        pass_match = re.search(r"pass_md5/([^'\"]+)", html)
        if not pass_match:
            logger.debug("No se encontró pass_md5 en %s", page_url)
            return None
        pass_path = pass_match.group(1)

        # Obtener URL base del CDN
        base_url = page_url.rsplit("/", 1)[0]  # e.g. https://playmogo.com
        pass_url = f"{base_url}/pass_md5/{pass_path}"

        try:
            pass_resp = await self._client.get(
                pass_url,
                headers={"Referer": page_url},
            )
            cdn_base = pass_resp.text.strip()
        except Exception as e:
            logger.warning("Error obteniendo pass_md5: %s", e)
            return None

        if not cdn_base or not cdn_base.startswith("http"):
            logger.debug("pass_md5 no devolvió URL válida: %r", cdn_base)
            return None

        # Construir URL final: base + random(10) + ?token=...&expiry=...
        random_suffix = "".join(random.choices(string.ascii_letters + string.digits, k=10))
        expiry = int(time.time() * 1000)
        video_url = f"{cdn_base}{random_suffix}?token={token}&expiry={expiry}"

        return PlaybackDescriptor(
            protocol="mp4",
            url=video_url,
            headers={"Referer": base_url},
        )

    @staticmethod
    def is_doodstream(url: str) -> bool:
        """Verifica si la URL pertenece a un servidor Doodstream/Playmogo."""
        url_lower = url.lower()
        return any(domain in url_lower for domain in DOODSTREAM_DOMAINS)

    async def close(self) -> None:
        await self._client.aclose()
```

### Paso 2: Integrar en `Cuevana3Adapter.resolve_playback()`

Modificar `resolve_playback()` para que, después de obtener la URL del embed server, intente resolver el video directo si el servidor es Doodstream/Playmogo.

En `src/adapters/cuevana3.py`:

1. Agregar import al inicio:
```python
from src.services.video_resolver import VideoResolver
```

2. En `__init__`, después de `self._flaresolverr = FlareSolverrClient()`, agregar:
```python
self._video_resolver = VideoResolver()
```

3. En `resolve_playback()`, después de cada bloque que retorna un `PlaybackDescriptor` con `protocol="embed"`, agregar lógica para intentar resolución directa. Reemplazar cada retorno de embed con:

```python
# Intentar resolver video directo si es Doodstream/Playmogo
if VideoResolver.is_doodstream(server_url):
    try:
        direct = await self._video_resolver.resolve_doodstream(server_url)
        if direct:
            return direct
    except Exception as e:
        logger.warning("Fallo resolviendo video directo: %s", e)
# Fallback a embed
return PlaybackDescriptor(
    protocol="embed",
    url=server_url,
    headers={"Referer": self._base},
)
```

Aplicar esto en los 4 puntos donde se retorna un PlaybackDescriptor con `protocol="embed"`:
- Después de `li[data-server]` (línea ~393)
- Después de `_extract_server_from_list` (línea ~401)
- Después de `_extract_server_from_scripts` (línea ~410)
- Después del fallback `for link in soup.find_all("a", href=True)` (línea ~418)

4. En `close()`, agregar antes del `await self._client.aclose()`:
```python
await self._video_resolver.close()
```

### Paso 3: Tests para `VideoResolver`

Crear `tests/test_video_resolver.py`:

```python
"""Tests para VideoResolver (resolución de video directo)."""

import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from src.services.video_resolver import VideoResolver
from src.models.catalog import PlaybackDescriptor


PLAYMOGO_HTML = """
<!DOCTYPE html>
<html>
<head><script src="video.js"></script></head>
<body>
<script>
var token = "s2ov4941r1l844sw0u3a14gr";
var expiry = Date.now();
function makePlay() {
    var a = "";
    for (var o = 0; 10 > o; o++)
        a += "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"[Math.floor(Math.random() * 62)];
    return a + "?token=" + token + "&expiry=" + expiry;
}
</script>
<script>
$.get('/pass_md5/267031004-181-178-1759449600-abc123/s2ov4941r1l844sw0u3a14gr', function(data) {
    dsplayer.src({ type: "video/mp4", src: data + makePlay() });
});
</script>
</body>
</html>
"""


@pytest.fixture
def resolver():
    r = VideoResolver()
    r._client = AsyncMock()
    yield r


@pytest.mark.asyncio
async def test_resolve_doodstream_success(resolver):
    """Resolver URL de video directo desde Playmogo."""
    mock_page = MagicMock()
    mock_page.url = "https://playmogo.com/e/jtri5tfbukk6"
    mock_page.text = PLAYMOGO_HTML

    mock_pass = MagicMock()
    mock_pass.text = "https://fj173o.cloudatacdn.com/u5kjvip74la3sdgge6n3gpaclldtb57jkldye3e55rq4l7gsymecnwwbgumq/hdnsjes9ln~"

    resolver._client.get = AsyncMock(side_effect=[mock_page, mock_pass])

    result = await resolver.resolve_doodstream("https://doodstream.com/e/jtri5tfbukk6")

    assert result is not None
    assert isinstance(result, PlaybackDescriptor)
    assert result.protocol == "mp4"
    assert result.url.startswith("https://fj173o.cloudatacdn.com/")
    assert "token=s2ov4941r1l844sw0u3a14gr" in result.url
    assert "expiry=" in result.url
    # El random suffix tiene 10 chars antes del ?
    url_path = result.url.split("?")[0]
    cdn_base = mock_pass.text
    suffix = url_path[len(cdn_base):]
    assert len(suffix) == 10


@pytest.mark.asyncio
async def test_resolve_doodstream_no_token(resolver):
    """Sin token en el HTML → None."""
    mock_page = MagicMock()
    mock_page.url = "https://playmogo.com/e/abc123"
    mock_page.text = "<html><body>No token here</body></html>"

    resolver._client.get = AsyncMock(return_value=mock_page)

    result = await resolver.resolve_doodstream("https://doodstream.com/e/abc123")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_doodstream_no_pass_md5(resolver):
    """Sin pass_md5 en el HTML → None."""
    mock_page = MagicMock()
    mock_page.url = "https://playmogo.com/e/abc123"
    mock_page.text = '<script>var token = "abc123";</script>'

    resolver._client.get = AsyncMock(return_value=mock_page)

    result = await resolver.resolve_doodstream("https://doodstream.com/e/abc123")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_doodstream_http_error(resolver):
    """Error HTTP accediendo al embed → None."""
    resolver._client.get = AsyncMock(side_effect=httpx.HTTPError("Connection error"))

    result = await resolver.resolve_doodstream("https://doodstream.com/e/abc123")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_doodstream_pass_md5_error(resolver):
    """Error HTTP obteniendo pass_md5 → None."""
    mock_page = MagicMock()
    mock_page.url = "https://playmogo.com/e/abc123"
    mock_page.text = PLAYMOGO_HTML

    resolver._client.get = AsyncMock(
        side_effect=[mock_page, httpx.HTTPError("Pass MD5 failed")]
    )

    result = await resolver.resolve_doodstream("https://doodstream.com/e/abc123")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_doodstream_invalid_pass_md5_response(resolver):
    """pass_md5 no devuelve URL válida → None."""
    mock_page = MagicMock()
    mock_page.url = "https://playmogo.com/e/abc123"
    mock_page.text = PLAYMOGO_HTML

    mock_pass = MagicMock()
    mock_pass.text = "not-a-url"

    resolver._client.get = AsyncMock(side_effect=[mock_page, mock_pass])

    result = await resolver.resolve_doodstream("https://doodstream.com/e/abc123")
    assert result is None


def test_is_doodstream_true():
    assert VideoResolver.is_doodstream("https://doodstream.com/e/abc123") is True
    assert VideoResolver.is_doodstream("https://playmogo.com/e/abc123") is True
    assert VideoResolver.is_doodstream("https://dood.la/e/abc123") is True
    assert VideoResolver.is_doodstream("https://d000d.com/e/abc123") is True


def test_is_doodstream_false():
    assert VideoResolver.is_doodstream("https://voe.sx/e/abc123") is False
    assert VideoResolver.is_doodstream("https://vidhide.com/e/abc123") is False
    assert VideoResolver.is_doodstream("https://example.com/video.mp4") is False
```

### Paso 4: Tests de integración para Cuevana3Adapter con video directo

Agregar a `tests/test_cuevana3.py` estos tests adicionales:

```python
# Tests de resolución de video directo (integrados en Cuevana3Adapter)

PLAYMOGO_EMBED_HTML = """
<!DOCTYPE html>
<html>
<body>
    <ul>
        <li>
            <div data-mdl="https://doodstream.com/e/jtri5tfbukk6">
                <img src="/flags/es.svg" alt="Español" />
            </div>
        </li>
    </ul>
</body>
</html>
"""


@pytest.mark.asyncio
async def test_resolve_playback_direct_video_doodstream(adapter):
    """Cuando el servidor es Doodstream, intenta resolver video directo."""
    # Mock del VideoResolver
    mock_descriptor = PlaybackDescriptor(
        protocol="mp4",
        url="https://cdn.example.com/video.mp4?token=abc&expiry=123",
        headers={"Referer": "https://playmogo.com"},
    )

    with patch("src.adapters.cuevana3.VideoResolver") as MockResolver:
        mock_instance = AsyncMock()
        mock_instance.resolve_doodstream = AsyncMock(return_value=mock_descriptor)
        MockResolver.return_value = mock_instance
        MockResolver.is_doodstream = staticmethod(lambda url: "doodstream" in url.lower())

        adapter._client.get.return_value = MockResponse(PLAYMOGO_EMBED_HTML)
        # Inicializar video_resolver mockeado
        adapter._video_resolver = mock_instance

        result = await adapter.resolve_playback("cuevana3:pelicula-prueba-2026")

        assert result.protocol == "mp4"
        assert "cdn.example.com" in result.url


@pytest.mark.asyncio
async def test_resolve_playback_fallback_to_embed_when_direct_fails(adapter):
    """Si la resolución directa falla, fallback a embed."""
    with patch("src.adapters.cuevana3.VideoResolver") as MockResolver:
        mock_instance = AsyncMock()
        mock_instance.resolve_doodstream = AsyncMock(return_value=None)
        MockResolver.return_value = mock_instance
        MockResolver.is_doodstream = staticmethod(lambda url: "doodstream" in url.lower())

        adapter._client.get.return_value = MockResponse(PLAYBACK_HTML)
        adapter._video_resolver = mock_instance

        result = await adapter.resolve_playback("cuevana3:pelicula-prueba-2026")

        assert result.protocol == "embed"
        assert "doodstream.com" in result.url
```

## ACEPTACION

```
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/test_video_resolver.py -v
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/test_cuevana3.py -v
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v --tb=short
```

## PREMISES

- `src/adapters/cuevana3.py` tiene `resolve_playback()` que retorna `PlaybackDescriptor(protocol="embed", url=...)` en 4 puntos
- `src/adapters/cuevana3.py` tiene `close()` que llama `await self._client.aclose()`
- `src/models/catalog.py` define `PlaybackDescriptor` con campos: protocol, url, headers, expires_at, subtitles
- `src/services/flaresolverr.py` existe como referencia de estructura de servicio
- `tests/test_cuevana3.py` usa `MockResponse`, `adapter` fixture con `AsyncMock` para `_client`
- `tests/test_cuevana3.py` tiene `PLAYBACK_HTML` con `data-mdl="https://doodstream.com/e/abc123"`
- `.fabrica-verify` ejecuta `pytest tests/ -v`
- El venv está en `.venv/` y se activa con `. .venv/bin/activate`
