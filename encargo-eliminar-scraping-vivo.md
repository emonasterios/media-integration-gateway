# Encargo: Eliminar scraping en vivo del catálogo VOD — leer SOLO de BD

## Problema
`get_vod_streams` y `get_vod_info` llaman a `catalog_service.get_catalog()` que scrapea Cuevana3 en vivo CADA VEZ. Esto es lento, incompleto (solo primeras páginas), y causa que películas como "Empire of Lies" no aparezcan.

## Solución
Leer el catálogo VOD SOLO desde `data/gateway.db`. Sin fallback a scraping en vivo.

**Nota**: Solo afectar endpoints VOD (películas). NO tocar `get_series`, `get_live_streams`, ni otros endpoints que aún necesitan scraping.

## Qué cambiar en src/api/xtream.py

### 1. En `get_vod_streams` (~línea 234)

Código actual:
```python
fallback_movies = []
for provider_name in ("cuevana3", "cuevan_net"):
    fallback_movies.extend(
        [m for m in (await catalog_service.get_catalog(provider_name)) if m.media_type == MediaType.MOVIE]
    )
unique_movies = await _load_catalog_from_db(fallback=fallback_movies)
```

Reemplazar por:
```python
unique_movies = await _load_catalog_from_db()
```

### 2. En `get_vod_info` (~línea 263)

Código actual:
```python
fallback_movies = []
for provider_name in ("cuevana3", "cuevan_net"):
    fallback_movies.extend(
        [m for m in (await catalog_service.get_catalog(provider_name)) if m.media_type == MediaType.MOVIE]
    )
all_movies = await _load_catalog_from_db(fallback=fallback_movies)
```

Reemplazar por:
```python
all_movies = await _load_catalog_from_db()
```

### 3. Modificar `_load_catalog_from_db` para aceptar db_path configurable

Código actual:
```python
async def _load_catalog_from_db(fallback: list[MediaItem] | None = None) -> list[MediaItem]:
    if not DB_PATH.exists():
        return fallback or []
    ...
```

Reemplazar por:
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

### 4. Modificar `_enrich_genres_from_db` para aceptar db_path configurable

Código actual:
```python
async def _enrich_genres_from_db(items: list[MediaItem], db_path: str = "data/gateway.db") -> list[MediaItem]:
    try:
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            ...
    except Exception:
        pass
    return items
```

Reemplazar por:
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

### 5. Modificar `get_vod_categories` para usar db_path configurable

La función que lee géneros de la BD (dentro de `xtream_player_api`, ~línea 197) debe usar `DB_PATH` directamente en vez de `catalog_service.db`.

## Qué cambiar en tests/test_xtream.py

### 1. Agregar fixture de BD en memoria

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

### 2. Modificar tests para usar la BD temporal

En `test_player_api_get_vod_streams`, `test_player_api_get_vod_streams_filtered_by_category`, `test_player_api_get_vod_info`:

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

## Qué NO cambiar
- `get_series` → sigue usando scraping (por ahora)
- `get_live_streams` → sigue usando scraping (por ahora)
- `resolve_playback` → sigue funcionando (scrapea página específica con URL guardada)
- `CatalogService` → se mantiene para series y otros usos
- `FakeCuevana3Provider` → se mantiene para otros tests

## ACEPTACION
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/test_xtream.py::test_player_api_get_vod_streams tests/test_xtream.py::test_player_api_get_vod_streams_filtered_by_category tests/test_xtream.py::test_player_api_get_vod_info -v
cd /home/emon/media-integration-gateway && . .venv/bin/activate && python scripts/accept_cuevana3.py
cd /home/emon/media-integration-gateway && . .venv/bin/activate && python scripts/accept_cache.py

## PREMISES
src/api/xtream.py:234 — get_vod_streams llama a catalog_service.get_catalog() como fallback
src/api/xtream.py:263 — get_vod_info llama a catalog_service.get_catalog() como fallback
src/api/xtream.py:197 — _load_catalog_from_db tiene parámetro fallback
src/api/xtream.py:84 — _enrich_genres_from_db tiene db_path hardcodeado
src/api/xtream.py:194 — DB_PATH definido como Path
tests/test_xtream.py:372 — test_player_api_get_vod_streams no usa BD temporal
tests/test_xtream.py:430 — test_player_api_get_vod_info no usa BD temporal
