# Fix: stream_movie lee de BD, no de scraping

## PROBLEMA
`stream_movie` (src/api/xtream.py línea ~409) usa `catalog_service.get_catalog("cuevana3")` que scrapea en vivo. El stream_id generado por `get_vod_streams` (que lee de BD) no coincide con el catálogo scrapeado → reproduce la película equivocada.

## QUÉ HACER
En `src/api/xtream.py`, función `stream_movie`:

**ANTES (línea ~409-411):**
```python
    catalog = await catalog_service.get_catalog("cuevana3")
    catalog2 = await catalog_service.get_catalog("cuevan_net")
    media = _stream_id_to_media(stream_id, "movie", catalog + catalog2)
```

**DESPUÉS:**
```python
    all_movies = await _load_catalog_from_db()
    media = _stream_id_to_media(stream_id, "movie", all_movies)
```

## QUÉ NO TOCAR
- NO tocar `get_series` ni `get_live_streams`
- NO tocar `resolve_playback`
- NO tocar tests
- NO tocar `_stream_id_to_media`
- NO tocar `stream_series` ni `stream_live`

## ACEPTACIÓN
- `cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v` → 20 passing
- `grep 'catalog_service.get_catalog' src/api/xtream.py` → SOLO aparece en get_series y get_live_streams (NO en stream_movie)

## PREMISES
- src/api/xtream.py:409-411 — stream_movie usa catalog_service.get_catalog("cuevana3")
- src/api/xtream.py:21 — _load_catalog_from_db() existe y lee de data/gateway.db
- src/api/xtream.py:380 — _stream_id_to_media() funciona con list[MediaItem]
- tests/test_xtream.py — 20 tests pasando actualmente
