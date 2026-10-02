# Fase 4a: Endpoint M3U para IPTV

## Qué hacer
1. Crear `src/api/m3u.py` — endpoint `GET /playlist.m3u` que genera playlist M3U desde el catálogo cacheado
2. Registrar router en `src/main.py`
3. Tests en `tests/test_m3u.py`

## Formato M3U
```
#EXTM3U
#EXTINF:-1 group-title="Peliculas",Signal One (2026)
http://localhost:8000/api/v1/resolve/cuevana3/signal-one
```

## Límites
- NO modificar adapters, cache, ni tests existentes
- Usar items cacheados, NO scrapear en cada request

## ACEPTACION
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v

## PREMISES
- src/main.py crea la app con create_app() e incluye router de src/api/routes.py (prefijo /api/v1)
- src/api/routes.py tiene endpoints: /search, /catalog/{provider}, /details/{provider}/{media_id}, /seasons, /episodes, /playback/resolve/{provider}/{media_id}, /providers
- src/services/cache.py tiene CatalogCache con métodos populate(), get_cached_catalog(), get_cached_item()
- src/models/catalog.py tiene MediaItem con campos: media_id, title, media_type, year, poster_url, overview, provider, provider_id
- src/services/catalog.py tiene CatalogService con search(), get_catalog(), get_details(), get_seasons(), get_episodes(), resolve_playback()
- 57 tests pasando actualmente en main
- El endpoint de resolución es POST /api/v1/playback/resolve/{provider}/{media_id} (no GET)
