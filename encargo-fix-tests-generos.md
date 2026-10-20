# Encargo: Fix tests fallidos tras el fix de géneros BD

## Contexto
El fix de `get_vod_streams` para leer géneros de la BD rompió 2 tests. El código funciona (verificado en contenedor), pero los tests necesitan ajuste.

## Tests fallidos

### 1. `test_enrich_genres_from_db` — IntegrityError
**Archivo:** `tests/test_xtream.py`
**Error:** `sqlite3.IntegrityError: datatype mismatch` al insertar `id='movie1'` en columna INTEGER.
**Fix:** Cambiar los IDs de los media items de test a enteros (`1`, `2`) o ajustar la fixture para que use IDs numéricos compatibles con la columna `id INTEGER PRIMARY KEY`.

### 2. `test_player_api_get_vod_streams` — `category_id == "1"`
**Archivo:** `tests/test_xtream.py` línea 406
**Error:** `assert stream1["category_id"] != "1"` falla porque en el test no hay BD poblada, `_enrich_genres_from_db` no encuentra géneros y cae al fallback `category_id = "1"`.
**Fix:** Dos opciones:
- a) Mockear `_enrich_genres_from_db` para que inyecte géneros en los items de test
- b) Cambiar la aserción a `assert stream1["category_id"]` (que exista) y verificar el nombre en vez del ID

## Límites
- NO cambiar el código de `src/api/xtream.py` — funciona correctamente
- SOLO ajustar los tests para que pasen con el nuevo comportamiento
- Mantener la verificación de que los géneros se leen de la BD cuando está poblada

## ACEPTACION
```
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/test_xtream.py::test_enrich_genres_from_db tests/test_xtream.py::test_player_api_get_vod_streams -v
```

## PREMISES
- `tests/test_xtream.py` línea ~390-410: test `test_player_api_get_vod_streams` asume `category_id != "1"`
- `tests/test_xtream.py` línea ~420-450: test `test_enrich_genres_from_db` crea items con `media_id="movie1"` (string)
- `src/api/xtream.py` línea 52-75: `_enrich_genres_from_db` lee de `data/gateway.db` y matchea por `provider_id` o `media_id`
- `src/db/models.py` columna `id` es `INTEGER PRIMARY KEY`
