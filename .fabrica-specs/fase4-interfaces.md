# Fase 4: Interfaces de salida — M3U + Web UI + Xtream API

## Qué hacer
1. Crear `src/api/m3u.py` — endpoint `GET /playlist.m3u` que genera playlist M3U desde el catálogo cacheado
2. Crear `src/api/xtream.py` — endpoints compatibles con Xtream Codes API:
   - `GET /player_api.php` (auth + info)
   - `GET /panel_api.php` (series/movies listing)
   - `GET /live/tv` (placeholder para futuro)
3. Crear `src/web/templates/` + `src/web/static/` — Web UI mínima con Jinja2:
   - Página principal con buscador
   - Vista de detalles de película/serie
   - Botón "Agregar a favoritos"
4. Registrar routers en `src/main.py`
5. Tests en `tests/test_m3u.py`, `tests/test_xtream.py`, `tests/test_web.py`

## Límites
- NO modificar `src/adapters/` ni `src/services/cache.py`
- NO modificar tests existentes
- Usar Jinja2 para templates (ya es dependencia de FastAPI)
- M3U debe usar items cacheados, NO scrapear en cada request

## Formato M3U esperado
```
#EXTM3U
#EXTINF:-1 group-title="Peliculas",Signal One (2026)
http://localhost:8000/api/v1/resolve/cuevana3/signal-one
```

## ACEPTACION
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v

## PREMISES
- src/main.py ya registra routers de api/v1
- src/services/cache.py tiene catálogo cacheado
- src/models/catalog.py tiene MediaItem con title, url, poster, type
- 57 tests pasando actualmente
