<!-- spec:ba5f32b6b88e7c33c58b019db0d35703 -->
REGLAS PARA EL EJECUTOR:
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

ADVERTENCIA DE FONDO:
Actualmente, peticiones públicas de catálogo, búsqueda y conteo disparan llamadas a `provider.get_catalog()` o `provider.search()` cuando la memoria o la BD no tienen datos, realizando scraping en vivo y bloqueando la API. Además, si el proveedor falla o está vacío, una petición pública de lectura reventaría o se demoraría por la red. La lectura pública debe desacoplarse por completo del scraping: debe consultar exclusivamente el snapshot SQLite local o la caché en memoria, y si no hay resultados, devolver una lista vacía sin intentar rastreo de red.

## PASO 1: Desacoplar lecturas y búsquedas de red en el servicio de catálogo
- Archivo a modificar: `src/services/catalog.py`
- Objetivo:
  1. En `CatalogService.get_catalog(self, category=None)`: comprobar si hay caché o consultar la base de datos SQLite (vía sesión de base de datos y modelos `Media`/`Source` o mapeo a `MediaItem`). Si la consulta no devuelve elementos, retornar lista vacía `[]`. ELIMINAR cualquier invocación a `provider.get_catalog(...)` en las rutas de lectura estándar.
  2. En `CatalogService.search(self, query, media_type=None)`: filtrar sobre los elementos del snapshot de la base de datos o de la caché local en memoria. ELIMINAR el fallback a `provider.search(query)` o llamadas de red cuando no haya coincidencias.
  3. Mantener compatibilidad con tests unitarios que inyectan catálogos en memoria sin base de datos activa.
- Lo que debe quedar: `CatalogService` atiende lecturas y búsquedas exclusivamente desde snapshot local (BD/memoria) sin iniciar rastreos de red ni scraping del proveedor.

## PASO 2: Eliminar llamadas a get_catalog y conectar búsquedas y conteos a la BD en Xtream
- Archivo a modificar: `src/api/xtream.py`
- Objetivo:
  1. Localizar todas las apariciones de `catalog_service.get_catalog(` en `src/api/xtream.py` y eliminarlas por completo.
  2. En `search_vod` y `search_series`: sustituir la llamada a `catalog_service.search()` por consulta directa sobre `_load_catalog_from_db()` filtrando por término de búsqueda y tipo de contenido (`movie` o `series`).
  3. En `panel_api.php`: sustituir las dos llamadas a `catalog_service.get_catalog()` para conteos de películas y series por lecturas de `_load_catalog_from_db()`.
  4. En la búsqueda y selección previa de serie en `/series/...` (líneas 512-529): sustituir las llamadas a `catalog_service.get_catalog()` por búsqueda sobre `_load_catalog_from_db()`.
- Lo que debe quedar: Ninguna ocurrencia de `catalog_service.get_catalog(` en `src/api/xtream.py`. Todas las rutas de Xtream (series, VOD, búsquedas, conteos y selección de serie) consultan exclusivamente el snapshot SQLite.

## PASO 3: Asegurar que los endpoints públicos de la API REST no rastreen la red
- Archivo a modificar: `src/api/routes.py`
- Objetivo:
  1. Revisar los endpoints `/api/v1/catalog/{provider}` y `/api/v1/search`.
  2. Garantizar que usen `catalog_service.get_catalog(...)` y `catalog_service.search(...)` adaptados en el PASO 1, consumiendo el snapshot de base de datos sin disparar sincronización de red.
  3. Si la base de datos está vacía o el término no coincide, devolver respuesta vacía (o 200 con lista vacía) sin invocar métodos del adaptador que hagan peticiones HTTP externas.
- Lo que debe quedar: Los endpoints `/api/v1/catalog/{provider}` y `/api/v1/search` responden de forma rápida y desacoplada leyendo únicamente el snapshot local.

## PASO 4: Pruebas de regresión contra llamadas de red en catálogo y Xtream
- Archivos a modificar: `tests/test_xtream.py`, `tests/test_smoke.py`
- Objetivo:
  1. En `tests/test_xtream.py`: añadir pruebas que aseguren que `search_vod`, `search_series`, `panel_api.php` y los endpoints de series obtienen sus datos de la base de datos temporal SQLite y que fallarían si se intentara llamar a `provider.get_catalog()`.
  2. En `tests/test_smoke.py`: añadir aserciones para verificar que `/api/v1/catalog/{provider}` y `/api/v1/search` no llaman a la red ni a `provider.get_catalog()`.
  3. Asegurar que toda la suite de pruebas pase en verde.
- Lo que debe quedar: Pruebas unitarias y de regresión verificando que ninguna lectura pública ejecuta scraping o rastreo de catálogo.

ACEPTACION
test -f src/services/catalog.py
test -f src/api/xtream.py
test -f src/api/routes.py
test -f tests/test_xtream.py
test -f tests/test_smoke.py
! grep -F 'catalog_service.get_catalog(' src/api/xtream.py
.venv/bin/python -m pytest tests/test_xtream.py tests/test_smoke.py -q
.venv/bin/python -m pytest tests/ -q

PREMISES

- `src/services/catalog.py:131-157` implementa `search()` mediante `self.get_catalog()` y hasta hace fallback al adapter, por lo que una petición pública puede acceder a red.
- `src/services/catalog.py:184-204` implementa `get_catalog()` llamando directamente a `provider.get_catalog(category)` cuando no hay caché de memoria.
- `src/api/routes.py:30-52` conecta `/api/v1/search` y `/api/v1/catalog/{provider}` con esos métodos del servicio.
- `src/api/xtream.py:313-315` demuestra el patrón ya aceptado: `get_series` lee `_load_catalog_from_db()`.
- `src/api/xtream.py:340-360` aún enruta `search_vod` y `search_series` a `catalog_service.search()`.
- `src/api/xtream.py:367-381` aún construye los conteos de `panel_api.php` llamando dos veces a `catalog_service.get_catalog()`.
- `src/api/xtream.py:512-529` aún localiza una serie mediante dos llamadas a `catalog_service.get_catalog()` antes del playback.
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
