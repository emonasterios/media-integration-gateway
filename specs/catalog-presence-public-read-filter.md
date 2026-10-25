# ENCARGO: Excluir fuentes ausentes de todas las lecturas públicas del catálogo

## Objetivo

Aplicar el estado persistente `Source.catalog_presence` a las superficies públicas del gateway. Una fuente con `catalog_presence="missing"` debe permanecer físicamente en SQLite para reconciliación e historial, pero no debe anunciarse, buscarse, detallarse ni reproducirse como disponible.

## Alcance obligatorio

1. Corregir las consultas públicas de Xtream en `src/api/xtream.py`:
   - `_load_catalog_from_db` solo devuelve medios que tengan una fuente `cuevana3` con `catalog_presence='present'`.
   - `_load_single_movie_from_db` devuelve `None` si la película no tiene una fuente `cuevana3` presente; queda cubierto tanto `get_vod_info` como `/movie/...`.
   - `get_vod_categories` no deriva categorías de películas cuya fuente esté ausente.
   - No usar el ID interno de `media` como `provider_id` para simular disponibilidad cuando no existe una fuente presente.
   - Evitar duplicados si un medio tiene más de una fuente.
2. Corregir `src/api/m3u.py`:
   - La playlist solo incluye medios con al menos una fuente presente.
   - El `provider` y `provider_id` publicados deben provenir de una fuente presente, nunca de la primera fuente ausente cargada por la relación.
3. Corregir `src/services/catalog.py`:
   - `_load_catalog_from_db` filtra `Source.catalog_presence == "present"` para el proveedor solicitado.
   - `_convert_db_media_to_item` elige exclusivamente una fuente presente del proveedor solicitado. Si no existe, devuelve `None`; no debe caer a otra fuente ni al ID interno.
4. Corregir `src/services/cache.py`:
   - `get_by_source` no devuelve medios cuyo `provider/url` corresponda a una fuente `missing`.
   - No cambiar la reconciliación ni borrar físicamente filas.
5. Añadir regresiones focalizadas en los archivos de prueba existentes, al menos para:
   - listado Xtream, búsqueda, detalle y endpoint de reproducción;
   - conteo de panel y categorías VOD;
   - playlist M3U;
   - catálogo de `CatalogService` y `CatalogCache.get_by_source`.
   Cada prueba debe sembrar al menos una fuente `present` y una `missing`, y demostrar que la presente sigue visible mientras la ausente no se expone.

## Límites

- Tocar únicamente `src/api/xtream.py`, `src/api/m3u.py`, `src/services/catalog.py`, `src/services/cache.py` y sus pruebas directamente relacionadas.
- No modificar modelos, migraciones, sincronización, adapters, resolvers, despliegue ni bases reales.
- No depender de red.
- Preservar compatibilidad con esquemas de prueba/legado que ya incluyan la migración vigente; no ocultar errores de esquema mediante excepciones amplias nuevas.
- Mantener el snapshot SQLite como fuente de lectura; no reintroducir rastreo de red.

## Resultado esperado

Después del cambio, `missing` significa conservado pero no publicable. `present` continúa funcionando en Xtream, M3U, búsqueda, detalle, panel y reproducción. La suite completa queda verde.

ACEPTACION
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_xtream.py tests/test_m3u.py tests/test_cache.py tests/test_smoke.py
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q
! rg -n 'LEFT JOIN sources s ON s.media_id = m.id AND s.provider = .cuevana3.' src/api/xtream.py
rg -n 'catalog_presence' src/api/xtream.py src/api/m3u.py src/services/catalog.py src/services/cache.py

PREMISES
- `src/api/xtream.py:31-39` lista el catálogo con `LEFT JOIN sources` y sin filtrar `catalog_presence`, por lo que una fuente ausente sigue publicada.
- `src/api/xtream.py:97-104` carga detalle/reproducción por PK sin exigir una fuente presente.
- `src/api/m3u.py:64-82` selecciona todos los medios y acepta cualquier primera fuente cargada.
- `src/services/catalog.py:164-169` filtra por proveedor pero no por presencia.
- `src/services/catalog.py:106-125` cae a otra fuente o al ID interno si no encuentra la fuente solicitada.
- `src/services/cache.py:51-60` resuelve por provider/url sin filtrar presencia.
- `src/db/models.py:46` declara `catalog_presence` no nulo con valor predeterminado `present`.
