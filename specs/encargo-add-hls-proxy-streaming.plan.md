<!-- spec:6056f92c3750ecf0b565bf0e55aa776a -->
# ENCARGO: Implementación de Proxy Streaming HLS y Remux MPEG-TS en Gateway

## REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- Cada paso debe dejar el proyecto COMPILANDO (`python3 -m py_compile`).

---

## AVISO DE FALLOS DE FONDO (CRÍTICOS PARA EJECUCIÓN)
1. **Cierre prematuro de conexión `aiohttp` en `StreamingResponse`:** En respuestas en streaming, el generador asíncrono debe mantener abierta la sesión `aiohttp.ClientSession` y la respuesta HTTP mientras cede los chunks (`yield chunk`). Si la sesión se abre con un context manager en la función principal y se cierra antes de que el cliente termine de consumir el generador, la descarga explotará con `ClientPayloadError` o `Session is closed`. La sesión y respuesta deben cerrarse únicamente en el bloque `finally:` dentro del generador asíncrono.
2. **Propagación ciega de encabezados hop-by-hop:** No reenviar headers como `transfer-encoding`, `connection`, `content-encoding` o `content-length` directamente desde el upstream si no coinciden con la respuesta en streaming de Starlette/FastAPI, ya que rompen el protocolo HTTP y desincronizan Uvicorn.
3. **Parámetro `Request` en FastAPI:** Modificar el endpoint `stream_movie` requiere explícitamente agregar `request: Request` a la firma del endpoint para acceder a los encabezados entrantes (`Range`), de lo contrario ocurrirá un `NameError` en tiempo de ejecución.
4. **Sintaxis de `-headers` en FFmpeg:** El flag `-headers` de FFmpeg exige que los encabezados terminen estrictamente en `\r\n`. Si la variable `referer` está vacía, no se debe agregar la opción `-headers` vacía porque FFmpeg abortará con error de sintaxis.

---

## PASO 1: Crear módulo `src/services/stream_proxy.py`

### Archivo a crear:
- `src/services/stream_proxy.py`

### Qué debe quedar:
Crear el archivo `src/services/stream_proxy.py` implementando dos funciones asíncronas principales:

1. `async def proxy_stream(url: str, request_headers: dict, referer: str = "") -> StreamingResponse`:
   - Constante `CHUNK_SIZE = 256 * 1024` (256 KB).
   - Lista de headers excluidos (hop-by-hop): `{"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade"}`.
   - Si `url` contiene `.m3u8` o el `Content-Type` upstream indica HLS (`application/vnd.apple.mpegurl`, `application/x-mpegurl`), derivar directamente a `await remux_hls_to_ts(url, referer=referer)`.
   - Reenviar el encabezado `Range` si viene en `request_headers`. Si se proporciona `referer`, agregar el header `Referer`.
   - Reintentos: manejar hasta 2 reintentos con backoff (1s, 2s) si el upstream responde con códigos `429`, `502` o `503`.
   - Generador asíncrono `content_streamer(session, response)`:
     - Itera chunks con `async for chunk in response.content.iter_chunked(CHUNK_SIZE): yield chunk`.
     - En bloque `finally:`, cerrar explícitamente `response.close()` y `await session.close()`.
   - Preparar los headers limpios de respuesta: pasar `Content-Type`, `Accept-Ranges`, `Content-Range`, `Content-Length` si existen en la respuesta del upstream.
   - Retornar `StreamingResponse(content_streamer(session, resp), status_code=resp.status, headers=response_headers)`.

2. `async def remux_hls_to_ts(hls_url: str, referer: str = "") -> StreamingResponse`:
   - Construir los argumentos para FFmpeg en una lista:
     `ffmpeg -hide_banner -loglevel warning -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 2 -rw_timeout 15000000 -analyzeduration 3000000 -probesize 3000000`
   - Si `referer` no está vacío, agregar `-headers` y `f"Referer: {referer}\r\n"`.
   - Seguido de:
     `-i <hls_url> -map 0:v? -map 0:a? -map 0:s? -c copy -max_interleave_delta 0 -muxdelay 0 -muxpreload 0 -f mpegts pipe:1`
   - Iniciar el subproceso con `await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)`.
   - Generador asíncrono que lee `process.stdout.read(CHUNK_SIZE)` en bucle mientras haya datos y los ceda con `yield`.
   - En el bloque `finally:` del generador, asegurar la terminación de FFmpeg:
     Si `process.returncode is None`: invocar `process.terminate()`, esperar con `asyncio.wait_for(process.wait(), timeout=3.0)` y si expira capturar `asyncio.TimeoutError` y llamar a `process.kill()`.
   - Retornar `StreamingResponse(ffmpeg_streamer(), media_type="video/mp2t")`.

