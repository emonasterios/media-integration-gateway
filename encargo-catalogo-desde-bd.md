# Encargo: Leer catálogo desde BD en lugar de scrapear en vivo

## Problema
Los endpoints `get_vod_streams` (línea 234) y `get_vod_info` (línea 260) llaman a `catalog_service.get_catalog()` que scrapea Cuevana3 EN VIVO cada vez. Esto es:
- **Lento**: scraping de múltiples páginas por cada request
- **Incompleto**: solo trae las primeras páginas, no las 911 películas de la BD
- **Inconsistente**: el catálogo vivo cambia, la BD es estable

## Solución
Modificar `get_vod_streams` y `get_vod_info` para leer desde la BD SQLite (`data/gateway.db`) en lugar de scrapear en vivo.

## Cambios requeridos

### 1. Nueva función `_load_catalog_from_db()`
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

### 2. Modificar `get_vod_streams` (línea 234-258)
Reemplazar:
```python
catalog = await catalog_service.get_catalog("cuevana3")
catalog2 = await catalog_service.get_catalog("cuevan_net")
```
Por:
```python
unique_movies = await _load_catalog_from_db()
```
Eliminar la lógica de deduplicación (la BD ya está limpia).

### 3. Modificar `get_vod_info` (línea 260-287)
Reemplazar:
```python
catalog = await catalog_service.get_catalog("cuevana3")
catalog2 = await catalog_service.get_catalog("cuevan_net")
```
Por:
```python
all_movies = await _load_catalog_from_db()
```
Eliminar la lógica de deduplicación.

## NO tocar
- `resolve_playback` → funciona bien (scrapea página específica con URL guardada)
- `get_vod_categories` → ya lee de BD
- `get_series_*` → no son parte de este encargo
- Tests existentes → deben seguir pasando

## ACEPTACION
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v
cd /home/emon/media-integration-gateway && . .venv/bin/activate && python3 -c "import asyncio; from src.api.xtream import _load_catalog_from_db; items = asyncio.get_event_loop().run_until_complete(_load_catalog_from_db()); print(f'Catálogo desde BD: {len(items)} películas'); assert len(items) > 900, f'Solo {len(items)} películas'"

## PREMISES
- src/api/xtream.py línea 236-237: llama a catalog_service.get_catalog() en get_vod_streams
- src/api/xtream.py línea 267-268: llama a catalog_service.get_catalog() en get_vod_info
- src/api/xtream.py línea 1-20: ya importa aiosqlite y json
- data/gateway.db existe con 911+ películas en tabla media
- MediaItem tiene campos: provider_id, title, original_title, media_type, year, overview, poster_url, genres
