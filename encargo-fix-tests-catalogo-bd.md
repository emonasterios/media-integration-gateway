# Encargo: Arreglar tests tras migrar catálogo a BD

## Contexto
El encargo anterior (`catalogo-desde-bd`) reemplazó `catalog_service.get_catalog()` por `_load_catalog_from_db()` que lee de `data/gateway.db`. El cambio es correcto para producción, pero rompió 3 tests porque en tests la BD no existe.

## Problema
3 tests fallan:
1. `test_player_api_get_vod_streams` → `assert 0 == 3` (BD vacía → 0 streams)
2. `test_player_api_get_vod_streams_filtered_by_category` → `assert 0 == 2` (mismo problema)
3. `test_player_api_get_vod_info` → `KeyError: 'info'` (BD vacía → retorna `{}`)

## Solución
Modificar `_load_catalog_from_db()` en `src/api/xtream.py` para que acepte un parámetro `fallback` opcional:

```python
async def _load_catalog_from_db(fallback: list[MediaItem] | None = None) -> list[MediaItem]:
    """Carga el catálogo desde SQLite, con fallback si la BD no existe."""
    if not DB_PATH.exists():
        return fallback or []
    # ... resto del código igual ...
```

Y en los endpoints, pasar el catálogo del `catalog_service` como fallback:

```python
# En get_vod_streams (línea ~234):
fallback_movies = [m for m in (await catalog_service.get_catalog("cuevana3")) if m.media_type == MediaType.MOVIE]
unique_movies = await _load_catalog_from_db(fallback=fallback_movies)

# En get_vod_info (línea ~258):
fallback_movies = [m for m in (await catalog_service.get_catalog("cuevana3")) if m.media_type == MediaType.MOVIE]
all_movies = await _load_catalog_from_db(fallback=fallback_movies)
```

## NO tocar
- No cambiar la lógica de `_media_item_to_vod_stream`
- No cambiar `_stream_id_to_media`
- No cambiar `get_vod_categories` (ya funciona con BD + fallback)
- No cambiar `get_series`, `get_live_streams`
- No cambiar tests (los tests están bien, el código debe adaptarse)

## Verificación
```bash
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/test_xtream.py::test_player_api_get_vod_streams tests/test_xtream.py::test_player_api_get_vod_streams_filtered_by_category tests/test_xtream.py::test_player_api_get_vod_info -v
```

Todos deben pasar.

## ACEPTACION
```
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/test_xtream.py::test_player_api_get_vod_streams tests/test_xtream.py::test_player_api_get_vod_streams_filtered_by_category tests/test_xtream.py::test_player_api_get_vod_info -v
```

## PREMISES
- src/api/xtream.py:15-42 — `_load_catalog_from_db()` actual, lee de DB_PATH, retorna [] si no existe
- src/api/xtream.py:234 — `get_vod_streams` llama a `_load_catalog_from_db()` sin fallback
- src/api/xtream.py:258 — `get_vod_info` llama a `_load_catalog_from_db()` sin fallback
- tests/test_xtream.py:45-79 — `FakeCuevana3Provider.get_catalog()` devuelve 2 películas + 1 serie
- tests/test_xtream.py:416 — test espera `len(data) == 3`
- tests/test_xtream.py:442 — test espera `len(data) == 2` para category_id=1
- tests/test_xtream.py:461 — test espera `data["info"]["name"] == "Película Test 1"`
