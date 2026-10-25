<!-- spec:d426ce1130f113bb42faa053c5e2ed60 -->
# ENCARGO: Rediseño del progreso de sincronización del catálogo

## REGLAS OBLIGATORIAS DE EJECUCIÓN
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- Cada paso debe compilar e importar limpiamente al terminar.

---

## PASO 1: Modelos ORM para la persistencia del progreso
**Archivo a modificar:** `src/db/models.py`

**FALLO DE FONDO CRÍTICO (evitar antes de tocar nada):**
En SQLite, añadir columnas NOT NULL sin un default predeterminado a tablas con registros previos hace fallar la base de datos en tiempo de ejecución. Además, desalinear los tipos o no definir valores por defecto en SQLAlchemy provocará fallos en los inserts asíncronos. Asimismo, `CatalogSyncPage` debe tener una restricción única compuesta `(run_id, page_number)` con FK en cascada a `catalog_sync_runs.id`.

**Qué debe quedar en `src/db/models.py`:**
1. En el modelo `CatalogSyncRun`:
   - Añadir columna `phase` (`String(32)`, `nullable=False`, `default="queued"`).
   - Añadir columna `stop_reason` (`String(32)`, `nullable=True`, `default=None`).
   - Añadir contadores enteros (`nullable=False`, `default=0`): `items_seen`, `items_unique`, `items_inserted`, `items_updated`, `items_unchanged`, `items_duplicate_in_run`, `items_rejected`.
   - Mantener la columna `items_discovered` (`Integer`, `nullable=False`, `default=0`) como alias compatible que refleje `items_unique`.
   - Añadir relación `pages` hacia el nuevo modelo `CatalogSyncPage` con `cascade="all, delete-orphan"`.
2. Crear el modelo `CatalogSyncPage`:
   - Nombre de tabla: `catalog_sync_pages`.
   - `id`: `Integer`, `primary_key=True`, `autoincrement=True`.
   - `run_id`: `String(36)`, `ForeignKey("catalog_sync_runs.id", ondelete="CASCADE")`, `nullable=False`, `index=True`.
   - `page_number`: `Integer`, `nullable=False`.
   - `page_url`: `Text`, `nullable=False`.
   - `next_page_url`: `Text`, `nullable=True`.
   - `page_fingerprint`: `String(64)`, `nullable=False`.
   - Contadores de la página: `seen`, `unique`, `inserted`, `updated`, `unchanged`, `duplicate_in_run`, `rejected` (todos `Integer`, `nullable=False`, `default=0`).
   - `committed_at`: `DateTime(timezone=True)`, `server_default=func.now()`, `nullable=False`.
   - Restricción única de tabla: `UniqueConstraint("run_id", "page_number", name="uq_catalog_sync_pages_run_page")`.
   - Relación inversa `run = relationship("CatalogSyncRun", back_populates="pages")`.

---

## PASO 2: Migración Alembic para las nuevas columnas y la tabla de páginas
**Archivo a crear:** `alembic/versions/f8a3b2c1d4e5_sync_progress_redesign.py`

**Qué debe quedar:**
1. Revisión Alembic encadenada a `e7f2a1b3c4d5`:
   - `revision = 'f8a3b2c1d4e5'`
   - `down_revision = 'e7f2a1b3c4d5'`
