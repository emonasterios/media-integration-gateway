<!-- spec:08c752d1b3dd8db4a6558fef05436e6d -->
# ENCARGO: Pruebas y documentación del descubrimiento reanudable de catálogo

## ADVERTENCIA DE FONDO OBLIGATORIA (LEER ANTES DE EMPEZAR)
Bajo ninguna circunstancia se debe ejecutar el crawler contra la red real ni escribir en las rutas por defecto `data/gateway.db` ni `data/cuevana3_checkpoint.json`. Cualquier prueba que invoque `discover_resumable` o `sync_from_checkpoint` DEBE inyectar mocks para el cliente HTTP y DEBE utilizar la fixture `tmp_path` de pytest para los archivos de checkpoint y bases de datos SQLite temporales. Si se genera cualquier archivo en `data/`, la entrega quedará invalidada de inmediato.

## REGLAS GENERALES PARA EL EJECUTOR
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

---

## PASO 1: Crear la suite de pruebas unitarias para checkpoints y reconciliación segura

### Archivo a crear
- `tests/test_catalog_checkpoint.py`

### Qué debe quedar en este archivo
Crear un archivo de pruebas con `pytest` que valide exhaustivamente `src/services/catalog_checkpoint.py` y el aislamiento en `scripts/sync_catalog.py`:
1. **Guardado y carga atómicos**:
   - `test_save_and_load_checkpoint_atomic`: guardar un checkpoint con `save_checkpoint(checkpoint_path, ...)` usando `tmp_path` y verificar con `load_checkpoint` que recupera exactamente el payload, estructura, estado y lista de ítems.
2. **Preservación ante fallo de guardado atómico**:
   - `test_atomic_write_preserves_previous_file_on_error`: guardar un checkpoint válido inicial; luego simular un error (por ejemplo, excepción durante la escritura o reemplazo) y verificar que el archivo original no se corrompe ni se borra, permaneciendo legible.
3. **Deduplicación estable**:
   - `test_add_items_deduplicated_preserves_order_and_uniqueness`: verificar que `add_items_deduplicated` añade ítems nuevos respetando el orden de llegada y descarta duplicados basados en el identificador único o URL.
4. **Validación para reconciliación**:
   - `test_validate_for_reconciliation_rejects_incompatible_version`: falla si `version` != 1.
   - `test_validate_for_reconciliation_rejects_mismatched_provider`: falla si el proveedor no coincide.
   - `test_validate_for_reconciliation_rejects_mismatched_category`: falla si la categoría esperada no coincide con la del checkpoint.
   - `test_validate_for_reconciliation_rejects_incomplete_status`: lanza error o excepción al intentar validar un checkpoint cuyo `status` sea `"incomplete"`.
5. **Aislamiento de base de datos en `sync_from_checkpoint`**:
   - `test_sync_from_checkpoint_does_not_open_db_on_invalid_checkpoint`: importar `sync_from_checkpoint` de `scripts/sync_catalog.py`. Mockear `AsyncSessionLocal` en `scripts.sync_catalog`. Ejecutar la función con un checkpoint con `status="incomplete"`, corrupto o con categoría discrepante, y asertar que la validación detiene la ejecución ANTES de llamar o abrir `AsyncSessionLocal` (`AsyncSessionLocal.assert_not_called()`).

El archivo debe quedar completamente compilando y ejecutable con `pytest tests/test_catalog_checkpoint.py`.

---

## PASO 2: Añadir pruebas simuladas de `discover_resumable` en Cuevana3

### Archivos a tocar
- `tests/test_cuevana3.py`
- `src/adapters/cuevana3.py` (SOLO si se detecta un defecto menor que impida pasar los tests)

### Qué debe quedar
Leer `tests/test_cuevana3.py` y añadir al final pruebas asíncronas para `Cuevana3Adapter.discover_resumable` utilizando HTTP completamente mockeado (sin peticiones de red reales) y rutas de checkpoint en `tmp_path`:
1. `test_cuevana3_discover_resumable_more_than_20_pages_complete`:
   - Mockear respuestas HTTP para más de 20 páginas consecutivas (p. ej. 22 páginas con catálogo simulado).
   - Ejecutar `discover_resumable(checkpoint_path=..., page_limit=None)`.
   - Verificar que procesa todas las páginas, recopila todos los ítems y el checkpoint final tiene `status == "complete"` y `next_page is None`.
2. `test_cuevana3_discover_resumable_intermediate_failure_retries_and_incomplete`:
   - Mockear una falla HTTP persistente (por ejemplo, error 500 o timeout) en una página intermedia (p. ej. página 5).
   - Verificar que se agotan los 3 reintentos configurados, se captura el error y se guarda el checkpoint con `status == "incomplete"` y `next_page == 5`.
3. `test_cuevana3_discover_resumable_resume_skips_confirmed_pages`:
   - Tomar el checkpoint incompleto con `next_page == 5` y reanudar la ejecución con `discover_resumable`.
   - Verificar que NO se solicitan nuevamente las páginas 1 a 4 y que las peticiones HTTP del mock inician directamente en la página 5.
