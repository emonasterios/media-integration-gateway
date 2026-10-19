# Categorías dinámicas por género para películas

## Problema
`get_vod_categories` en `src/api/xtream.py` línea 114 devuelve solo:
```python
[{"category_id": "1", "category_name": "Peliculas", "parent_id": 0}]
```

Cada `MediaItem` ya tiene `genres: list[str]` (extraído por `_extract_genres` en `cuevana3.py:565`).

## Qué hacer

### 1. En `src/api/xtream.py` — función `_get_vod_categories`

Reemplazar la línea 114 con una función que:
1. Obtiene el catálogo deduplicado (misma lógica que `get_vod_streams`)
2. Extrae todos los géneros únicos ordenados alfabéticamente
3. Asigna `category_id` numérico secuencial (1=N, 2=Acción, etc.)
4. Devuelve lista de `{"category_id": str, "category_name": str, "parent_id": 0}`

### 2. En `src/api/xtream.py` — `get_vod_streams` con filtro

El endpoint `get_vod_streams` acepta `?category_id=X` (parámetro query).
- Si no hay `category_id`: devolver todas las películas (comportamiento actual)
- Si hay `category_id`: filtrar películas cuyo `genres` contenga el género correspondiente

Mapeo: `category_id` → género por posición alfabética. Ejemplo:
```
1 = "N" (sin género)
2 = "Acción"
3 = "Animación"
4 = "Ciencia ficción"
...
```

### 3. En `_media_item_to_vod_stream`

Agregar `"category_id"` al dict de retorno, mapeando el primer género de la película al ID numérico.

## Código exacto

```python
# Nueva función helper (antes de las líneas de action)
def _build_genre_categories(movies: list[MediaItem]) -> list[dict]:
    genres: set[str] = set()
    for m in movies:
        genres.update(m.genres or [])
    if not genres:
        return [{"category_id": "1", "category_name": "Peliculas", "parent_id": 0}]
    sorted_genres = sorted(genres)
    return [
        {"category_id": str(i + 1), "category_name": g, "parent_id": 0}
        for i, g in enumerate(sorted_genres)
    ]

def _genre_to_id(genres: list[str], sorted_genres: list[str]) -> str:
    if not genres or not sorted_genres:
        return "1"
    first = genres[0]
    if first in sorted_genres:
        return str(sorted_genres.index(first) + 1)
    return "1"
```

## Qué NO tocar
- No cambiar `cuevana3.py` (ya extrae géneros correctamente)
- No cambiar `catalog.py`
- No cambiar tests existentes (solo agregar 2 nuevos si cabe)

## ACEPTACION
```bash
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v
cd /home/emon/media-integration-gateway && . .venv/bin/activate && python -c "
import asyncio, sys
sys.path.insert(0, 'src')
from api.xtream import _build_genre_categories
from models.catalog import MediaItem, MediaType
m1 = MediaItem(title='A', media_type=MediaType.MOVIE, provider_id='a', genres=['Acción', 'Thriller'])
m2 = MediaItem(title='B', media_type=MediaType.MOVIE, provider_id='b', genres=['Comedia'])
cats = _build_genre_categories([m1, m2])
assert len(cats) == 3, f'Esperaba 3, got {len(cats)}'
assert cats[0]['category_name'] == 'Acción'
assert cats[1]['category_name'] == 'Comedia'
assert cats[2]['category_name'] == 'Thriller'
print(f'OK: {len(cats)} categorías')
"
```

## PREMISES
- `src/api/xtream.py:114` devuelve 1 categoría hardcodeada "Peliculas"
- `src/models/catalog.py:65` MediaItem tiene `genres: list[str]`
- `src/adapters/cuevana3.py:565-577` `_extract_genres` extrae géneros del HTML
- `src/api/xtream.py:122-131` `get_vod_streams` obtiene catálogo y aplica deduplicación
- `src/api/xtream.py:164` ya usa `", ".join(item.genres)` en el campo "genre" del response
