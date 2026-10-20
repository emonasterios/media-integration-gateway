<!-- spec:62525d72217b51552580a3ca41dfe2a0 -->
# Encargo: Arreglar tests de Xtream tras migración de catálogo a BD con fallback

## REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

## ADVERTENCIA DE FALLO DE FONDO
Si se añade el filtrado `m.media_type == MediaType.MOVIE` sin asegurar que `MediaType` está importado en `src/api/xtream.py`, el código compilará pero reventará en tiempo de ejecución con `NameError: name 'MediaType' is not defined`. Asimismo, `_load_catalog_from_db` debe mantener `fallback: list[MediaItem] | None = None` con valor por defecto opcional para que cualquier otra llamada existente no falle por falta de argumentos.

---

## PASO 1: Asegurar imports y parametrizar `_load_catalog_from_db` con fallback
**Archivo a modificar:** `src/api/xtream.py`

1. Leer `src/api/xtream.py`.
2. Verificar las importaciones desde `src.models.catalog`. Asegurar que incluya `MediaType` junto con `MediaItem`:
   ```python
   from src.models.catalog import MediaItem, MediaType
   ```
3. Modificar la cabecera y el inicio de `_load_catalog_from_db` (alrededor de la línea 15) para aceptar `fallback`:
   ```python
   async def _load_catalog_from_db(fallback: list[MediaItem] | None = None) -> list[MediaItem]:
       """Carga el catálogo desde SQLite, con fallback si la BD no existe."""
       if not DB_PATH.exists():
           return fallback or []
   ```
   Mantener exactamente el resto de la lógica de conexión SQLite y lectura de BD que ya existe en la función.
4. Guardar y verificar que el proyecto compila sintácticamente (`python3 -m py_compile src/api/xtream.py`).

---

## PASO 2: Conectar fallback en `get_vod_streams` y `get_vod_info`
**Archivo a modificar:** `src/api/xtream.py`

1. Leer `src/api/xtream.py` en las funciones `get_vod_streams` (aprox. línea 234) y `get_vod_info` (aprox. línea 258).
2. En `get_vod_streams`, sustituir la llamada directa a `_load_catalog_from_db()` por la obtención de películas desde `catalog_service` como fallback:
   ```python
   fallback_movies = [m for m in (await catalog_service.get_catalog("cuevana3")) if m.media_type == MediaType.MOVIE]
   unique_movies = await _load_catalog_from_db(fallback=fallback_movies)
   ```
3. En `get_vod_info`, sustituir la llamada directa a `_load_catalog_from_db()` por la obtención de películas desde `catalog_service` como fallback:
   ```python
   fallback_movies = [m for m in (await catalog_service.get_catalog("cuevana3")) if m.media_type == MediaType.MOVIE]
   all_movies = await _load_catalog_from_db(fallback=fallback_movies)
   ```
4. NO alterar `_media_item_to_vod_stream`, `_stream_id_to_media`, `get_vod_categories`, `get_series`, `get_live_streams` ni los archivos de tests.
5. Guardar y verificar que el proyecto compila sintácticamente (`python3 -m py_compile src/api/xtream.py`).

---

ACEPTACION
grep -q "MediaType" src/api/xtream.py
grep -q "def _load_catalog_from_db(fallback: list\[MediaItem\] | None = None)" src/api/xtream.py
grep -q "return fallback or \[\]" src/api/xtream.py
grep -q "fallback_movies = \[m for m in (await catalog_service.get_catalog(\"cuevana3\")) if m.media_type == MediaType.MOVIE\]" src/api/xtream.py
grep -q "unique_movies = await _load_catalog_from_db(fallback=fallback_movies)" src/api/xtream.py
grep -q "all_movies = await _load_catalog_from_db(fallback=fallback_movies)" src/api/xtream.py
pytest tests/test_xtream.py::test_player_api_get_vod_streams tests/test_xtream.py::test_player_api_get_vod_streams_filtered_by_category tests/test_xtream.py::test_player_api_get_vod_info

PREMISES
- src/api/xtream.py:15-42 — `_load_catalog_from_db()` actual, lee de DB_PATH, retorna [] si no existe
- src/api/xtream.py:234 — `get_vod_streams` llama a `_load_catalog_from_db()` sin fallback
- src/api/xtream.py:258 — `get_vod_info` llama a `_load_catalog_from_db()` sin fallback
- tests/test_xtream.py:45-79 — `FakeCuevana3Provider.get_catalog()` devuelve 2 películas + 1 serie
- tests/test_xtream.py:416 — test espera `len(data) == 3`
- tests/test_xtream.py:442 — test espera `len(data) == 2` para category_id=1
- tests/test_xtream.py:461 — test espera `data["info"]["name"] == "Película Test 1"`
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