4. `test_cuevana3_discover_resumable_second_failure_preserves_checkpoint`:
   - Reanudar desde la página 5 y simular una nueva falla en la página 8.
   - Verificar que el checkpoint resultante preserva intactos todos los ítems acumulados previamente (páginas 1 a 7) y mantiene el estado `incomplete` sin corromperse.
5. `test_cuevana3_discover_resumable_deduplication_across_pages`:
   - Simular páginas que contienen películas con URLs repetidas entre páginas y a través de una reanudación.
   - Verificar que en el checkpoint final cada película aparece exactamente una vez.

Los nombres de las pruebas añadidas deben contener obligatoriamente `resumable`, `resume`, `checkpoint` o `discovery`. Toda la suite de `tests/test_cuevana3.py` debe quedar pasando sin conexiones de red.

---

## PASO 3: Actualizar la documentación operativa de sincronización de catálogo

### Archivo a tocar
- `docs/operations/catalog-sync-2026-10-21.md`

### Qué debe quedar
Leer `docs/operations/catalog-sync-2026-10-21.md` y actualizarlo con las secciones operativas del descubrimiento reanudable:
1. **Estructura y formato del checkpoint**:
   - Detallar el esquema JSON (versión 1, proveedor, categoría, timestamp, status `incomplete`/`complete`, `next_page`, lista de ítems).
2. **Ruta configurable del checkpoint**:
   - Explicar la opción para especificar rutas personalizadas de checkpoint sin depender de una ruta estática fija.
3. **Comandos de CLI en `scripts/sync_catalog.py`**:
   - `--status`: consultar el estado actual de un checkpoint sin modificar nada.
   - `--discover-only`: ejecutar únicamente el descubrimiento y actualizar el archivo de checkpoint sin escribir en la base de datos.
   - `--from-checkpoint`: reconciliar el catálogo en base de datos a partir de un checkpoint existente.
   - `--dry-run`: simular la reconciliación mostrando cambios sin persistir en la base de datos.
4. **Procedimiento de recuperación ante fallos**:
   - Pasos para reanudar un descubrimiento interrumpido reutilizando el archivo de checkpoint con `--discover-only`.
5. **Regla de integridad obligatoria**:
   - Documentar explícitamente la prohibición y el bloqueo que impiden reconciliar en base de datos snapshots con estado `incomplete`.

---

ACEPTACION
test -f tests/test_catalog_checkpoint.py
grep -q "def test_save_and_load_checkpoint_atomic" tests/test_catalog_checkpoint.py
grep -q "def test_validate_for_reconciliation_rejects_incomplete_status" tests/test_catalog_checkpoint.py
grep -q "def test_sync_from_checkpoint_does_not_open_db_on_invalid_checkpoint" tests/test_catalog_checkpoint.py
grep -q "test_cuevana3_discover_resumable" tests/test_cuevana3.py
grep -q -- "--status" docs/operations/catalog-sync-2026-10-21.md
grep -q -- "--discover-only" docs/operations/catalog-sync-2026-10-21.md
grep -q -- "--from-checkpoint" docs/operations/catalog-sync-2026-10-21.md
grep -q -- "--dry-run" docs/operations/catalog-sync-2026-10-21.md
grep -q "incomplete" docs/operations/catalog-sync-2026-10-21.md
test ! -e data/gateway.db
test ! -e data/cuevana3_checkpoint.json

PREMISES

- I1 interface — `save_checkpoint`, `load_checkpoint`, `validate_for_reconciliation` y `add_items_deduplicated` existen en el módulo nuevo — `src/services/catalog_checkpoint.py:69`, `src/services/catalog_checkpoint.py:111`, `src/services/catalog_checkpoint.py:149`, `src/services/catalog_checkpoint.py:179`.
- I2 interface — `Cuevana3Adapter.discover_resumable(checkpoint_path, category=None, page_limit=None)` existe y usa el cliente HTTP inyectable del adaptador — `src/adapters/cuevana3.py:250`, `src/adapters/cuevana3.py:339`.
- P1 precedent — el método guarda el checkpoint después de procesar cada página y antes de continuar a la siguiente — `src/adapters/cuevana3.py:405`, `src/adapters/cuevana3.py:417`, `src/adapters/cuevana3.py:429`.
- P2 precedent — `sync_from_checkpoint` carga y valida antes de abrir `AsyncSessionLocal` — `scripts/sync_catalog.py:83`, `scripts/sync_catalog.py:102`.
- L1 literal — la versión actual del formato es `CHECKPOINT_VERSION = 1` — `src/services/catalog_checkpoint.py:24`.
- P3 precedent — el test de panel ahora aísla `DB_PATH` con `temp_db_path` y restauración en `finally` — `tests/test_xtream.py:558`, `tests/test_xtream.py:577`.
- L2 literal — la suite completa local, sin los artefactos ignorados dejados por la corrida anterior, termina con 112 pruebas aprobadas — `.fabrica-verify:1`.
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