2. En `upgrade()`:
   - Usar `op.batch_alter_table("catalog_sync_runs")` para agregar:
     - `phase`: `sa.String(length=32)`, `nullable=False`, `server_default="queued"`.
     - `stop_reason`: `sa.String(length=32)`, `nullable=True`.
     - `items_seen`: `sa.Integer()`, `nullable=False`, `server_default="0"`.
     - `items_unique`: `sa.Integer()`, `nullable=False`, `server_default="0"`.
     - `items_inserted`: `sa.Integer()`, `nullable=False`, `server_default="0"`.
     - `items_updated`: `sa.Integer()`, `nullable=False`, `server_default="0"`.
     - `items_unchanged`: `sa.Integer()`, `nullable=False`, `server_default="0"`.
     - `items_duplicate_in_run`: `sa.Integer()`, `nullable=False`, `server_default="0"`.
     - `items_rejected`: `sa.Integer()`, `nullable=False`, `server_default="0"`.
   - Crear tabla `catalog_sync_pages` con `op.create_table`:
     - `id` (Integer, primary key), `run_id` (String(36), ForeignKey en cascade), `page_number` (Integer), `page_url` (Text), `next_page_url` (Text, nullable), `page_fingerprint` (String(64)), `seen` (Integer), `unique` (Integer), `inserted` (Integer), `updated` (Integer), `unchanged` (Integer), `duplicate_in_run` (Integer), `rejected` (Integer), `committed_at` (DateTime con server_default).
     - Restricción `sa.UniqueConstraint('run_id', 'page_number', name='uq_catalog_sync_pages_run_page')`.
3. En `downgrade()`:
   - `op.drop_table("catalog_sync_pages")`.
   - Con `op.batch_alter_table("catalog_sync_runs")` eliminar las columnas agregadas.

---

## PASO 3: Esquemas Pydantic y contrato de transferencia de progreso
**Archivo a modificar:** `src/models/catalog_sync.py`

**Qué debe quedar en `src/models/catalog_sync.py`:**
1. Crear el modelo o dataclass `PageSyncResult`:
   - `page_number: int`
   - `page_url: str`
   - `next_page_url: str | None = None`
   - `fingerprint: str`
   - `seen: int`
   - `unique: int`
   - `inserted: int`
   - `updated: int`
   - `unchanged: int`
   - `duplicate_in_run: int`
   - `rejected: int`
2. Actualizar el esquema `CatalogSyncRunRead`:
   - Incluir campos:
     - `phase: str = "queued"`
     - `stop_reason: str | None = None`
     - `next_page_url: str | None = None`
     - `items_seen: int = 0`
     - `items_unique: int = 0`
     - `items_inserted: int = 0`
     - `items_updated: int = 0`
     - `items_unchanged: int = 0`
     - `items_duplicate_in_run: int = 0`
     - `items_rejected: int = 0`
   - Mantener `items_discovered: int = 0` para compatibilidad regresiva con clientes previos.
   - Configuración Pydantic con `from_attributes = True` compatible.

---

## PASO 4: Normalización canónica de URLs de catálogo
**Archivo a modificar:** `src/services/catalog.py`

**Qué debe quedar en `src/services/catalog.py`:**
1. Añadir la función `normalize_catalog_url(url: str | None) -> str | None`:
   - Si `url` es vacío o `None`, devolver `None`.
   - Parsear con `urllib.parse.urlsplit`.
   - Normalizar esquema y host (netloc) a minúsculas.
   - Eliminar componentes de query (`query=""`) y fragmento (`fragment=""`).
   - Normalizar la ruta colapsando barras repetidas consecutivas (ej. `//` -> `/`).
   - Aplicar política uniforme de barra final (eliminar barra final a menos que la ruta sea únicamente `/`).
   - Reconstruir con `urlunsplit`.
2. Asegurar que la función pueda importarse directamente desde `src.services.catalog`.

---

## PASO 5: Adaptador Cuevana3: detección de parada y fin natural
**Archivo a modificar:** `src/adapters/cuevana3.py`

**Qué debe quedar en `src/adapters/cuevana3.py`:**
1. En `discover_resumable`:
   - Eliminar la emisión de `no_new_items` como condición de parada para corridas nuevas.
   - Si un checkpoint previo contiene `no_new_items`, permitir leerlo sin fallar, pero nunca emitir este valor en nuevas ejecuciones.
   - Generar huella (fingerprint) de la página ordenando los `provider_id` extraídos de los elementos.
   - Detectar condiciones de terminación terminales:
     - `natural_end`: cuando el HTML no contiene enlace a siguiente página.
     - `pagination_cycle`: cuando la URL siguiente normalizada ya fue visitada en la corrida actual.
     - `repeated_page`: cuando la huella de identidades coincide exactamente con la página anterior y no hay avance.
     - `max_pages`: cuando se alcanza el límite configurado de páginas.
   - Reportar la causa de terminación precisa en el retorno o callback de descubrimiento.

