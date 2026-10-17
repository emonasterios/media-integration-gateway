<!-- spec:8d18e22028a8a29a1d799e14845ae1a2 -->
# REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- Cada paso debe dejar el proyecto COMPILANDO.

---

## PASO 1: Agregar dependencia mediaflow-proxy en pyproject.toml

Archivo a tocar: `pyproject.toml`

Instrucciones:
1. Leer `pyproject.toml`.
2. Localizar la lista `dependencies = [ ... ]`.
3. Agregar `"mediaflow-proxy"` a la lista de dependencias sin eliminar ni alterar ninguna de las dependencias ya existentes.
4. Guardar los cambios.

Lo que debe quedar:
`pyproject.toml` debe contener `"mediaflow-proxy"` dentro del arreglo de dependencias del proyecto.

---

## PASO 2: Crear el adaptador src/services/mediaflow_bridge.py

Archivo a tocar: `src/services/mediaflow_bridge.py`

Instrucciones:
1. Crear el archivo `src/services/mediaflow_bridge.py` nuevo.
2. Escribir la implementación del puente que envuelve los extractores de `mediaflow-proxy` y retorna `PlaybackDescriptor`.

El archivo completo debe quedar exactamente así:
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

# Mapeo de dominio -> clase extractor
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

Lo que debe quedar:
`src/services/mediaflow_bridge.py` creado y con sintaxis válida (`python3 -m py_compile src/services/mediaflow_bridge.py`).

---

## PASO 3: Conectar mediaflow_bridge en resolve_doodstream y resolve_voe

Archivo a tocar: `src/services/video_resolver.py`

Instrucciones:
1. Leer `src/services/video_resolver.py` antes de editarlo.
2. Localizar el método `resolve_doodstream(self, embed_url: str) -> Optional[PlaybackDescriptor]:` (alrededor de la línea 132).
   Al inicio del cuerpo del método, antes del bloque `async with httpx.AsyncClient...`, agregar:
```python
        # Intentar con mediaflow-proxy primero
        from src.services.mediaflow_bridge import resolve_with_mediaflow
        result = await resolve_with_mediaflow(embed_url, "doodstream.com")
        if result:
            return result
```
   Mantener todo el código existente posterior de `resolve_doodstream` intacto como fallback.
3. Localizar el método `resolve_voe(self, embed_url: str) -> Optional[PlaybackDescriptor]:` (alrededor de la línea 206).
   Al inicio del cuerpo del método, antes del bloque existente de resolución/flaresolverr, agregar:
```python
        # Intentar con mediaflow-proxy primero
        from src.services.mediaflow_bridge import resolve_with_mediaflow
        result = await resolve_with_mediaflow(embed_url, "voe.sx")
        if result:
            return result
```
   Mantener todo el código existente posterior de `resolve_voe` intacto como fallback.
4. NO tocar `resolve_streamtape`, `resolve_morencius`, `_validate_video_url` ni la interfaz pública de `VideoResolver`.
5. Guardar los cambios.

Lo que debe quedar:
`src/services/video_resolver.py` intentando primero `resolve_with_mediaflow` en `resolve_doodstream` y `resolve_voe`, conservando los fallbacks originales y compilando limpiamente (`python3 -m py_compile src/services/video_resolver.py`).

---

ACEPTACION
grep -q "mediaflow-proxy" pyproject.toml
test -f src/services/mediaflow_bridge.py
grep -q "from mediaflow_proxy.extractors.doodstream import DoodStreamExtractor" src/services/mediaflow_bridge.py
grep -q "from mediaflow_proxy.extractors.voe import VoeExtractor" src/services/mediaflow_bridge.py
grep -q "async def resolve_with_mediaflow" src/services/mediaflow_bridge.py
grep -q "from src.services.mediaflow_bridge import resolve_with_mediaflow" src/services/video_resolver.py
grep -q 'resolve_with_mediaflow(embed_url, "doodstream.com")' src/services/video_resolver.py
grep -q 'resolve_with_mediaflow(embed_url, "voe.sx")' src/services/video_resolver.py
python3 -m py_compile src/services/mediaflow_bridge.py
python3 -m py_compile src/services/video_resolver.py

PREMISES
- src/services/video_resolver.py:132 — `resolve_doodstream` empieza con httpx directo, bloqueado por Cloudflare
- src/services/video_resolver.py:206 — `resolve_voe` usa FlareSolverr que devuelve "New Tab"
- src/models/catalog.py — `PlaybackDescriptor` tiene campos: protocol, url, headers
- mediaflow-proxy está en PyPI, se instala con `pip install mediaflow-proxy`
- Los extractores de mediaflow devuelven dict con keys: destination_url, request_headers, mediaflow_endpoint
- DoodStreamExtractor.extract() usa curl-cffi con impersonate="chrome" para bypass Cloudflare
- VoeExtractor.extract() decodifica payload ofuscado y devuelve HLS manifest
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
