# Rediseño del progreso de sincronización del catálogo

## Objetivo

Separar de forma inequívoca el avance del rastreo, el efecto real sobre SQLite y
la causa de terminación de una sincronización. La API debe poder responder, sin
inferencias, cuántas páginas se recorrieron, cuántos elementos se vieron, cuántos
eran duplicados de la corrida, cuántos ya existían sin cambios, cuántos cambiaron
y cuántos se insertaron.

La implementación no debe desplegarse ni ejecutar una sincronización real dentro
de esta unidad. Primero debe quedar probada íntegramente con proveedor y SQLite
temporales.

## Problema confirmado

La corrida `80b536a4-5b2d-43e8-a575-3c439033ba56` terminó con 437 páginas y
19.528 identidades acumuladas, pero solo insertó una película. El contrato actual
expone únicamente `pages_completed` e `items_discovered`; además,
`persist_page_batch` cuenta como `updated` cualquier coincidencia existente aunque
ningún campo cambie. Por ello el progreso de navegación se confunde con altas o
modificaciones de la base.

El crawler también puede detenerse con `no_new_items` cuando varias páginas no
añaden identidades al checkpoint. Que una página contenga registros ya conocidos
no demuestra el final del catálogo y no debe ser una condición de terminación.

## Decisiones de arquitectura

### 1. Tres dominios independientes

1. **Rastreo**: páginas visitadas, apariciones vistas, identidades únicas y próxima
   página.
2. **Persistencia**: insertados, modificados, existentes sin cambios, duplicados
   dentro de la corrida y rechazados.
3. **Ciclo de vida**: estado de la ejecución, fase actual y razón terminal.

Ningún contador de un dominio puede reutilizarse con otro significado.

### 2. Identidad y URL canónica

- La identidad estable continúa siendo `(provider, provider_id)`; para Cuevana3,
  `provider_id` es el slug derivado de la ruta.
- `Source.page_url` conserva la página completa del contenido y funciona como
  evidencia secundaria y dato actualizable, no como clave primaria.
- Antes de comparar `page_url`, normalizar esquema y host a minúsculas, eliminar
  query y fragmento, colapsar barras redundantes y aplicar una política única a la
  barra final.
- Un cambio de dominio con la misma identidad actualiza `page_url`; no crea otra
  película.
- `Source.url` mantiene su semántica existente para no romper reproducción ni la
  restricción `uq_sources_provider_url`. No se hará una migración semántica de esa
  columna en esta unidad.

### 3. Clasificación exhaustiva por elemento

Cada aparición procesada debe acabar exactamente en una categoría:

- `inserted`: no existía `(provider, provider_id)` y se creó `Media` + `Source`.
- `updated`: existía y cambió al menos un campo persistible normalizado.
- `unchanged`: existía y no cambió ningún campo persistible.
- `duplicate_in_run`: la identidad ya apareció antes en la misma corrida; no se
  vuelve a persistir.
- `rejected`: falta identidad o el elemento no cumple el contrato de catálogo.

Invariante por corrida:

```text
items_seen = inserted + updated + unchanged + duplicate_in_run + rejected
```

`items_unique` debe equivaler a:

```text
items_unique = inserted + updated + unchanged
```

### 4. Estado y fase

Conservar `status` como ciclo de vida estable:

```text
pending | running | completed | interrupted | failed
```

Añadir `phase` para no sobrecargarlo:

```text
queued | crawling | reconciling | finished
```

Añadir `stop_reason`, separado de `status`:

```text
natural_end | pagination_cycle | repeated_page | max_pages |
network_error | cancelled | process_restart | internal_error
```

Solo `completed + finished + natural_end` representa una corrida completa apta
para reconciliación de bajas.

### 5. Condiciones de parada

- Eliminar `no_new_items` como condición emitida por corridas nuevas.
- Fin natural: el DOM no contiene enlace siguiente.
- Ciclo: la URL normalizada de la próxima página ya fue visitada.
- Página repetida: se repite la misma huella ordenada de identidades y no existe
  evidencia de avance real.
- `max_pages` permanece como fusible y produce una corrida `interrupted`.
- Mantener lectura compatible con checkpoints antiguos que ya contengan
  `no_new_items`, pero nunca emitirlo desde el nuevo crawler.

## Persistencia durable del progreso

### `catalog_sync_runs`

Conservar las columnas actuales y añadir:

- `phase` (`String(32)`, no nulo, default `queued`).
- `stop_reason` (`String(32)`, nullable).
- `items_seen` (`Integer`, no nulo, default 0).
- `items_unique` (`Integer`, no nulo, default 0).
- `items_inserted` (`Integer`, no nulo, default 0).
- `items_updated` (`Integer`, no nulo, default 0).
- `items_unchanged` (`Integer`, no nulo, default 0).
- `items_duplicate_in_run` (`Integer`, no nulo, default 0).
- `items_rejected` (`Integer`, no nulo, default 0).

Conservar temporalmente `items_discovered` para compatibilidad y hacerlo reflejar
`items_unique`. No usarlo internamente para decisiones.

### `catalog_sync_pages`

Crear una tabla de resultados por página:

- `run_id`, FK a `catalog_sync_runs.id` con borrado en cascada.
- `page_number`.
- `page_url` normalizada.
- `next_page_url` normalizada y nullable.
- `page_fingerprint`.
- los siete contadores de clasificación de esa página.
- `committed_at`.
- restricción única `(run_id, page_number)`.

