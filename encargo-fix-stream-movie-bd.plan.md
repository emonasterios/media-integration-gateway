<!-- spec:0dd9a105a9d6f69cb0bd95ba1d6e4c12 -->
# ENCARGO: Fix stream_movie para leer catálogo desde base de datos en lugar de scraping en vivo

## REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

## ADVERTENCIA DE FALLO DE FONDO EN EJECUCIÓN
`stream_movie` en `src/api/xtream.py` scrapea en vivo usando `catalog_service.get_catalog(...)`, mientras que `get_vod_streams` obtiene el catálogo y genera los `stream_id` desde la base de datos SQLite local (`data/gateway.db`).
Aunque el código compile, esto causa un fallo crítico en ejecución: los `stream_id` asignados al cliente Xtream no coinciden con el catálogo scrapeado en vivo, por lo que al intentar reproducir una película se reproduce la película equivocada o falla la resolución.

## PASO 1: Reemplazar scraping en vivo por lectura de base de datos en stream_movie (`src/api/xtream.py`)

1. Leer el archivo `src/api/xtream.py`.
2. Ubicar la función `stream_movie(stream_id: int, ...)` alrededor de la línea 409.
3. Localizar exactamente estas tres líneas dentro del cuerpo de `stream_movie`:
```python
    catalog = await catalog_service.get_catalog("cuevana3")
    catalog2 = await catalog_service.get_catalog("cuevan_net")
    media = _stream_id_to_media(stream_id, "movie", catalog + catalog2)
```
4. Reemplazar únicamente esas tres líneas por:
```python
    all_movies = await _load_catalog_from_db()
    media = _stream_id_to_media(stream_id, "movie", all_movies)
```
5. Verificar las restricciones:
   - NO modificar `get_series` ni `get_live_streams`.
   - NO modificar `resolve_playback`.
   - NO modificar `_stream_id_to_media`.
   - NO modificar `stream_series` ni `stream_live`.
   - NO modificar ningún archivo de test.
6. Dejar el archivo compilando sin errores de sintaxis (`python3 -m py_compile src/api/xtream.py`).

ACEPTACION
grep -q "all_movies = await _load_catalog_from_db()" src/api/xtream.py
grep -q 'media = _stream_id_to_media(stream_id, "movie", all_movies)' src/api/xtream.py
! grep -A 10 "async def stream_movie" src/api/xtream.py | grep -q "catalog_service.get_catalog"
pytest tests/test_xtream.py

PREMISES
- src/api/xtream.py:409-411 — stream_movie usa catalog_service.get_catalog("cuevana3")
- src/api/xtream.py:21 — _load_catalog_from_db() existe y lee de data/gateway.db
- src/api/xtream.py:380 — _stream_id_to_media() funciona con list[MediaItem]
- tests/test_xtream.py — 20 tests pasando actualmente
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
