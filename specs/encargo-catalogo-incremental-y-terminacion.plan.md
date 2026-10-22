<!-- spec:df5cc15eeafa8168eec8f6c1f179c3b4 -->
# ENCARGO: Carga incremental segura y terminación fiable del catálogo

## ADVERTENCIA DE FALLO DE FONDO (CRÍTICO)
Si el crawler se detiene por una trampa de paginación infinita, límite de páginas o caída a mitad de rastreo y el checkpoint no distingue de forma estricta entre un "final natural" (`natural_end`) y una parada artificial o incompleta (`stop_reason`), la lógica de sincronización intentará reconciliar el catálogo contra un snapshot parcial y BORRARÁ o desactivará todas las películas y fuentes no incluidas en dicho lote. Asimismo, si la persistencia de películas y el checkpoint no se confirman por página en transacciones aisladas, una caída dejará la base de datos desincronizada con el checkpoint o causará duplicados al reanudar. Esto se resuelve blindando primero el contrato del checkpoint y prohibiendo cualquier baja si el snapshot no concluyó de forma natural.

## REGLAS OBLIGATORIAS PARA EL EJECUTOR
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- Cada paso debe dejar el proyecto COMPILANDO y pasando las pruebas existentes (`pytest -q tests/test_catalog_checkpoint.py`).
- No crear `data/gateway.db` ni checkpoints persistentes fuera de directorios temporales durante las pruebas.

---

## PASO 1: Blindaje del modelo de Checkpoint, estados de parada y compatibilidad v1
**Archivo a modificar:** `src/services/catalog_checkpoint.py`

1. Leer `src/services/catalog_checkpoint.py`.
2. Ampliar la estructura de datos del checkpoint (ej. `CatalogCheckpoint` o `dict` serializado) para incorporar:
   - Campo `stop_reason`: valores admitidos como `None`, `"natural_end"`, `"repeated_page"`, `"no_new_items"`, `"max_pages"`, `"interrupted"`.
   - Campo `version`: valor entero por defecto `2` (o mantener retrocompatibilidad explícita cargando checkpoints v1 sin este campo y asignándoles `version=1`, `stop_reason=None`).
3. Modificar la función de validación de reconciliación de bajas (`can_reconcile_removals` o equivalente en líneas 149-175):
   - Exigir estrictamente que `checkpoint.status == "complete"` Y `checkpoint.stop_reason == "natural_end"`.
   - Si `stop_reason` es `"max_pages"`, `"repeated_page"`, `"no_new_items"` o el estado es `"incomplete"`, devolver `False` categóricamente, bloqueando cualquier borrado o retiro.
4. Asegurar que `load_checkpoint` pueda deserializar un checkpoint versión 1 antiguo sin error, preservando todos sus campos (`provider`, `category`, `pages_visited`, `items`).
5. Mantener el proyecto compilando y verificar ejecutando `pytest -q tests/test_catalog_checkpoint.py`.

---

## PASO 2: Normalización de títulos y detección de paginación infinita en el adapter
**Archivo a modificar:** `src/adapters/cuevana3.py`

1. Leer `src/adapters/cuevana3.py` en las secciones de parseo de items (`_parse_movie_item` / `_parse_catalog_page`) y el bucle de descubrimiento (`discover_movies` / `crawl_catalog`).
2. Implementar la normalización de títulos:
   - Al extraer el título y el año (`item.year`), si el título en texto plano comienza con el mismo año (ejemplo con regex `rf"^{item.year}\s*(.+)$"` convirtiendo `"2018Aquaman"` en `"Aquaman"`), limpiar y asignar el título normalizado.
   - Si el prefijo numérico no coincide con `item.year`, NO recortar el título.