La tabla evita doble conteo al repetir una página después de una caída y permite
auditar el progreso sin guardar el contenido completo ni logs.

## Frontera transaccional por página

Para cada página, una única transacción SQLite debe:

1. comprobar si `(run_id, page_number)` ya fue confirmado;
2. clasificar las identidades de la página;
3. insertar o modificar únicamente los registros necesarios;
4. insertar `catalog_sync_pages`;
5. incrementar los acumulados de `catalog_sync_runs`;
6. actualizar `pages_completed`, `last_activity_at` y la próxima página durable;
7. confirmar.

Si la página ya estaba confirmada, se considera replay y no se vuelven a modificar
ni los datos ni los contadores. El checkpoint de archivo puede mantenerse durante
la transición, pero deja de ser la fuente de verdad de los contadores de la API.

## Contrato del callback

Reemplazar el callback ambiguo `(pages, items)` por un objeto tipado, por ejemplo:

```python
PageSyncResult(
    page_number: int,
    page_url: str,
    next_page_url: str | None,
    fingerprint: str,
    seen: int,
    unique: int,
    inserted: int,
    updated: int,
    unchanged: int,
    duplicate_in_run: int,
    rejected: int,
)
```

El servicio no debe recalcular resultados a partir del tamaño del checkpoint.

## API

`GET /api/v1/catalog-sync/runs/latest` y `GET /runs/{run_id}` deben añadir:

- `phase` y `stop_reason`;
- todos los contadores nuevos;
- `next_page_url` si no contiene credenciales ni datos sensibles.

`items_discovered` permanece durante una versión como alias compatible de
`items_unique` y debe documentarse como obsoleto. No cambiar el contrato de
exclusión `active_slot` ni el comportamiento `202/409`.

## Migración

- Crear una revisión Alembic posterior a la revisión que incorporó
  `catalog_sync_runs`.
- Añadir columnas con defaults compatibles para filas existentes.
- Crear `catalog_sync_pages` sin alterar `media`, `sources` ni sus datos.
- Downgrade: eliminar únicamente `catalog_sync_pages` y las columnas nuevas.
- Probar upgrade y downgrade sobre una base con medios, fuentes y corridas previas.

## Pruebas obligatorias

1. Una página de elementos inexistentes incrementa solo `inserted`.
2. Repetir los mismos datos incrementa `unchanged`, no `updated`.
3. Cambiar título, año, póster o `page_url` normalizada incrementa `updated` solo
   una vez y persiste únicamente los valores cambiados.
4. Cambiar solo query, fragmento, mayúsculas del host o barra final no produce una
   actualización.
5. Repetir una identidad dentro de la misma corrida incrementa
   `duplicate_in_run` y no toca nuevamente la fila.
6. Se cumple la invariante de clasificación después de cada página y al final.
7. Reprocesar una página ya confirmada no cambia datos ni acumulados.
8. Cero insertados durante muchas páginas no detiene el crawler.
9. Ausencia de `next` produce `completed/finished/natural_end`.
10. Ciclo de URL, página repetida y `max_pages` producen `interrupted`, liberan
    `active_slot` y nunca habilitan bajas.
11. Checkpoint antiguo con `no_new_items` sigue siendo legible y permanece no apto
    para reconciliación.
12. Los endpoints exponen contadores correctos y mantienen compatibilidad con
    `items_discovered`.
13. Migración upgrade/downgrade conserva medios, fuentes y corridas existentes.
14. Toda la suite permanece verde sin red real, VM ni base de producción.

## Alcance permitido

- Modelos, esquemas, servicio y router de `catalog_sync`.
- Flujo de descubrimiento/persistencia de `scripts/sync_catalog.py`.
- Terminación y normalización de paginación en `src/adapters/cuevana3.py`.
- Servicio de checkpoint solo para compatibilidad y contrato de terminación.
- Migración Alembic y pruebas focalizadas.

## Fuera de alcance

- Despliegue, sincronización real o edición de la base de producción.
- Reproducción, HLS, resolvers, M3U, Xtream o cambios locales actualmente sueltos.
- Borrado o limpieza de los tres registros legacy sin `page_url`.
- Reintentos automáticos, Telegram, cron o una cola distribuida.
- Cambiar la política de bajas más allá de consumir el nuevo estado terminal.

## ACEPTACION

. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_catalog_sync.py tests/test_catalog_sync_jobs.py tests/test_migrations.py tests/test_smoke.py
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q
test ! -e data/gateway.db
git diff --exit-code -- src/api/xtream.py src/services/video_resolver.py src/services/mediaflow_bridge.py src/services/stream_proxy.py
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_catalog_sync.py -k 'natural_end and unchanged'

PREMISES

I `CatalogSyncRun` solo conserva `pages_completed` e `items_discovered` — src/db/models.py:78-99
I `CatalogSyncRunRead` expone el mismo progreso ambiguo — src/models/catalog_sync.py:1-38
I `CatalogSyncService.on_progress` recibe únicamente `(pages, items)` — src/services/catalog_sync.py:1-226
I `persist_page_batch` clasifica coincidencias existentes como actualizadas aunque no cambien — scripts/sync_catalog.py:1-280
I `discover_resumable` todavía puede emitir `no_new_items` — src/adapters/cuevana3.py:250-530
I `page_url` ya forma parte del modelo de fuentes y no reemplaza la identidad `(provider, provider_id)` — src/db/models.py:20-77
I El checkout principal contiene cambios HLS no relacionados y esta unidad se ejecutará en un worktree limpio — /home/emon/media-integration-gateway:git-status
