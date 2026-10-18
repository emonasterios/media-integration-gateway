<!-- spec:2d1d1a06cff44984d4c36d08561f5ac9 -->
# REGLAS OBLIGATORIAS DE EJECUCIÓN
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

---

## PASO 1: FALLO DE FONDO EN REPRODUCCIÓN - Proxy de video MP4 y soporte de Referer en `src/api/xtream.py`

### Diagnóstico de fallo en ejecución
Aunque el código compile, `stream_movie()` actualmente responde con `RedirectResponse(302)` directo a la URL del CDN (`cloudatacdn.com`). Este CDN bloquea cualquier petición que no incluya el encabezado `Referer: https://cuevana3.li`. Como los reproductores IPTV no envían este encabezado en redirecciones, la reproducción revienta inmediatamente en tiempo de ejecución. Además, el endpoint no importa `StreamingResponse`, por lo que usar streaming sin importarlo causa un `NameError`.

### Archivo a modificar
- `src/api/xtream.py`

### Instrucciones concretas
1. Leer `src/api/xtream.py`.
2. En la sección de imports superiores, asegurar la importación de `StreamingResponse` junto a `RedirectResponse` desde `fastapi.responses`:
   ```python
   from fastapi.responses import RedirectResponse, StreamingResponse
   ```
3. En la función `_proxy_stream(url: str, headers: dict)` (alrededor de la línea 315), verificar que realiza la petición por streaming con `httpx.AsyncClient` reenviando los encabezados, siguiendo redirecciones y cediendo los chunks:
   ```python
   async def _proxy_stream(url: str, headers: dict):
       async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
           async with client.stream("GET", url, headers=headers) as response:
               async for chunk in response.aiter_bytes(chunk_size=65536):
                   yield chunk
   ```
4. En `stream_movie()` (alrededor de la línea 305-312), reemplazar el bloque condicional donde `result.protocol in ("hls", "mp4")` por la lógica diferenciada para `mp4` y `hls`:
   ```python
       if result.protocol == "mp4":
           proxy_headers = {
               "Referer": "https://cuevana3.li",
               "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
           }
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
5. Comprobar que compila sin errores ejecutando: `python3 -m py_compile src/api/xtream.py`.

---

## PASO 2: Deduplicación del catálogo por `provider_id` en `src/api/xtream.py`

### Diagnóstico de fallo en ejecución
El catálogo concatenado `catalog + catalog2` contiene elementos duplicados (1540 elementos para solo 1207 únicos). Ciertos reproductores IPTV rechazan o abortan la sincronización de listas al detectar múltiples entradas con el mismo identificador.

### Archivo a modificar
- `src/api/xtream.py`

### Instrucciones concretas
1. Leer `src/api/xtream.py`.
2. En la función `player_api()`, en el bloque de `action == "get_vod_streams"` (alrededor de la línea 125):
   Reemplazar:
   ```python
   movies = [item for item in catalog + catalog2 if item.media_type == MediaType.MOVIE]
   ```
   Por:
   ```python
   seen_ids: set[str] = set()
   movies: list[MediaItem] = []
   for item in catalog + catalog2:
       if item.media_type == MediaType.MOVIE and item.provider_id not in seen_ids:
           seen_ids.add(item.provider_id)
           movies.append(item)
   ```
3. En `player_api()`, en el bloque de `action == "get_vod_info"` (alrededor de la línea 137):
   Deduplicar la lista combinada antes de buscar el `vod_id`:
   ```python
   seen_vod_info_ids: set[str] = set()
   dedup_catalog: list[MediaItem] = []
   for item in catalog + catalog2:
       if item.provider_id not in seen_vod_info_ids:
           seen_vod_info_ids.add(item.provider_id)
           dedup_catalog.append(item)
   ```
   Y utilizar `dedup_catalog` para localizar el elemento solicitado.
4. En `player_api()`, en el bloque de `action == "get_series"` (alrededor de la línea 160):
   Deduplicar por `provider_id` para series:
   ```python
   seen_series_ids: set[str] = set()
   series: list[MediaItem] = []
   for item in catalog + catalog2:
       if item.media_type == MediaType.SERIES and item.provider_id not in seen_series_ids:
           seen_series_ids.add(item.provider_id)
           series.append(item)
   ```
5. En `player_api()`, en el bloque de `action == "get_series_info"` (alrededor de la línea 178):
   Deduplicar la lista combinada antes de buscar el `series_id`:
   ```python
   seen_sinfo_ids: set[str] = set()
   dedup_series_catalog: list[MediaItem] = []
   for item in catalog + catalog2:
       if item.provider_id not in seen_sinfo_ids:
           seen_sinfo_ids.add(item.provider_id)
           dedup_series_catalog.append(item)
   ```
   Y utilizar `dedup_series_catalog` para localizar la serie.
6. En `player_api()`, en el bloque de `action == "search_vod"` (alrededor de la línea 192):
   Deduplicar las películas por `provider_id`:
   ```python
   seen_search_ids: set[str] = set()
   movies: list[MediaItem] = []
   for item in catalog + catalog2:
       if item.media_type == MediaType.MOVIE and item.provider_id not in seen_search_ids:
           seen_search_ids.add(item.provider_id)
           movies.append(item)
   ```
7. Mantener intacto el bloque de `get_vod_categories`.
8. Comprobar que compila sin errores ejecutando: `python3 -m py_compile src/api/xtream.py`.

---

ACEPTACION
python3 -m py_compile src/api/xtream.py
grep -q "from fastapi.responses import.*StreamingResponse" src/api/xtream.py
grep -q "seen_ids: set\[str\] = set()" src/api/xtream.py
grep -q "item.provider_id not in seen_ids" src/api/xtream.py
grep -q "https://cuevana3.li" src/api/xtream.py
grep -q "_proxy_stream(result.url, proxy_headers)" src/api/xtream.py
grep -q "status_code=206 if range_header else 200" src/api/xtream.py
grep -q 'headers={"Accept-Ranges": "bytes"}' src/api/xtream.py

PREMISES
- `src/api/xtream.py` línea 125: `movies = [item for item in catalog + catalog2 if item.media_type == MediaType.MOVIE]` — sin deduplicar
- `src/api/xtream.py` línea 307-309: `return RedirectResponse(url=result.url, status_code=302)` — redirect directo al CDN sin Referer
- `src/api/xtream.py` línea 315: `async def _proxy_stream(url: str, headers: dict)` — existe pero nunca se usa
- `src/api/xtream.py` línea 259-312: `stream_movie()` resuelve playback pero siempre termina en RedirectResponse
- CDN `cloudatacdn.com` requiere `Referer: https://cuevana3.li` (verificado con curl)
- 35 títulos duplicados en catálogo: "Castigo divino" aparece 41 veces, "Signal One" 4 veces
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
