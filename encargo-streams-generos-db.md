# Encargo: get_vod_streams — leer géneros de la BD, no del adapter

## Problema
`get_vod_streams` en `src/api/xtream.py` (línea 180-202) lee de `catalog_service.get_catalog()` que devuelve items con `genres=[]`. Los géneros reales están en la BD SQLite pero el endpoint no los consulta.

Resultado: `_genre_to_id(item.genres, sorted_genres)` recibe `genres=[]` → devuelve siempre `"1"` → todas las pelis aparecen en categoría "Acción" (la categoría 1).

## Qué hacer
En `src/api/xtream.py`, dentro del bloque `if action == "get_vod_streams":` (línea ~180):

1. Después de obtener `unique_movies` del adapter, leer los géneros de la BD y enriquecer los items:

```python
import aiosqlite

async def _enrich_genres_from_db(items: list[MediaItem]) -> list[MediaItem]:
    """Lee géneros de la BD y los inyecta en los items que los tienen vacíos."""
    async with aiosqlite.connect("data/gateway.db") as db:
        async with db.execute("SELECT provider_id, genres FROM media WHERE media_type='movie' AND genres IS NOT NULL AND genres != '[]'") as cur:
            db_genres = {row[0]: json.loads(row[1]) async for row in cur}
    for item in items:
        if not item.genres and item.provider_id in db_genres:
            item.genres = db_genres[item.provider_id]
    return items
```

2. Llamar `unique_movies = await _enrich_genres_from_db(unique_movies)` antes de calcular `genres_set`.

## Qué NO tocar
- No cambiar la lógica de filtrado por category_id
- No cambiar series ni live TV
- No modificar adapters ni catalog_service

## ACEPTACION
ssh root@192.168.122.120 "curl -s 'http://localhost:9193/player_api.php?username=test&password=test&action=get_vod_streams' | python3 -c 'import sys,json; data=json.load(sys.stdin); cats=set(d.get(\"category_id\") for d in data); print(f\"Categorías usadas: {cats}\"); assert cats != {\"1\"}, \"Siguen todos en cat 1\"'"

## PREMISES
src/api/xtream.py:180 — get_vod_streams lee de catalog_service.get_catalog()
src/api/xtream.py:63 — _media_item_to_vod_stream usa _genre_to_id(item.genres, sorted_genres)
src/api/xtream.py:24-30 — _genre_to_id devuelve "1" cuando genres está vacío
data/gateway.db — tabla media con provider_id y genres JSON poblados
