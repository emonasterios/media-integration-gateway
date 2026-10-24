# ENCARGO: Reconciliar ausencias sin borrado físico — unidad 2B.1

## Objetivo acotado

Sustituir exclusivamente la fase de borrado de la reconciliación de catálogo por marcado
persistente de ausencia en `Source`. Una fuente que no aparece en un snapshot completo y
terminado naturalmente debe conservarse junto con su `Media`; esta unidad no implementa aún
retiro definitivo, umbrales temporales ni exposición pública del estado.

## Reglas obligatorias

- Leer antes de editar y limitar los cambios a `scripts/sync_catalog.py` y pruebas focalizadas
  en `tests/test_catalog_sync.py`.
- No modificar modelos, migraciones, adapters, API, resolvers, reproducción ni despliegue.
- No borrar físicamente ninguna fila de `sources` ni de `media` durante la reconciliación.
- No ejecutar una sincronización real ni tocar bases/checkpoints de producción.
- Conservar las barreras existentes: solo reconciliar ausencias tras checkpoint completo con
  `stop_reason="natural_end"`; `--limit` deshabilita ausencias; `--dry-run` revierte todo; la
  protección de cambio masivo superior a 25% sigue exigiendo `allow_large_delete=True`.

## Implementación requerida

En `sync_from_checkpoint`, reemplazar la fase actual de bajas y limpieza de huérfanos:

1. Para cada `Source` del proveedor ausente del snapshot apto para reconciliación:
   - establecer `catalog_presence = "missing"`;
   - establecer `missing_since = observed_at` solo si actualmente es `None`, preservando el
     instante original en ausencias sucesivas;
   - incrementar `consecutive_misses` en uno;
   - conservar sin cambios `last_seen_at` y `last_seen_run_id`, que representan la última
     observación positiva.
2. Mantener intactas las transiciones positivas ya implementadas para fuentes presentes.
3. Eliminar de este flujo tanto `db.delete(source)` / `db.delete(media)` como la limpieza física
   de fuentes huérfanas. No reemplazarlos por otro borrado, cascada o SQL directo.
4. Ajustar nombres de contadores y el resumen impreso para hablar de fuentes marcadas ausentes,
   no de fuentes o medios retirados. No introducir todavía estado `retired`.

## Regresiones focalizadas

Añadir pruebas sin red y con SQLite temporal que demuestren:

1. Un snapshot completo con final natural marca una fuente omitida como `missing`, fija
   `missing_since`, incrementa el contador a uno y conserva tanto la fuente como su película.
2. Una segunda reconciliación completa que vuelve a omitirla incrementa el contador, pero
   preserva `missing_since`, `last_seen_at` y `last_seen_run_id`.
3. Una ejecución con `limit` no marca ausencias.
4. `dry_run=True` revierte el marcado de ausencia.
5. Un checkpoint no apto para reconciliación sigue sin escribir; reutilizar las pruebas
   existentes cuando ya cubran este contrato.
6. La protección de cambio masivo sigue rechazando más de 25% salvo autorización explícita,
   ahora antes de marcar ausencias y sin borrar filas.

## Fuera de alcance

- Retirar fuentes después de N ausencias o de un plazo.
- Borrar fuentes, películas u otros residuos.
- Cambiar la lectura pública para ocultar fuentes `missing`.
- Cambiar el significado de fallos de reproducción o salud del resolver.
- Cambiar el esquema, desplegar o sincronizar producción.

## ACEPTACION

```bash
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_catalog_sync.py
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q
! grep -q 'await db.delete' scripts/sync_catalog.py
git diff --exit-code c0a9acc -- src/db src/adapters src/api src/services alembic
```

## PREMISES

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
