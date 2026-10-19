# Enriquecer catálogo con géneros reales

## Problema
`get_catalog()` en `src/adapters/cuevana3.py` scrapea `/peliculas/` (lista de posts) — los géneros no están en esa vista. Los géneros solo se extraen en `get_details()` (línea 242) que visita la página individual de cada película. Resultado: 1139 películas en caché con `genres=[]`.

## Qué hacer

### 1. Agregar campo `genres` al modelo Media
- **Archivo**: `src/db/models.py`
- Agregar `genres = Column(Text, nullable=True)` al modelo `Media` (línea 24, después de `poster_url`)
- Guardar como JSON string: `json.dumps(genres)`

### 2. Crear migración Alembic
- `cd /home/emon/media-integration-gateway && . .venv/bin/activate && alembic revision --autogenerate -m "add genres column to media"`
- Si alembic no está configurado, crear `alembic.ini` y `alembic/` con la estructura mínima apuntando a `sqlite:///./data/catalog.db`

### 3. Actualizar CatalogCache.save_media
- **Archivo**: `src/services/cache.py`, método `save_media` (línea 60)
- El `item_data` ya incluye `genres` (viene de MediaItem). Asegurar que si `genres` es una lista, se serialice a JSON string antes de guardar:
```python
if "genres" in item_data and isinstance(item_data["genres"], list):
    item_data["genres"] = json.dumps(item_data["genres"])
```
- Y al leer, deserializar:
```python
if media.genres and isinstance(media.genres, str):
    media.genres = json.loads(media.genres)
```

### 4. Crear script de enriquecimiento `scripts/enrich_genres.py`
- Lee todas las películas de la BD con `genres IS NULL` o `genres = '[]'`
- Para cada una, llama a `adapter.get_details(media_id)` que extrae géneros
- Actualiza el registro en la BD con los géneros
- Rate limit: 1 request cada 2 segundos
- Progreso: log cada 10 películas
- Uso: `python scripts/enrich_genres.py [--limit N] [--provider cuevana3]`

### 5. Actualizar get_vod_categories en xtream.py
- **Archivo**: `src/api/xtream.py`, línea ~113
- En lugar de leer del caché en memoria, leer géneros directamente de la BD
- Query: `SELECT DISTINCT genres FROM media WHERE media_type='movie' AND genres IS NOT NULL AND genres != '[]'`
- Construir las categorías desde los géneros únicos encontrados
- Fallback: si no hay géneros en BD, devolver `{"category_id": "1", "category_name": "Peliculas"}`

### 6. Actualizar el warmup en main.py
- Después de cargar el caché, disparar `enrich_genres.py` en background (sin await)
- El enriquecimiento es incremental y no bloquea el startup

## NO tocar
- `src/adapters/cuevana3.py` (la extracción de géneros ya funciona en get_details)
- `src/api/xtream.py` líneas de streaming/proxy (funcionan)
- Tests existentes (agregar tests nuevos si es necesario)

## ACEPTACION
```bash
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v
cd /home/emon/media-integration-gateway && . .venv/bin/activate && python scripts/enrich_genres.py --limit 5
```

## PREMISES
- src/db/models.py:12-26 — modelo Media sin campo genres
- src/adapters/cuevana3.py:242 — _extract_genres funciona en get_details
- src/adapters/cuevana3.py:186-198 — get_catalog crea MediaItem sin genres
- src/services/cache.py:60-102 — save_media persiste item_data pero genres no existe en el modelo
- src/api/xtream.py:113-160 — get_vod_categories lee del caché en memoria, no de la BD
