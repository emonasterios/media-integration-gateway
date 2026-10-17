# Encargo: Integrar mediaflow-proxy como motor de resolución de video

## Contexto
El `video_resolver.py` actual usa `httpx.AsyncClient` directo para resolver Doodstream y Voe.sx, pero Cloudflare bloquea las peticiones (403 challenge). FlareSolverr tampoco funciona bien para estos hosts.

**mediaflow-proxy** (`pip install mediaflow-proxy`) ya resuelve esto: usa `curl-cffi` con fingerprint TLS Chrome para bypass de Cloudflare, con fallback a Byparr. Tiene extractores para Doodstream, Voe, StreamWish, FileMoon, etc.

## Qué hacer

### 1. Agregar dependencia
En `pyproject.toml`, agregar `mediaflow-proxy` a las dependencies.

### 2. Crear `src/services/mediaflow_bridge.py`
Nuevo módulo que envuelve los extractores de mediaflow-proxy y traduce su salida a `PlaybackDescriptor`.

```python
"""Puente entre mediaflow-proxy extractors y PlaybackDescriptor del gateway."""

from __future__ import annotations

import logging
from typing import Optional

from mediaflow_proxy.extractors.doodstream import DoodStreamExtractor
from mediaflow_proxy.extractors.voe import VoeExtractor
from mediaflow_proxy.extractors.base import ExtractorError

from src.models.catalog import PlaybackDescriptor

logger = logging.getLogger(__name__)

# Mapeo de dominio → clase extractor
_EXTRACTOR_MAP = {
    "doodstream.com": DoodStreamExtractor,
    "dood.la": DoodStreamExtractor,
    "dood.ws": DoodStreamExtractor,
    "playmogo.com": DoodStreamExtractor,
    "d000d.com": DoodStreamExtractor,
    "dood.yt": DoodStreamExtractor,
    "dooood.com": DoodStreamExtractor,
    "voe.sx": VoeExtractor,
    "voe-unblock.com": VoeExtractor,
    "voeunblock.com": VoeExtractor,
    "voeunbl0ck.com": VoeExtractor,
    "voeunblocker.com": VoeExtractor,
}


async def resolve_with_mediaflow(embed_url: str, domain: str) -> Optional[PlaybackDescriptor]:
    """Resolver una URL de embed usando el extractor de mediaflow-proxy correspondiente.
    
    Returns PlaybackDescriptor con protocol='mp4' (o 'hls' para Voe) y headers necesarios.
    """
    extractor_cls = _EXTRACTOR_MAP.get(domain)
    if not extractor_cls:
        logger.warning("No hay extractor mediaflow para dominio %s", domain)
        return None
    
    request_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": embed_url,
    }
    
    try:
        extractor = extractor_cls(request_headers=request_headers)
        result = await extractor.extract(embed_url)
    except ExtractorError as e:
        logger.warning("mediaflow extractor falló para %s: %s", embed_url, e)
        return None
    
    dest_url = result.get("destination_url")
    if not dest_url:
        logger.warning("Extractor no devolvió destination_url para %s", embed_url)
        return None
    
    req_headers = result.get("request_headers", {})
    endpoint = result.get("mediaflow_endpoint", "")
    
    # Doodstream devuelve mp4 directo; Voe devuelve HLS
    protocol = "hls" if "hls" in endpoint.lower() else "mp4"
    
    return PlaybackDescriptor(
        protocol=protocol,
        url=dest_url,
        headers=req_headers,
    )
```

### 3. Modificar `src/services/video_resolver.py`
En los métodos `resolve_doodstream` y `resolve_voe`, intentar primero con mediaflow_bridge antes del fallback actual.

En `resolve_doodstream` (línea ~132), al inicio del método:
```python
# Intentar con mediaflow-proxy primero
from src.services.mediaflow_bridge import resolve_with_mediaflow
result = await resolve_with_mediaflow(embed_url, "doodstream.com")
if result:
    return result
# ... mantener el código existente como fallback
```

En `resolve_voe` (línea ~206), al inicio del método:
```python
from src.services.mediaflow_bridge import resolve_with_mediaflow
result = await resolve_with_mediaflow(embed_url, "voe.sx")
if result:
    return result
# ... mantener el código existente como fallback
```

### 4. NO tocar
- `src/adapters/cuevana3.py` ni `src/adapters/cuevan_net.py` (llaman al resolver, no al extractor)
- Los tests existentes (siguen mockeando `_validate_video_url`)
- `resolve_streamtape` ni `resolve_morencius` (por ahora)
- La interfaz pública de `VideoResolver` (los adapters no deben cambiar)

## ACEPTACION
```
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v -x
```
```
cd /home/emon/media-integration-gateway && . .venv/bin/activate && python scripts/accept_cuevana3.py
```

## PREMISES
- src/services/video_resolver.py:132 — `resolve_doodstream` empieza con httpx directo, bloqueado por Cloudflare
- src/services/video_resolver.py:206 — `resolve_voe` usa FlareSolverr que devuelve "New Tab"
- src/models/catalog.py — `PlaybackDescriptor` tiene campos: protocol, url, headers
- mediaflow-proxy está en PyPI, se instala con `pip install mediaflow-proxy`
- Los extractores de mediaflow devuelven dict con keys: destination_url, request_headers, mediaflow_endpoint
- DoodStreamExtractor.extract() usa curl-cffi con impersonate="chrome" para bypass Cloudflare
- VoeExtractor.extract() decodifica payload ofuscado y devuelve HLS manifest
