# Encargo: Fix get_vod_categories — leer géneros reales de la BD

## Problema
`get_vod_categories` en `src/api/xtream.py` intenta `catalog_service.db.get_connection()` pero `CatalogService` no tiene atributo `db`. Siempre cae al fallback que lee del caché del adapter (géneros vacíos). Resultado: solo muestra "Peliculas" como categoría.

## Qué hacer
1. En `src/api/xtream.py`, línea 145-157: reemplazar el bloque `try/except` que usa `catalog_service.db.get_connection()` por una lectura directa de la BD SQLite usando `aiosqlite`.
2. La BD está en `./data/gateway.db` (configurada en docker-compose como `sqlite+aiosqlite:///./data/gateway.db`).
3. Usar `import aiosqlite` y abrir la BD con `aiosqlite.connect("data/gateway.db")` para hacer `SELECT genres FROM media WHERE media_type='movie' AND genres IS NOT NULL AND genres != '[]'`.
4. Parsear cada fila con `json.loads(row[0])` y acumular en el set `genres`.
5. NO tocar nada más del archivo.

## Código exacto para reemplazar (líneas 143-157)
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

Reemplazar por:
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

## ACEPTACION
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v
cd /home/emon/media-integration-gateway && . .venv/bin/activate && python -c "import ast; ast.parse(open('src/api/xtream.py').read()); print('OK')"

## PREMISES
src/api/xtream.py:145 usa catalog_service.db.get_connection() que no existe
src/api/xtream.py:149-157 lee géneros con SQL pero nunca se ejecuta por AttributeError
docker-compose.yml: DATABASE_URL=sqlite+aiosqlite:///./data/gateway.db
src/db/database.py:26 define AsyncSessionLocal
94 tests passing
