<!-- spec:9de7161bfabc2c20ff2a9d49c79b4077 -->
# ENCARGO: Enriquecer géneros en get_vod_streams desde la base de datos

## REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

---

## PASO 1: Implementar función de enriquecimiento y conectarla en get_vod_streams
**Archivo a modificar:** `src/api/xtream.py`

**Fallo de fondo a prevenir:**
Si `data/gateway.db` no existe en el entorno de ejecución o la tabla `media` no está creada, una conexión a ciegas con `aiosqlite` lanzará `sqlite3.OperationalError` y tumbará el endpoint con error 500 en tiempo de ejecución aunque el código compile. La función de enriquecimiento debe capturar errores y retornar la lista intacta si la base de datos no está disponible.

**Acciones concretas:**
1. Leer `src/api/xtream.py`.
2. Asegurar la importación de `json`, `aiosqlite` y `os.path` (o manejo seguro mediante `try/except Exception`).
3. Definir la función auxiliar `_enrich_genres_from_db`:
```python
async def _enrich_genres_from_db(items: list[MediaItem]) -> list[MediaItem]:
    """Lee géneros de la BD y los inyecta en los items que los tienen vacíos."""
    db_path = "data/gateway.db"
    if not os.path.exists(db_path):
        return items
    try:
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT provider_id, genres FROM media WHERE media_type='movie' AND genres IS NOT NULL AND genres != '[]'"
            ) as cur:
                db_genres = {row[0]: json.loads(row[1]) async for row in cur}
        for item in items:
            if not item.genres and item.provider_id in db_genres:
                item.genres = db_genres[item.provider_id]
    except Exception:
        pass
    return items
```
4. Dentro del bloque `if action == "get_vod_streams":`, inmediatamente después de obtener `unique_movies` y ANTES de calcular `genres_set`, añadir la llamada:
```python
unique_movies = await _enrich_genres_from_db(unique_movies)
```
5. No modificar la lógica de `get_series`, `get_live_streams`, ni la asignación de categorías posterior.
6. Verificar que el archivo compila sin errores de sintaxis ejecutando: `python3 -m py_compile src/api/xtream.py`.

---

## PASO 2: Agregar tests unitarios para verificar el enriquecimiento de géneros
**Archivo a modificar:** `tests/test_xtream.py`

**Acciones concretas:**
1. Leer `tests/test_xtream.py`.
2. Añadir un caso de prueba `test_enrich_genres_from_db` que valide que:
   - Los items con `genres=[]` reciben los géneros correspondientes a su `provider_id` si existen en la BD.
   - Si la BD no existe o lanza error, la función devuelve los items sin romper la ejecución.
3. Añadir o actualizar un test para la acción `get_vod_streams` comprobando que cuando los items tienen géneros, `category_id` no se asigna exclusivamente a `"1"`.
4. Ejecutar la suite de tests de xtream y asegurar que pasa completamente: `python3 -m pytest tests/test_xtream.py`.

---

ACEPTACION
grep -q "import aiosqlite" src/api/xtream.py
grep -q "async def _enrich_genres_from_db" src/api/xtream.py
grep -q "SELECT provider_id, genres FROM media WHERE media_type='movie'" src/api/xtream.py
grep -q "unique_movies = await _enrich_genres_from_db(unique_movies)" src/api/xtream.py
grep -q "test_enrich_genres" tests/test_xtream.py
python3 -m pytest tests/test_xtream.py

PREMISES
src/api/xtream.py:180 — get_vod_streams lee de catalog_service.get_catalog()
src/api/xtream.py:63 — _media_item_to_vod_stream usa _genre_to_id(item.genres, sorted_genres)
src/api/xtream.py:24-30 — _genre_to_id devuelve "1" cuando genres está vacío
data/gateway.db — tabla media con provider_id y genres JSON poblados
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
