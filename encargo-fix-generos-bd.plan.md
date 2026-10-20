<!-- spec:7755822ee67f7b052bdc5d0f7bddf5e5 -->
# ENCARGO: Fix get_vod_categories — leer géneros reales de la BD SQLite

## FALLO DE FONDO PREVIO
En `src/api/xtream.py`, la acción `get_vod_categories` intenta ejecutar `catalog_service.db.get_connection()`. La clase `CatalogService` no tiene ningún atributo `db`. Esto produce un `AttributeError` silencioso que es capturado por un `try/except`, provocando que nunca se consulte la base de datos y cayendo siempre al fallback vacío, mostrando únicamente "Peliculas" como categoría. Se debe reemplazar ese bloque por una conexión directa y asíncrona a la base de datos SQLite (`data/gateway.db`) usando `aiosqlite`.

---

## REGLAS PARA EL EJECUTOR
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

---

## PASO 1: Reemplazar la consulta de géneros por aiosqlite en src/api/xtream.py

**Archivo a modificar:** `src/api/xtream.py`

1. Leer `src/api/xtream.py` y localizar el bloque dentro de `if action == "get_vod_categories":` (aproximadamente líneas 143 a 157).
2. Localizar exactamente el siguiente fragmento:
```python
    if action == "get_vod_categories":
        genres: set[str] = set()
        try:
            conn = catalog_service.db.get_connection()
        except AttributeError:
            conn = None
        if conn is not None:
            cursor = conn.execute(
                "SELECT DISTINCT genres FROM media WHERE media_type='movie' AND genres IS NOT NULL AND genres != '[]'"
            )
            for row in cursor.fetchall():
                try:
                    for genre in json.loads(row[0]):
                        genres.add(genre)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
```
3. Sustituir dicho fragmento EXACTAMENTE por:
```python
    if action == "get_vod_categories":
        genres: set[str] = set()
        import aiosqlite
        try:
            async with aiosqlite.connect("data/gateway.db") as db:
                async with db.execute(
                    "SELECT genres FROM media WHERE media_type='movie' AND genres IS NOT NULL AND genres != '[]'"
                ) as cursor:
                    async for row in cursor:
                        try:
                            for genre in json.loads(row[0]):
                                genres.add(genre)
                        except (TypeError, ValueError, json.JSONDecodeError):
                            continue
        except Exception:
            pass
```
4. NO tocar ninguna otra línea ni función de `src/api/xtream.py`.
5. Verificar que el archivo compila sin errores sintácticos ejecutando `python3 -m py_compile src/api/xtream.py`.

---

ACEPTACION
grep -q "import aiosqlite" src/api/xtream.py
grep -q 'async with aiosqlite.connect("data/gateway.db") as db:' src/api/xtream.py
grep -q "SELECT genres FROM media WHERE media_type='movie' AND genres IS NOT NULL AND genres != '\[\]'" src/api/xtream.py
grep -q "async for row in cursor:" src/api/xtream.py
python3 -c "code = open('src/api/xtream.py').read(); assert 'catalog_service.db' not in code"
python3 -c "import ast; ast.parse(open('src/api/xtream.py').read())"
pytest tests/test_xtream.py

PREMISES
src/api/xtream.py:145 usa catalog_service.db.get_connection() que no existe
src/api/xtream.py:149-157 lee géneros con SQL pero nunca se ejecuta por AttributeError
docker-compose.yml: DATABASE_URL=sqlite+aiosqlite:///./data/gateway.db
src/db/database.py:26 define AsyncSessionLocal
94 tests passing
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
