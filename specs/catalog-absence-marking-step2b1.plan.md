<!-- spec:db462881fa01ec0685da678b746a6aef -->
# ENCARGO: Reconciliar ausencias sin borrado físico en el catálogo (Unidad 2B.1)

## Reglas obligatorias para el ejecutor
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- No modificar archivos fuera de `scripts/sync_catalog.py` y `tests/test_catalog_sync.py`.
- No ejecutar sincronizaciones reales contra producción ni tocar bases de datos reales.
- El proyecto debe quedar en estado compilable y pasando pruebas tras cada paso.

---

## PASO 1: Sustituir el borrado físico por marcado persistente de ausencia en el reconciliador de catálogo

### Archivo a modificar
- `scripts/sync_catalog.py`

### Instrucciones
1. Leer `scripts/sync_catalog.py` prestando atención a la función `sync_from_checkpoint` y su bloque de reconciliación de bajas (aproximadamente líneas 290 a 380).
2. Identificar el punto donde se computa `missing_ids` y la validación del umbral de seguridad por borrado masivo (`allow_large_delete`). Mantener intacto el cálculo de porcentaje y la excepción si se supera el 25% sin `allow_large_delete=True`.
3. Eliminar por completo el borrado físico de la base de datos:
   - Eliminar todas las llamadas `await db.delete(source)`.
   - Eliminar todas las llamadas `await db.delete(media)`.
   - Eliminar el bloque de limpieza de fuentes huérfanas que hacía `await db.delete(...)`.
   - Asegurarse de que no quede ninguna llamada `await db.delete` en todo `scripts/sync_catalog.py`.
4. En lugar de borrar las fuentes correspondientes a `missing_ids`:
   - Para cada `Source` del proveedor ausente del snapshot:
     - Asignar `source.catalog_presence = "missing"`.
     - Si `source.missing_since is None`, asignar `source.missing_since = observed_at` (preservando el valor previo si ya estaba ausente).
     - Incrementar `source.consecutive_misses = (source.consecutive_misses or 0) + 1`.
     - Dejar inalterados `last_seen_at` y `last_seen_run_id` (que registran la última observación positiva).
5. Mantener intacta la lógica de presencia positiva para las fuentes presentes (`catalog_presence = "present"`, `missing_since = None`, `consecutive_misses = 0`, actualización de `last_seen_at` y `last_seen_run_id`).
6. Ajustar los nombres de contadores y textos de logging/resumen:
   - Renombrar contadores como `deleted_sources` / `deleted_media` por `marked_missing` o `missing_sources_count`.
   - Actualizar el mensaje de log final o impresión para reflejar "fuentes marcadas ausentes" en lugar de "eliminadas".
   - No introducir el estado `retired`.
7. Verificar con `python3 -m py_compile scripts/sync_catalog.py` que el archivo no contiene errores de sintaxis.

---

## PASO 2: Actualizar y añadir pruebas de regresión focalizadas para marcado de ausencias

### Archivo a modificar
- `tests/test_catalog_sync.py`

### Instrucciones
1. Leer `tests/test_catalog_sync.py` y localizar los tests existentes que verificaban borrado físico de fuentes o medios en la reconciliación de checkpoints.
2. Actualizar los tests existentes que esperaban que `source` o `media` desaparecieran de la base de datos tras un checkpoint con final natural:
   - Ahora deben verificar que tanto `Source` como `Media` SIGUEN existiendo en la base de datos.
   - Deben verificar que `source.catalog_presence == "missing"`.
3. Añadir o completar casos de prueba con SQLite temporal en memoria / sesión de prueba:
   - **Caso 1 (Marcado inicial de ausencia y preservación)**: Snapshot completo con `stop_reason="natural_end"` omite una fuente preexistente. Verificar que la fuente no se borra, su `Media` no se borra, `catalog_presence == "missing"`, `missing_since` queda registrado con la marca de tiempo de la ejecución, y `consecutive_misses == 1`.
   - **Caso 2 (Ausencias consecutivas)**: Ejecutar una segunda reconciliación completa que vuelve a omitir la fuente. Verificar que `consecutive_misses == 2`, pero `missing_since`, `last_seen_at` y `last_seen_run_id` conservan sus valores de la ejecución previa.
   - **Caso 3 (Preservación con limit)**: Una ejecución con parámetro `--limit` (o `limit` fijado) no debe marcar ausencias ni modificar el estado de fuentes omitidas.
   - **Caso 4 (Rollback con dry-run)**: Ejecutar con `dry_run=True`. Verificar que la transacción se revierte y la fuente conserva su estado original sin cambios persistidos.
   - **Caso 5 (Checkpoint no apto)**: Verificar que checkpoints con `stop_reason` distinto de `natural_end` no marcan ausencias ni borran filas.
   - **Caso 6 (Protección contra cambio masivo >25%)**: Simular omisión masiva superior al 25% del catálogo. Verificar que se dispara el error de seguridad antes de alterar registros y que ninguna fila es borrada ni marcada si no se pasa `allow_large_delete=True`.
4. Ejecutar la suite de pruebas del archivo:
   `pytest -q tests/test_catalog_sync.py`
   y comprobar que pasan al 100%.

---

ACEPTACION
! grep -q 'await db.delete' scripts/sync_catalog.py
grep -q 'catalog_presence = "missing"' scripts/sync_catalog.py
grep -q 'consecutive_misses' scripts/sync_catalog.py
grep -q 'missing_since' scripts/sync_catalog.py
git diff --exit-code c0a9acc -- src/db src/adapters src/api src/services alembic
pytest -q tests/test_catalog_sync.py
pytest -q

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
