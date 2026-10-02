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
- src/main.py ya registra routers de api/v1
- src/services/cache.py tiene catálogo cacheado
- src/models/catalog.py tiene MediaItem con title, url, poster, type
- 57 tests pasando actualmente
