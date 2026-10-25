---
name: add-hls-proxy-streaming
description: Replicar la solución de streaming HLS del IPTV en el gateway — proxy directo por chunks con byte-range y reintentos, en lugar de 302 redirect.
---

# Agregar proxy HLS al gateway (replicar solución del IPTV)

## Contexto
El IPTV en `/opt/iptv-proxy/gateway/gateway.py` resuelve el buffering de HLS con dos mecanismos:

1. **`direct_provider_media`** (línea 470): proxy directo que lee chunks de 256KB del upstream y los escribe al cliente, soporta byte-range headers, reintentos con backoff.
2. **`remux_stream`** (línea 910): ffmpeg convierte HLS → MPEG-TS con flags `-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 2`.

El gateway actual en `src/api/xtream.py` (endpoint `stream_movie`) devuelve 302 redirect a la URL del CDN. Cuando el CDN entrega HLS (.m3u8), el cliente IPTV se congela porque no puede hacer byte-range seeks.

## Qué hacer

### 1. Crear `src/services/stream_proxy.py`

Módulo con dos funciones:

```python
async def proxy_stream(
    url: str,
    request_headers: dict,
    referer: str = "",
) -> StreamingResponse:
    """
    Proxy directo: abre conexión al upstream, lee chunks de 256KB
    y los escribe al cliente. Soporta byte-range (Range header).
    Replica direct_provider_media del IPTV.
    """
```

Lógica:
- Leer header `Range` del request y forward al upstream
- Abrir sesión aiohttp con `allow_redirects=True`
- Leer chunk inicial para inspección (como hace el IPTV con `body_sample`)
- Si es HLS (.m3u8), usar `remux_hls_to_ts` (paso 2)
- Si es MP4 directo, hacer proxy por chunks de 256KB
- Headers de respuesta: copiar del upstream menos hop headers
- Reintentos: 2 intentos con backoff si el upstream falla (429, 502, 503)

```python
async def remux_hls_to_ts(
    hls_url: str,
    referer: str = "",
) -> StreamingResponse:
    """
    ffmpeg convierte HLS → MPEG-TS pipe.
    Replica remux_stream del IPTV.
    """
```

Lógica:
- Lanzar subprocess ffmpeg con:
  ```
  ffmpeg -hide_banner -loglevel warning
    -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 2
    -rw_timeout 15000000
    -analyzeduration 3000000 -probesize 3000000
    -i <hls_url>
    -map 0:v? -map 0:a? -map 0:s?
    -c copy -max_interleave_delta 0 -muxdelay 0 -muxpreload 0
    -f mpegts pipe:1
  ```
- Headers: `Referer` si aplica
- Leer stdout de ffmpeg en chunks de 256KB y escribir al cliente
- Content-Type: `video/mp2t`
- Al desconectar cliente: terminar ffmpeg con `process.terminate()` + `process.kill()` tras 3s timeout

### 2. Modificar `src/api/xtream.py` — endpoint `stream_movie`

Cambiar la lógica actual (que devuelve `RedirectResponse`) para:

```python
@app.get("/movie/{username}/{password}/{vod_id}.mp4")
async def stream_movie(...):
    # ... resolver URL como antes ...
    resolved_url = await resolve_url(...)
    
    if not resolved_url:
        raise HTTPException(502, "No se pudo resolver")
    
    # Si es HLS (.m3u8), usar remux
    if resolved_url.endswith('.m3u8') or 'm3u8' in resolved_url:
        return await remux_hls_to_ts(
            resolved_url,
            referer=extract_referer(resolved_url)
        )
    
    # Si es MP4 directo, usar proxy directo
    return await proxy_stream(
        resolved_url,
        request_headers=request.headers,
        referer=extract_referer(resolved_url)
    )
```

### 3. Agregar endpoint `/stream/{media_type}/{vod_id}.ts`

Nuevo endpoint para streams HLS explícitos:

```python
@app.get("/stream/{media_type}/{vod_id}.ts")
async def stream_hls(media_type: str, vod_id: str, ...):
    """Endpoint dedicado para remux HLS → MPEG-TS"""
```

### 4. NO tocar
- `src/services/mediaflow_bridge.py` — los resolvers quedan igual
- `src/adapters/` — no cambiar
- Tests existentes — no romper

## ACEPTACION
cd /app && python3 -m pytest tests/ -x -q
cd /app && python3 -m py_compile src/services/stream_proxy.py
cd /app && python3 -c "from src.services.stream_proxy import proxy_stream, remux_hls_to_ts; print('OK')"

## PREMISES
- src/api/xtream.py tiene endpoint stream_movie en línea ~409 que devuelve RedirectResponse
- src/services/mediaflow_bridge.py tiene _EXTRACTOR_MAP con los 4 resolvers nuevos
- El IPTV usa aiohttp.ClientSession para proxy directo (gateway.py línea 470)
- El IPTV usa ffmpeg subprocess para remux (gateway.py línea 910)
- FastAPI ya usa StreamingResponse en otros endpoints
- El contenedor tiene ffmpeg disponible (verificar en Dockerfile)
