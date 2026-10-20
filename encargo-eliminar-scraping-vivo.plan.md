<!-- spec:341aa57dedea715e35c758c445927b5d -->
# ENCARGO: Eliminar scraping en vivo del catálogo VOD y leer exclusivamente de la base de datos

## REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

---

## PASO 1: Actualizar funciones de acceso a BD y desacoplar scraping de VOD en `src/api/xtream.py`

### Archivo a modificar
`src/api/xtream.py`

### Objetivo
Hacer que las funciones auxiliares de BD acepten una ruta parametrizable (`db_path`), eliminar el scraping en vivo de Cuevana3/cuevan_net en `get_vod_streams` y `get_vod_info`, y garantizar que `get_vod_categories` use `DB_PATH`.

### Cambios concretos
1. **Asegurar imports**: Verificar que `json`, `aiosqlite` y `Path` estén importados al inicio o dentro del archivo.
2. **Modificar `_enrich_genres_from_db`**:
   Cambiar su firma e implementación para aceptar `db_path: Path | str | None = None` y usar `target = Path(db_path) if db_path else DB_PATH`:
   ```python
   async def _enrich_genres_from_db(items: list[MediaItem], db_path: Path | str | None = None) -> list[MediaItem]:
       """Lee géneros de la BD y los inyecta en los items que los tienen vacíos."""
       target = Path(db_path) if db_path else DB_PATH
       if not target.exists():
           return items
       try:
           async with aiosqlite.connect(str(target)) as db:
               async with db.execute(
                   "SELECT id, genres FROM media WHERE media_type='movie' AND genres IS NOT NULL AND genres != '[]'"
               ) as cur:
                   db_genres = {str(row[0]): json.loads(row[1]) async for row in cur}
           for item in items:
               if not item.genres:
                   if item.provider_id in db_genres:
                       item.genres = db_genres[item.provider_id]
                   elif item.media_id in db_genres:
                       item.genres = db_genres[item.media_id]
       except Exception:
           pass
       return items
   ```
3. **Modificar `_load_catalog_from_db`**:
   Eliminar el parámetro `fallback` y aceptar `db_path: Path | str | None = None`:
   ```python
   async def _load_catalog_from_db(db_path: Path | str | None = None) -> list[MediaItem]:
       """Carga el catálogo VOD desde SQLite. db_path permite tests con BD en memoria."""
       target = Path(db_path) if db_path else DB_PATH
       if not target.exists():
           return []
       async with aiosqlite.connect(str(target)) as db:
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
4. **En el manejador `action == "get_vod_streams"`**:
   Eliminar el bucle de scraping `fallback_movies = []` que llama a `catalog_service.get_catalog(provider_name)` y sustituir la llamada por:
   ```python
   unique_movies = await _load_catalog_from_db()
   ```
5. **En el manejador `action == "get_vod_info"`**:
   Eliminar el bucle de scraping `fallback_movies = []` que llama a `catalog_service.get_catalog(provider_name)` y sustituir la llamada por:
   ```python
   all_movies = await _load_catalog_from_db()
   ```
6. **En `get_vod_categories`**:
   Si existe alguna referencia directa a `catalog_service.db` para leer géneros, usar `DB_PATH`.
7. **NO TOCAR**: endpoints de series (`get_series`, `get_series_info`), streams en vivo (`get_live_streams`), ni `resolve_playback`.

---

## PASO 2: Adaptar los tests en `tests/test_xtream.py` usando base de datos de prueba

### Archivo a modificar
`tests/test_xtream.py`

### Objetivo
Añadir una fixture `temp_db_path` con películas y géneros de prueba en SQLite y actualizar los tests de endpoints VOD para apuntar temporalmente `xtream_module.DB_PATH` a esa BD.

### Cambios concretos
1. **Añadir fixture `temp_db_path`**:
   ```python
   @pytest.fixture
   def temp_db_path(tmp_path):
       """Crea una BD SQLite temporal con datos de prueba."""
       import sqlite3
       db_path = tmp_path / "test_gateway.db"
       conn = sqlite3.connect(str(db_path))
       conn.execute("""CREATE TABLE media (
           id INTEGER PRIMARY KEY,
           title TEXT,
           original_title TEXT,
           media_type TEXT,
           year INTEGER,
           synopsis TEXT,
           poster_url TEXT,
           genres TEXT
       )""")
       conn.execute("INSERT INTO media VALUES (1, 'Test Movie', 'Test Movie', 'movie', 2024, 'Overview', 'http://poster.jpg', '[\"Acción\", \"Drama\"]')")
       conn.execute("INSERT INTO media VALUES (2, 'Another Movie', 'Another Movie', 'movie', 2023, 'Overview 2', 'http://poster2.jpg', '[\"Comedia\"]')")
       conn.execute("INSERT INTO media VALUES (3, 'Third Movie', 'Third Movie', 'movie', 2022, 'Overview 3', 'http://poster3.jpg', '[\"Terror\", \"Suspense\"]')")
       conn.commit()
       conn.close()
       return db_path
   ```
2. **Actualizar `test_player_api_get_vod_streams`**:
   Inyectar `temp_db_path` y sobrescribir temporalmente `xtream_module.DB_PATH`:
   ```python
   def test_player_api_get_vod_streams(client, temp_db_path):
       import src.api.xtream as xtream_module
       original_db_path = xtream_module.DB_PATH
       xtream_module.DB_PATH = temp_db_path
       try:
           response = client.get("/player_api.php", params={
               "username": "test",
               "password": "test",
               "action": "get_vod_streams",
           })
           assert response.status_code == 200
           data = response.json()
           assert isinstance(data, list)
           assert len(data) > 0
       finally:
           xtream_module.DB_PATH = original_db_path
   ```
3. **Actualizar `test_player_api_get_vod_streams_filtered_by_category`**:
   Inyectar `temp_db_path` y fijar `xtream_module.DB_PATH = temp_db_path` en bloque `try ... finally` para restaurar el valor original al terminar.
4. **Actualizar `test_player_api_get_vod_info`**:
   Inyectar `temp_db_path` y fijar `xtream_module.DB_PATH = temp_db_path` en bloque `try ... finally` para restaurar el valor original al terminar.

---

ACEPTACION
grep -q "async def _load_catalog_from_db(db_path: Path | str | None = None)" src/api/xtream.py
grep -q "unique_movies = await _load_catalog_from_db()" src/api/xtream.py
grep -q "all_movies = await _load_catalog_from_db()" src/api/xtream.py
grep -q "def temp_db_path(tmp_path):" tests/test_xtream.py
grep -q "xtream_module.DB_PATH = temp_db_path" tests/test_xtream.py
python3 -m py_compile src/api/xtream.py
python3 -m py_compile tests/test_xtream.py

PREMISES
src/api/xtream.py:234 — get_vod_streams llama a catalog_service.get_catalog() como fallback
src/api/xtream.py:263 — get_vod_info llama a catalog_service.get_catalog() como fallback
src/api/xtream.py:197 — _load_catalog_from_db tiene parámetro fallback
src/api/xtream.py:84 — _enrich_genres_from_db tiene db_path hardcodeado
src/api/xtream.py:194 — DB_PATH definido como Path
tests/test_xtream.py:372 — test_player_api_get_vod_streams no usa BD temporal
tests/test_xtream.py:430 — test_player_api_get_vod_info no usa BD temporal
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
