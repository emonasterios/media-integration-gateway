<!-- spec:33fa1cf8806e2e435b5905e8ce2dedf1 -->
# ENCARGO: Cargar catálogo VOD desde BD SQLite en Xtream Codes

## REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- Cada paso debe dejar el proyecto COMPILANDO y ejecutable.

---

## ADVERTENCIA DE FALLO DE FONDO
Al desacoplar `get_vod_streams` y `get_vod_info` de `catalog_service.get_catalog()`, cualquier test unitario en `tests/test_xtream.py` que estuviera simulando (`mock`/`patch`) `catalog_service.get_catalog` fallará de inmediato porque el código ahora ejecutará `_load_catalog_from_db()`, abriendo `data/gateway.db` o ignorando el mock. Se debe actualizar el mock en los tests para apuntar a `src.api.xtream._load_catalog_from_db`.

---

## PASO 1: Implementar `_load_catalog_from_db` y conectar los endpoints en `src/api/xtream.py`

**Archivo:** `src/api/xtream.py`

1. Leer `src/api/xtream.py` para ubicar las importaciones, `get_vod_streams` (alrededor de línea 234) y `get_vod_info` (alrededor de línea 260).
2. Asegurar que estén importados `aiosqlite`, `json`, y `MediaItem`, `MediaType` (desde `src.models.catalog`).
3. Definir la función auxiliar:
```python
async def _load_catalog_from_db() -> list[MediaItem]:
    """Carga el catálogo completo desde SQLite."""
    async with aiosqlite.connect("data/gateway.db") as db:
        async with db.execute(
            "SELECT id, title, original_title, media_type, year, synopsis, poster_url, genres "
            "FROM media WHERE media_type = 'movie' ORDER BY title"
        ) as cur:
            rows = await cur.fetchall()

    return [
        MediaItem(
            provider_id=str(row[0]),
            title=row[1],
            original_title=row[2],
            media_type=MediaType.MOVIE,
            year=row[4],
            overview=row[5],
            poster_url=row[6],
            genres=json.loads(row[7]) if row[7] else [],
        )
        for row in rows
    ]
```
4. En `get_vod_streams`:
   - Sustituir las llamadas a `catalog_service.get_catalog("cuevana3")` y `catalog_service.get_catalog("cuevan_net")` y la lógica de deduplicación de diccionarios por:
     ```python
     unique_movies = await _load_catalog_from_db()
     ```
   - Mantener el filtrado por categoría (`category_id`) y el mapeo a `VodStream`.
5. En `get_vod_info`:
   - Sustituir las llamadas a `catalog_service.get_catalog(...)` y la lógica de deduplicación por:
     ```python
     all_movies = await _load_catalog_from_db()
     ```
   - Mantener la búsqueda de la película por ID y la construcción de `VodInfoResponse`.
6. NO modificar `resolve_playback`, `get_vod_categories` ni `get_series_*`.

---

## PASO 2: Actualizar tests en `tests/test_xtream.py`

**Archivo:** `tests/test_xtream.py`

1. Leer `tests/test_xtream.py` identificando las pruebas que ejecutan `get_vod_streams` y `get_vod_info`.
2. Si los tests aplican `unittest.mock.patch` sobre `catalog_service.get_catalog` (o similar), cambiar el objetivo del patch a `src.api.xtream._load_catalog_from_db` para que devuelva la lista simulada de `MediaItem`.
3. Si los tests invocan los endpoints esperando datos de prueba, asegurarse de que `_load_catalog_from_db` devuelva los objetos `MediaItem` esperados por cada caso de prueba.
4. Ejecutar `pytest tests/test_xtream.py` y verificar que la suite completa pase sin errores.

---

ACEPTACION
test -f src/api/xtream.py
grep -q "async def _load_catalog_from_db" src/api/xtream.py
grep -q "unique_movies = await _load_catalog_from_db()" src/api/xtream.py
grep -q "all_movies = await _load_catalog_from_db()" src/api/xtream.py
! grep -q 'catalog_service.get_catalog("cuevana3")' src/api/xtream.py
! grep -q 'catalog_service.get_catalog("cuevan_net")' src/api/xtream.py
pytest tests/test_xtream.py -v
pytest tests/ -v
python3 -c "import asyncio; from src.api.xtream import _load_catalog_from_db; items = asyncio.run(_load_catalog_from_db()); assert len(items) > 900, f'Solo {len(items)} peliculas'"

PREMISES
- src/api/xtream.py línea 236-237: llama a catalog_service.get_catalog() en get_vod_streams
- src/api/xtream.py línea 267-268: llama a catalog_service.get_catalog() en get_vod_info
- src/api/xtream.py línea 1-20: ya importa aiosqlite y json
- data/gateway.db existe con 911+ películas en tabla media
- MediaItem tiene campos: provider_id, title, original_title, media_type, year, overview, poster_url, genres
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