---

## PASO 6: Persistencia transaccional por página y clasificación exhaustiva
**Archivo a modificar:** `scripts/sync_catalog.py`

**Qué debe quedar en `scripts/sync_catalog.py`:**
1. Sustituir la lógica de conteo de `persist_page_batch`:
   - Para cada página procesada en una corrida (`run_id`, `page_number`):
     a) Comprobar si ya existe un registro en `catalog_sync_pages` para `(run_id, page_number)`. Si ya existe, abortar la persistencia de esa página (replay idempotente) y retornar sin modificar datos ni contadores acumulados.
     b) Para cada elemento de la página, clasificarlo en exactamente una de 5 categorías:
        - `rejected`: no cumple el contrato o carece de `provider_id`.
        - `duplicate_in_run`: su identidad `(provider, provider_id)` ya fue vista en una página previa de esta misma corrida.
        - `inserted`: no existía en la base de datos `(provider, provider_id)`. Se crea `Media` y `Source` (`page_url` normalizada con `normalize_catalog_url`).
        - `updated`: ya existía en la base de datos, pero al menos un campo persistible normalizado cambió (título, año, póster o `page_url` normalizada). Solo se actualizan los campos modificados.
        - `unchanged`: ya existía en la base de datos y ningún campo persistible cambió (incluyendo cuando solo variaba query, fragmento o mayúsculas del host en `page_url`).
     c) Verificar la invariante:
        `seen = inserted + updated + unchanged + duplicate_in_run + rejected`
        `unique = inserted + updated + unchanged`
     d) Insertar el registro correspondiente en `catalog_sync_pages`.
     e) Actualizar en `catalog_sync_runs` los acumulados (`items_seen`, `items_unique`, `items_inserted`, `items_updated`, `items_unchanged`, `items_duplicate_in_run`, `items_rejected`, `pages_completed`, `items_discovered = items_unique`, `last_activity_at = func.now()`).
     f) Confirmar la transacción atómicamente.
2. Invocar el callback de progreso pasando una instancia de `PageSyncResult` en lugar de una tupla `(pages, items)`.

---

## PASO 7: Servicio de ciclo de vida de sincronización
**Archivo a modificar:** `src/services/catalog_sync.py`

**Qué debe quedar en `src/services/catalog_sync.py`:**
1. Actualizar `CatalogSyncService.on_progress` para recibir un objeto `PageSyncResult` (o datos estructurados equivalentes):
   - Actualizar el registro `CatalogSyncRun` con los contadores exactos provenientes de la persistencia transaccional.
   - Reflejar `items_discovered = items_unique`.
2. Gestión de fases y razones de terminación:
   - `phase`: transiciones válidas `queued -> crawling -> reconciling -> finished`.
   - `status`: transiciones `pending -> running -> completed | interrupted | failed`.
   - `stop_reason`: persistir la causa terminal (`natural_end`, `pagination_cycle`, `repeated_page`, `max_pages`, `network_error`, `cancelled`, `process_restart`, `internal_error`).
   - Solo cuando `status == "completed"`, `phase == "finished"` y `stop_reason == "natural_end"` se considera una corrida apta para reconciliación de bajas.
   - Ante `pagination_cycle`, `repeated_page`, `max_pages` o error, marcar `status="interrupted"` (o `"failed"` según corresponda), `phase="finished"`, liberar `active_slot` y no habilitar bajas.

---

## PASO 8: Exposición en la API y compatibilidad de endpoints
**Archivo a modificar:** `src/api/catalog_sync.py`