3. Incorporar en el bucle de descubrimiento (`discover_movies`) las heurísticas de detección de terminación artificial:
   - **Huella de página repetida:** calcular un hash o tupla ordenada de IDs `(provider, provider_id)` de la página actual; si el conjunto de identidades ya fue visitado en esa misma corrida, detener el rastreo asignando `stop_reason = "repeated_page"` y `status = "incomplete"`.
   - **Páginas consecutivas sin novedades:** mantener un contador de páginas seguidas donde ningún `provider_id` sea nuevo. Si alcanza el umbral configurable (por defecto 3 páginas sin nuevos ítems), detener el rastreo con `stop_reason = "no_new_items"` y `status = "incomplete"`.
   - **Fusible de páginas máximas:** si se alcanza `max_pages`, detener con `stop_reason = "max_pages"` y `status = "incomplete"`.
   - **Fin natural:** únicamente si el selector del enlace siguiente (`next`) no existe en el DOM, marcar `stop_reason = "natural_end"` y `status = "complete"`.
4. Permitir un callback opcional en `discover_movies` (por ejemplo `on_page: Optional[Callable[[list[CatalogMovie], CatalogCheckpoint], Awaitable[None]]] = None`) para notificar a quien invoca tras procesar y validar cada página.
5. Comprobar que los tests existentes de Cuevana3 siguen pasando.

---

## PASO 3: Upserts idempotentes por página y checkpoint transaccional en sincronización
**Archivo a modificar:** `scripts/sync_catalog.py`

1. Leer `scripts/sync_catalog.py`.
2. Extraer la lógica de persistencia para que opere por lote de página:
   - Definir una función o manejador asíncrono `persist_page_batch(session_factory, movies: list[CatalogMovie], checkpoint: CatalogCheckpoint, checkpoint_path: Path)` que:
     - Abra una sesión/transacción de BD acotada.
     - Ejecute upsert idempotente para cada película buscando por `(provider, provider_id)`. Si existe, actualiza campos modificados; si no existe, inserta `Media` y `Source`.
     - Confirme (`commit`) la transacción de BD.
     - Inmediatamente guarde el checkpoint actualizado en disco de forma atómica.
3. Conectar dicho manejador al callback de página de `discover_movies` del adapter Cuevana3.
4. Aislar estrictamente la reconciliación de bajas y limpieza de huérfanos:
   - Si `checkpoint.status != "complete"` o `checkpoint.stop_reason != "natural_end"`, omitir completamente la fase de bajas y huérfanos, emitiendo un log explicativo (ej. `"Snapshot incompleto o parada por heurística/límite (razón: {stop_reason}). Bajas deshabilitadas."`).
5. Añadir opción `--status` en el CLI de `sync_catalog.py`:
   - Al invocar `python scripts/sync_catalog.py --status`, leer exclusivamente el archivo de checkpoint en disco (sin abrir conexiones innecesarias a la BD) e imprimir: estado, páginas visitadas, total de ítems acumulados, `stop_reason` y timestamp.
6. Verificar que `python scripts/sync_catalog.py --help` compila y funciona.

---

## PASO 4: Pruebas unitarias de Checkpoint y detección de terminación
**Archivo a modificar:** `tests/test_catalog_checkpoint.py`

1. Leer `tests/test_catalog_checkpoint.py`.
2. Añadir casos de prueba focalizados sin tocar red real ni base de datos persistente:
   - Cargar un checkpoint formato v1 (sin `version` ni `stop_reason`) y comprobar que se carga con éxito sin perder páginas ni ítems.
   - Probar que `can_reconcile_removals` devuelve `True` únicamente cuando `status == "complete"` y `stop_reason == "natural_end"`.
   - Probar que `can_reconcile_removals` devuelve `False` para `stop_reason` en `["repeated_page", "no_new_items", "max_pages", "interrupted"]` y cuando `status == "incomplete"`.
   - Comprobar que la serialización y guardado del checkpoint persiste los campos `version` y `stop_reason`.
3. Ejecutar `pytest -q tests/test_catalog_checkpoint.py` y comprobar que todas las pruebas pasen en verde.

---

