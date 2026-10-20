# Encargo: Poblar más items y verificar filtro por género en Xtream

## Contexto
La BD tiene 50 items (42 pelis, 8 series) con géneros reales. El catálogo completo tiene 1500 items. Los endpoints Xtream en `src/api/xtream.py` ya soportan `get_vod_categories` (lee géneros de la BD) y `get_vod_streams` con filtro por `category_id`.

## Qué hacer
1. Ejecutar `python scripts/populate_catalog.py --limit 200 --delay 0.5` para poblar más items
2. Ejecutar `python scripts/enrich_genres.py` para asegurar géneros en los nuevos items
3. Verificar que `get_vod_categories` devuelve categorías reales desde la BD
4. Verificar que `get_vod_streams?category_id=N` filtra correctamente

## ACEPTACION
python scripts/populate_catalog.py --limit 200 --delay 0.5
python scripts/enrich_genres.py
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v

## PREMISES
src/api/xtream.py:149-157 lee géneros de la BD con SELECT DISTINCT genres FROM media
src/api/xtream.py:193-201 filtra por category_id en get_vod_streams
src/adapters/cuevana3.py:get_catalog devuelve 1500 items con géneros
scripts/populate_catalog.py existe y funciona (ya pobló 50 items)
scripts/enrich_genres.py existe y funciona
94 tests passing