**Qué debe quedar en `src/api/catalog_sync.py`:**
1. En `GET /api/v1/catalog-sync/runs/latest` y `GET /api/v1/catalog-sync/runs/{run_id}`:
   - Serializar la respuesta utilizando el esquema actualizado `CatalogSyncRunRead`.
   - Exponer `phase`, `stop_reason`, contadores (`items_seen`, `items_unique`, `items_inserted`, `items_updated`, `items_unchanged`, `items_duplicate_in_run`, `items_rejected`).
   - Exponer `next_page_url` sanitizado (sin credenciales ni datos sensibles).
   - Mantener `items_discovered` como alias de `items_unique`.
   - Mantener sin cambios los códigos HTTP (202 para inicio, 409 si hay ejecución en curso con `active_slot`).

---

## PASO 9: Pruebas unitarias e integración de migración y progreso
**Archivos a modificar:** `tests/test_catalog_sync.py`, `tests/test_catalog_sync_jobs.py`, `tests/test_migrations.py`

**Qué debe quedar:**
1. En `tests/test_migrations.py`:
   - Probar upgrade y downgrade de la migración `f8a3b2c1d4e5` asegurando que no se pierden datos en `media`, `sources` ni corridas previas en `catalog_sync_runs`.
2. En `tests/test_catalog_sync.py` y `tests/test_catalog_sync_jobs.py`:
   - Test 1: Página con elementos nuevos incrementa solo `inserted`.
   - Test 2: Repetir los mismos datos incrementa `unchanged`, manteniendo `updated = 0`.
   - Test 3: Cambiar título, año, póster o `page_url` normalizada incrementa `updated` y no `inserted`.
   - Test 4: Variación de query, fragmento, mayúsculas de host o barra final no produce actualización (`unchanged`).
   - Test 5: Identidad repetida en la misma corrida incrementa `duplicate_in_run` y no altera la BD.
   - Test 6: Se cumple el invariante `seen = inserted + updated + unchanged + duplicate_in_run + rejected` y `unique = inserted + updated + unchanged`.
   - Test 7: Reprocesar una página ya confirmada (mismo `run_id` y `page_number`) no incrementa contadores ni altera datos.
   - Test 8: Múltiples páginas con 0 insertados no disparan terminación del crawler.
   - Test 9: Fin natural de catálogo (`natural_end`) culmina con `completed`, `finished` y `natural_end`.
   - Test 10: Ciclos de URL o páginas repetidas culminan en `interrupted`, liberando el slot activo sin habilitar bajas.
   - Test 11: Endpoints devuelven los nuevos campos y mantienen `items_discovered`.

---

ACEPTACION
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_catalog_sync.py tests/test_catalog_sync_jobs.py tests/test_migrations.py tests/test_smoke.py
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q
test ! -e data/gateway.db
git diff --exit-code -- src/api/xtream.py src/services/video_resolver.py src/services/mediaflow_bridge.py src/services/stream_proxy.py
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_catalog_sync.py -k 'natural_end and unchanged'
grep -q "catalog_sync_pages" src/db/models.py
grep -q "items_unchanged" src/models/catalog_sync.py
grep -q "PageSyncResult" src/models/catalog_sync.py
grep -q "normalize_catalog_url" src/services/catalog.py
grep -q "stop_reason" src/db/models.py

PREMISES

I `CatalogSyncRun` solo conserva `pages_completed` e `items_discovered` — src/db/models.py:78-99
I `CatalogSyncRunRead` expone el mismo progreso ambiguo — src/models/catalog_sync.py:1-38
I `CatalogSyncService.on_progress` recibe únicamente `(pages, items)` — src/services/catalog_sync.py:1-226
I `persist_page_batch` clasifica coincidencias existentes como actualizadas aunque no cambien — scripts/sync_catalog.py:1-280
I `discover_resumable` todavía puede emitir `no_new_items` — src/adapters/cuevana3.py:250-530
I `page_url` ya forma parte del modelo de fuentes y no reemplaza la identidad `(provider, provider_id)` — src/db/models.py:20-77
I El checkout principal contiene cambios HLS no relacionados y esta unidad se ejecutará en un worktree limpio — /home/emon/media-integration-gateway:git-status
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
