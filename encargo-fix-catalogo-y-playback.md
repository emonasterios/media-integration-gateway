# Fix: deduplicar catálogo + usar proxy de video

## Problema
1. **Catálogo duplicado**: `get_vod_streams` devuelve 1540 entradas pero solo 1207 únicas. 35 títulos aparecen múltiples veces (ej: "Castigo divino" 41 veces). El IPTV no actualiza el catálogo por esto.
2. **No reproduce**: `stream_movie()` hace `RedirectResponse(302)` directo al CDN (`cloudatacdn.com`), pero el CDN requiere header `Referer: https://cuevana3.li`. El cliente IPTV no envía Referer → el CDN rechaza.

## Qué hacer

### 1. Deduplicar catálogo en `src/api/xtream.py`

En la función `player_api()`, donde se construye `movies` (línea ~125), deduplicar por `provider_id`:

```python
# ANTES (línea ~125):
movies = [item for item in catalog + catalog2 if item.media_type == MediaType.MOVIE]

# DESPUÉS:
seen_ids: set[str] = set()
movies: list[MediaItem] = []
for item in catalog + catalog2:
    if item.media_type == MediaType.MOVIE and item.provider_id not in seen_ids:
        seen_ids.add(item.provider_id)
        movies.append(item)
```

Aplicar la misma deduplicación en:
- `get_vod_info` (línea ~137, donde se usa `catalog + catalog2`)
- `search_vod` (línea ~192)
- `get_series` (línea ~160, deduplicar por `provider_id`)
- `get_series_info` (línea ~178)
- `get_vod_categories` → no necesita cambio

### 2. Usar proxy de video en lugar de redirect 302

En `stream_movie()` (línea 263-312), cuando `result.protocol` es `"mp4"`, en vez de `RedirectResponse`, usar `_proxy_stream` que ya existe (línea 315) pero nunca se invoca.

Reemplazar el bloque de línea 307-309:
```python
# ANTES:
if result.protocol in ("hls", "mp4"):
    logger.info("Redirecting to direct %s URL: %s", result.protocol, result.url[:80])
    return RedirectResponse(url=result.url, status_code=302)
```

Por:
```python
# DESPUÉS:
if result.protocol == "mp4":
    proxy_headers = {
        "Referer": "https://cuevana3.li",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    # Añadir Range si el cliente lo envió
    range_header = request.headers.get("range")
    if range_header:
        proxy_headers["Range"] = range_header
    
    logger.info("Proxying mp4 URL: %s", result.url[:80])
    return StreamingResponse(
        _proxy_stream(result.url, proxy_headers),
        status_code=206 if range_header else 200,
        media_type="video/mp4",
        headers={"Accept-Ranges": "bytes"},
    )

if result.protocol == "hls":
    logger.info("Redirecting to HLS URL: %s", result.url[:80])
    return RedirectResponse(url=result.url, status_code=302)
```

Asegurar que los imports necesarios están arriba del archivo:
```python
from fastapi.responses import RedirectResponse, StreamingResponse
```

### 3. Verificar que `_proxy_stream` funciona

La función `_proxy_stream` (línea 315) ya existe. Verificar que:
- Usa `httpx.AsyncClient.stream()` correctamente
- Forwardea los headers de respuesta `Content-Range`, `Content-Length`
- El generador cede chunks del video

Si necesita ajuste, corregirlo para que soporte byte-range requests correctamente.

## NO tocar
- No cambiar la lógica de scraping de `cuevana3.py`
- No cambiar `video_resolver.py` ni `mediaflow_bridge.py`
- No cambiar tests existentes
- No cambiar `resolve_playback` en `catalog.py`

## ACEPTACION
```
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v
cd /home/emon/media-integration-gateway && . .venv/bin/activate && python scripts/accept_cuevana3.py
```

## PREMISES
- `src/api/xtream.py` línea 125: `movies = [item for item in catalog + catalog2 if item.media_type == MediaType.MOVIE]` — sin deduplicar
- `src/api/xtream.py` línea 307-309: `return RedirectResponse(url=result.url, status_code=302)` — redirect directo al CDN sin Referer
- `src/api/xtream.py` línea 315: `async def _proxy_stream(url: str, headers: dict)` — existe pero nunca se usa
- `src/api/xtream.py` línea 259-312: `stream_movie()` resuelve playback pero siempre termina en RedirectResponse
- CDN `cloudatacdn.com` requiere `Referer: https://cuevana3.li` (verificado con curl)
- 35 títulos duplicados en catálogo: "Castigo divino" aparece 41 veces, "Signal One" 4 veces