---

## PASO 2: Integrar el proxy en `src/api/xtream.py` y añadir endpoint de stream TS

### Archivos a tocar:
- `src/api/xtream.py`

### Qué debe quedar:
1. Leer `src/api/xtream.py` antes de editarlo.
2. Importar `Request` desde `fastapi`.
3. Importar `proxy_stream` y `remux_hls_to_ts` desde `src.services.stream_proxy`.
4. En el endpoint `stream_movie` (ruta `@router.get("/movie/{username}/{password}/{vod_id}.mp4")` o equivalente):
   - Añadir el parámetro `request: Request` a la función si no está presente.
   - Tras resolver la URL (`resolved_url`):
     - Determinar el `referer` a partir de la URL o cabeceras entrantes.
     - Si `resolved_url.endswith('.m3u8')` o `'m3u8' in resolved_url`:
       retornar `await remux_hls_to_ts(resolved_url, referer=referer)`.
     - Para URLs directas (como MP4), retornar `await proxy_stream(resolved_url, request_headers=dict(request.headers), referer=referer)`.
     - Eliminar el retorno con `RedirectResponse(url=resolved_url, status_code=302)`.
5. Agregar el nuevo endpoint para reproducción HLS / TS explícita:
   ```python
   @router.get("/stream/{media_type}/{vod_id}.ts")
   async def stream_hls(
       media_type: str,
       vod_id: str,
       request: Request,
   ):
       # Resolver la URL del stream para vod_id y media_type
       # Si no resuelve, lanzar HTTPException(status_code=502, detail="No se pudo resolver el stream")
       # Invocar y retornar await remux_hls_to_ts(resolved_url, referer=referer)
   ```

---

## PASO 3: Pruebas unitarias para `stream_proxy` y endpoints Xtream

### Archivos a tocar:
- `tests/test_stream_proxy.py` (crear)

### Qué debe quedar:
Crear `tests/test_stream_proxy.py` con pruebas usando `pytest` y `unittest.mock`:
1. `test_proxy_stream_mp4`: simula una respuesta upstream de aiohttp con chunks de bytes y verifica que `proxy_stream` devuelve un `StreamingResponse` con status code 200/206 y propaga el `Range` header.
2. `test_proxy_stream_delegates_m3u8`: verifica que si `url` contiene `.m3u8`, `proxy_stream` delega automáticamente en `remux_hls_to_ts`.
3. `test_remux_hls_to_ts_process_lifecycle`: simula `asyncio.create_subprocess_exec`, verifica que el generador lee datos de `stdout`, y comprueba que en el cierre o desconexión se ejecutan `process.terminate()` y la limpieza.
4. `test_xtream_stream_movie_uses_proxy`: prueba el endpoint `stream_movie` de `src/api/xtream.py` asegurando que ya no devuelve un redirect 302 sino una respuesta en streaming.

Verificar que todas las pruebas pasen ejecutando:
`pytest tests/test_stream_proxy.py tests/test_xtream.py`

---

ACEPTACION
test -f src/services/stream_proxy.py
grep -q "async def proxy_stream" src/services/stream_proxy.py
grep -q "async def remux_hls_to_ts" src/services/stream_proxy.py
grep -q "reconnect_streamed" src/services/stream_proxy.py
grep -q "from src.services.stream_proxy import" src/api/xtream.py
grep -q "remux_hls_to_ts" src/api/xtream.py
grep -q "proxy_stream" src/api/xtream.py
grep -q "/stream/{media_type}/{vod_id}.ts" src/api/xtream.py
test -f tests/test_stream_proxy.py
python3 -m py_compile src/services/stream_proxy.py
python3 -m py_compile src/api/xtream.py
python3 -c "from src.services.stream_proxy import proxy_stream, remux_hls_to_ts; print('OK')"
pytest tests/test_stream_proxy.py tests/test_xtream.py -q

PREMISES
- src/api/xtream.py tiene endpoint stream_movie en línea ~409 que devuelve RedirectResponse
- src/services/mediaflow_bridge.py tiene _EXTRACTOR_MAP con los 4 resolvers nuevos
- El IPTV usa aiohttp.ClientSession para proxy directo (gateway.py línea 470)
- El IPTV usa ffmpeg subprocess para remux (gateway.py línea 910)
- FastAPI ya usa StreamingResponse en otros endpoints
- El contenedor tiene ffmpeg disponible (verificar en Dockerfile)
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
