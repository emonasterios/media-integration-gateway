<!-- spec:adef235a7c1ef0fb6dc62426caf5770d -->
# ENCARGO: Reconciliar ausencias sin borrado físico en reconciliación de catálogo — unidad 2B.1

## Reglas obligatorias para el ejecutor
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- No modificar modelos, migraciones, adapters, API, resolvers, reproducción ni despliegue. Limitar los cambios estrictamente a `scripts/sync_catalog.py` y `tests/test_catalog_sync.py`.
- No borrar físicamente ninguna fila de `sources` ni de `media` durante la reconciliación.

---

## PASO 1: Reemplazar el borrado físico por marcado persistente de ausencia en scripts/sync_catalog.py

**Archivo a modificar:** `scripts/sync_catalog.py`

**Instrucciones:**
1. Leer `scripts/sync_catalog.py` prestando atención a la función `sync_from_checkpoint` (sección entre líneas 280 y 385 aproximadamente, donde se identifican `missing_ids` y se ejecutan las bajas).
2. Mantener intactas las validaciones previas a la reconciliación de ausencias:
   - Solo se reconcilian ausencias si el checkpoint es completo y `stop_reason == "natural_end"`.
   - Si se ejecuta con `--limit`, las ausencias quedan deshabilitadas (`delete_enabled = False` o equivalente).
   - Mantener el control de cambio masivo: si el porcentaje de ausencias supera el 25% del total de fuentes activas del proveedor y no se pasa `allow_large_delete=True`, abortar con el mismo error existente, antes de marcar ausencias.
3. Eliminar por completo el borrado físico:
   - Eliminar las llamadas `await db.delete(source)` y `await db.delete(media)`.
   - Eliminar la lógica de limpieza de fuentes huérfanas (`orphan_sources` / borrado de huérfanos).
   - No introducir borrados en cascada ni sentencias SQL DELETE directas.
4. En lugar de borrar las fuentes ausentes, iterar sobre cada `Source` ausente (`missing_ids`):
   - Establecer `source.catalog_presence = "missing"`.
   - Si `source.missing_since is None`, asignar `source.missing_since = observed_at` (si ya tenía valor, preservarlo para mantener la fecha original de la primera ausencia).
   - Incrementar `source.consecutive_misses = (source.consecutive_misses or 0) + 1`.
   - Mantener intactos `source.last_seen_at` y `source.last_seen_run_id` (representan la última observación positiva).
5. Mantener intacto el flujo de fuentes presentes ya existente (donde se establece `catalog_presence = "present"`, `missing_since = None`, `consecutive_misses = 0`, y se actualizan `last_seen_at` y `last_seen_run_id`).
6. En las variables de conteo y el resumen impreso final:
   - Reemplazar nombres de contadores de borrado (`sources_deleted`, `media_deleted`) por `sources_marked_missing`.
   - En el mensaje de resumen por consola, reportar "fuentes marcadas ausentes" (no hablar de fuentes ni medios borrados o retirados; no usar el estado `retired`).
7. Comprobar que el archivo compila sin errores:
   `python3 -m py_compile scripts/sync_catalog.py`

---

## PASO 2: Actualizar y ampliar pruebas unitarias en tests/test_catalog_sync.py

**Archivo a modificar:** `tests/test_catalog_sync.py`

**Instrucciones:**
1. Leer `tests/test_catalog_sync.py` para identificar las pruebas existentes de `sync_from_checkpoint` que verifiquen borrados físicos de `Source` o `Media`.
2. Actualizar las pruebas existentes que esperaban borrado de filas:
   - Reemplazar aserciones que comprobaban que la fuente o el medio desaparecían (`session.get(...) is None`) por aserciones que demuestren que permanecen en la base de datos, pero la fuente tiene `catalog_presence == "missing"`.
3. Añadir pruebas de regresión focalizadas (usando la base SQLite temporal / fixtures existentes sin llamadas de red):
   - **Caso 1 (Marcado de ausencia inicial y preservación de registros):** Un snapshot completo con `stop_reason="natural_end"` omite una fuente existente. Verificar que la fuente NO se borra, su `Media` NO se borra, `source.catalog_presence == "missing"`, `source.missing_since` se establece con la fecha de la ejecución y `source.consecutive_misses == 1`.
   - **Caso 2 (Ausencias sucesivas preservan timestamp original):** Una segunda sincronización completa que vuelve a omitir la fuente incrementa `source.consecutive_misses` a 2, pero conserva intactos `source.missing_since` original, `source.last_seen_at` y `source.last_seen_run_id`.
   - **Caso 3 (Ejecución con limit no marca ausencias):** Ejecutar `sync_from_checkpoint` con `limit` (o `delete_enabled=False`). Verificar que una fuente omitida conserva su estado previo (`catalog_presence == "present"` y no pasa a `"missing"`).
   - **Caso 4 (Dry-run revierte el marcado):** Ejecutar con `dry_run=True`. Verificar que la transacción hace rollback y la fuente no queda persistida como `"missing"`.
   - **Caso 5 (Checkpoint no apto no altera ausencias):** Con un checkpoint incompleto o con `stop_reason != "natural_end"`, verificar que no se marcan ausencias.
   - **Caso 6 (Protección de cambio masivo):** Si más del 25% de fuentes resultan ausentes y `allow_large_delete=False`, la función falla/aborta antes de modificar o marcar filas, y ninguna fila es borrada.
4. Ejecutar la suite de pruebas para confirmar que todo pasa en verde:
   `. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_catalog_sync.py`

---

ACEPTACION
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_catalog_sync.py
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q
! grep -q 'await db.delete' scripts/sync_catalog.py
grep -q 'catalog_presence = "missing"' scripts/sync_catalog.py
grep -q 'missing_since' scripts/sync_catalog.py
grep -q 'consecutive_misses' scripts/sync_catalog.py
git diff --exit-code c0a9acc -- src/db src/adapters src/api src/services alembic

PREMISES

- `Source` ya contiene `catalog_presence`, `last_seen_at`, `last_seen_run_id`, `missing_since`
  y `consecutive_misses` — `src/db/models.py:47-52`.
- Las observaciones positivas ya restablecen `present`, limpian ausencia y registran última
  observación en ambos flujos — `scripts/sync_catalog.py:148-173` y
  `scripts/sync_catalog.py:315-325`.
- La implementación actual calcula `missing_ids`, aplica el umbral masivo y luego borra
  físicamente `Source` y eventualmente `Media` — `scripts/sync_catalog.py:293-368`.
- La implementación actual también borra físicamente fuentes huérfanas en esa misma fase —
  `scripts/sync_catalog.py:371-378`.
- `limit` deja `delete_enabled=False`, el checkpoint se valida antes de abrir la BD y
  `dry_run` termina con rollback — `scripts/sync_catalog.py:245-276` y
  `scripts/sync_catalog.py:401-405`.
- El commit base verificado de este worktree es `c0a9acc`, con la observación positiva ya
  integrada y sin cambios locales.
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