## PASO 5: Suite de pruebas de sincronización incremental e idempotencia
**Archivo a crear:** `tests/test_catalog_sync.py`

1. Crear `tests/test_catalog_sync.py` utilizando `pytest`, `pytest_asyncio` y fixtures de SQLite en memoria o archivos en `tmp_path` (asegurando no tocar `data/gateway.db`).
2. Implementar los siguientes casos de prueba:
   - `test_incremental_upsert_per_page`: Simular 2 páginas de catálogo; verificar que tras la página 1 las películas ya están confirmadas en la BD antes de procesar la página 2.
   - `test_resume_and_replay_idempotency`: Repetir la carga de una misma página o reanudar tras parada y verificar que no se duplican registros en `Media` ni `Source`.
   - `test_title_normalization`: Verificar que un ítem con año 2018 y título `"2018Aquaman"` se persiste como `"Aquaman"`, mientras que `"2020Aquaman"` con año 2018 no se altera.
   - `test_stop_conditions`: Simular respuestas del crawler para página repetida, N páginas sin novedades y límite `max_pages`, verificando que el crawler se detiene con el `stop_reason` correspondiente y jamás marca apto para bajas.
   - `test_clean_environment`: Asegurar que el test no deja archivos `data/gateway.db` ni checkpoints en el directorio de trabajo.
3. Ejecutar `pytest -q tests/test_catalog_sync.py` y verificar que pase al 100%.

---

## PASO 6: Documentación operativa del flujo de sincronización y checkpoints
**Archivo a crear:** `docs/operations/catalog-sync-2026-10-21.md`

1. Redactar `docs/operations/catalog-sync-2026-10-21.md` documentando:
   - La arquitectura de carga incremental página a página (upsert atómico por página).
   - Heurísticas de parada deterministas contra paginación infinita (`repeated_page`, `no_new_items`, `max_pages`, `natural_end`).
   - Política de protección contra bajas involuntarias: por qué solo `natural_end` permite reconciliación y eliminación de huérfanos.
   - Comandos de CLI para ejecutar la sincronización y consultar `--status`.
   - Procedimiento de reanudación transparente desde checkpoints previos (v1 y v2).

---

ACEPTACION
grep -q "stop_reason" src/services/catalog_checkpoint.py
grep -q "stop_reason" src/adapters/cuevana3.py
grep -q "persist_page_batch" scripts/sync_catalog.py || grep -q "on_page" scripts/sync_catalog.py
test -f tests/test_catalog_sync.py
grep -q "test_incremental_upsert_per_page" tests/test_catalog_sync.py
grep -q "test_stop_conditions" tests/test_catalog_sync.py
test -f docs/operations/catalog-sync-2026-10-21.md
. .venv/bin/activate && pytest -q tests/test_catalog_checkpoint.py tests/test_catalog_sync.py
. .venv/bin/activate && pytest -q
test ! -e data/gateway.db
git diff --exit-code -- src/api src/services/video_resolver.py src/services/mediaflow_bridge.py

PREMISES

- `src/adapters/cuevana3.py:251-268` define el descubrimiento reanudable y checkpoint por página.
- `src/adapters/cuevana3.py:325-345` controla el bucle, límite y páginas visitadas solo dentro de una ejecución.
- `src/adapters/cuevana3.py:418-445` deduplica, avanza el checkpoint y confía en el enlace `next` para terminar.
- `scripts/sync_catalog.py:68-109` exige checkpoint completo para reconciliar y deshabilita bajas solo cuando hay `--limit`.
- `scripts/sync_catalog.py:113-189` mezcla upserts, bajas y limpieza de huérfanos en una sola transacción.
- `src/services/catalog_checkpoint.py:45-66` conserva proveedor, categoría, páginas, ítems y estado del checkpoint.
- `src/services/catalog_checkpoint.py:149-175` prohíbe reconciliar snapshots incompletos y valida proveedor/categoría.
- `src/services/catalog_checkpoint.py:179-196` deduplica por `(provider, provider_id)`.
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
