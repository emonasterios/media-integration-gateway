# Encargo: stream_id estable basado en provider_id, no en posición

## Problema
`get_vod_streams` asigna `stream_id` como índice posicional (1-based) en la lista scrapeada. Como el catálogo se scrapea en vivo cada vez, el orden varía entre llamadas y el `stream_id` apunta a películas diferentes.

## Fix requerido

### 1. `get_vod_streams` — usar hash numérico del provider_id como stream_id
En `src/api/xtream.py`, función `_media_item_to_vod_stream`:
- En vez de `stream_id = 1000 + index`, usar un hash numérico estable del `provider_id`
- Ejemplo: `stream_id = int(hashlib.md5(item.provider_id.encode()).hexdigest()[:8], 16) % 100000 + 1000`
- Esto garantiza que el mismo `provider_id` siempre tenga el mismo `stream_id`

### 2. `_stream_id_to_media` — buscar por provider_id en vez de por índice
En `src/api/xtream.py`, función `_stream_id_to_media`:
- En vez de buscar por posición en la lista, construir un mapa `stream_id -> provider_id` y buscar el item por provider_id
- O: guardar el `stream_id` calculado en el item y buscar por ese valor

### 3. Mantener compatibilidad
- El `stream_id` debe seguir siendo un entero positivo
- El formato de respuesta no cambia (mismas claves)

## Límites
- NO cambiar el scraping ni el adapter
- NO cambiar la estructura de respuesta del API
- SOLO cambiar cómo se calcula y resuelve el `stream_id`

## ACEPTACION
```
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/test_xtream.py -v -k "stream_id or vod_streams or vod_info"
```

## PREMISES
- `src/api/xtream.py` línea ~190-200: `_media_item_to_vod_stream` usa `index` como stream_id
- `src/api/xtream.py` línea ~337-350: `_stream_id_to_media` busca por posición en lista
- `src/api/xtream.py` línea ~368: `resolve_playback` usa `media.provider_id` para resolver
- `src/models/catalog.py`: `MediaItem` tiene `provider_id` como identificador estable
