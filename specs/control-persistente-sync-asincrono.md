# Control persistente de la sincronización asíncrona del catálogo

## Objetivo

Permitir que la API lance una sincronización manual de catálogo en segundo plano,
devuelva inmediatamente un identificador y exponga un estado durable consultable.
Debe existir como máximo una ejecución activa incluso con solicitudes concurrentes,
y un reinicio del proceso debe dejar explícitamente como interrumpidas las ejecuciones
que ya no pueden continuar.

Esta unidad construye el núcleo observable y recuperable. Los avisos Telegram, los
reintentos automáticos y la limpieza de históricos se implementarán después, usando
los estados persistidos aquí.

## Contrato de datos

1. Añadir un modelo y una migración Alembic posterior a `d6e1f2a3b4c5` para una
   tabla `catalog_sync_runs` con, como mínimo:
   - `id`: UUID textual, clave primaria.
   - `status`: `pending`, `running`, `completed`, `failed` o `interrupted`.
   - `active_slot`: entero nullable. Vale `1` solo mientras el estado sea
     `pending` o `running`, y vuelve a `NULL` al entrar en cualquier estado terminal.
   - `checkpoint_path`, `pages_completed`, `items_discovered` y `last_activity_at`.
   - `created_at`, `started_at`, `finished_at` y `error` nullable.
2. La base debe imponer la restricción `uq_catalog_sync_runs_active_slot` de
   unicidad sobre `active_slot`. Así dos procesos o dos
   solicitudes concurrentes no pueden confirmar a la vez una segunda ejecución activa.
3. La migración debe funcionar sobre SQLite existente, conservar todas las tablas y
   filas previas y tener downgrade seguro que elimine únicamente
   `catalog_sync_runs` y sus índices.
4. No guardar logs completos ni contenido del catálogo dentro del registro de ejecución.

## Servicio de control

1. Crear un servicio dedicado, independiente del router, que reciba una fábrica de
   sesiones y un runner async inyectable para pruebas.
2. `start()` debe:
   - insertar y confirmar primero un registro `pending` con `active_slot=1`;
   - resolver la carrera de unicidad de SQLite devolviendo un error de dominio que
     incluya la ejecución activa, sin crear una segunda tarea;
   - programar después una `asyncio.Task`, conservar una referencia fuerte y devolver
     el registro recién creado sin esperar el rastreo.
3. La tarea debe cambiar a `running`, ejecutar el flujo real de `sync_catalog` con
   los defaults seguros actuales (`allow_large_delete=False`, sin enriquecimiento),
   y actualizar por página `pages_completed`, `items_discovered` y
   `last_activity_at` en transacciones breves.
4. Ampliar el flujo de sincronización solo con el callback o resultado mínimo necesario
   para reportar progreso. La CLI existente debe seguir funcionando igual cuando no se
   suministre callback.
5. Marcar `completed` únicamente si el runner termina sin excepción y el checkpoint
   final tiene `status="complete"` y `stop_reason="natural_end"`. En ese cierre debe
   persistir los conteos finales, `finished_at` y liberar `active_slot`.
6. Ante una excepción, persistir `failed`, un mensaje de error acotado, `finished_at`
   y liberar `active_slot`. No incluir traceback ni secretos en la respuesta API.
7. Ante cancelación o cierre ordenado de la aplicación, persistir `interrupted`,
   `finished_at` y liberar `active_slot` antes de propagar la cancelación.
8. Al arrancar la aplicación, convertir cualquier registro `pending` o `running`
   heredado de un proceso anterior en `interrupted`, con razón de reinicio, y liberar
   su slot. No reanudar automáticamente en esta unidad; el checkpoint existente permite
   que un nuevo disparo continúe después.
9. Al cerrar la aplicación, cancelar y esperar únicamente las tareas propiedad del
   servicio. No cancelar tareas ajenas del event loop.

## API

1. Añadir un router bajo `/api/v1/catalog-sync` y conectarlo tanto en `_build_app`
   como en `create_app`.
2. `POST /api/v1/catalog-sync/runs`:
   - responde `202` con el registro `pending` y su UUID;
   - no espera la sincronización;
   - responde `409` si ya existe una ejecución activa, incluyendo el UUID y estado
     de esa ejecución.
3. `GET /api/v1/catalog-sync/runs/latest` devuelve la ejecución más reciente o `404`.
4. `GET /api/v1/catalog-sync/runs/{run_id}` devuelve el estado persistido o `404`.
5. Las respuestas deben exponer fechas ISO, progreso y error acotado, pero nunca
   traceback, variables de entorno, secretos ni logs completos.
6. La aplicación debe crear el servicio en lifespan, ejecutar la recuperación de
   huérfanos antes de aceptar trabajo y cerrarlo ordenadamente al salir. Debe existir
   una vía simple de inyección/override para que las pruebas no hagan red real.

## Pruebas obligatorias

1. La migración desde la revisión anterior hasta `head` crea la tabla y el índice
   único, conserva datos anteriores y el downgrade elimina solo la tabla nueva.
2. `POST` devuelve en menos de un tiempo razonable sin esperar un runner bloqueado;
   el job puede consultarse por UUID.
3. Dos disparos concurrentes producen exactamente un `202` y un `409`, con un solo
   registro activo en SQLite.
4. Un runner fake que informa dos páginas deja los conteos y actividad persistidos y
   termina en `completed` solo con checkpoint `complete/natural_end`.
5. Excepción del runner termina en `failed`, libera el slot y permite lanzar otra ejecución.
6. Cancelación termina en `interrupted`, libera el slot y permite lanzar otra ejecución.
7. La recuperación de arranque convierte registros `pending` y `running` en
   `interrupted`, pero no altera registros terminales.
8. `GET latest` y `GET por UUID` cubren respuestas exitosas y `404`.
9. Las pruebas no acceden a Cuevana ni a Telegram y no escriben la base/checkpoint de
   producción.

## Límites

- No implementar avisos Telegram todavía.
- No implementar reintentos automáticos, cron, cola distribuida ni limpieza histórica.
- No cambiar la política de retiro, el umbral de borrado ni la identidad `(provider, url)`.
- No modificar reproducción, resolvers, M3U, Xtream ni los cambios HLS sueltos del árbol principal.
- No aceptar parámetros API que habiliten `allow_large_delete`, enriquecimiento o rutas arbitrarias.
- No desplegar ni tocar la base o los checkpoints de producción.

## ACEPTACION

. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_catalog_sync_jobs.py tests/test_migrations.py tests/test_smoke.py
. /home/emon/media-integration-gateway/.venv/bin/activate && python -c "from src.db.models import CatalogSyncRun; assert CatalogSyncRun.__tablename__ == 'catalog_sync_runs'; assert CatalogSyncRun.__table__.columns['active_slot'].nullable is True; assert any(c.name == 'uq_catalog_sync_runs_active_slot' for c in CatalogSyncRun.__table__.constraints)"

PREMISES

I La sincronización completa ya existe como coroutine `sync_catalog` y hoy se invoca de forma bloqueante desde la CLI — scripts/sync_catalog.py:329-359,443-454
I La persistencia por página ya tiene un callback natural después de cada página descubierta — scripts/sync_catalog.py:47-58
I El checkpoint durable ya guarda páginas, ítems, estado, razón de parada y próxima página mediante reemplazo atómico — src/services/catalog_checkpoint.py:39-78
I La reconciliación solo permite bajas con snapshot completo y parada natural — scripts/sync_catalog.py:266-291
I La aplicación ya dispone de lifespan para inicializar y cerrar recursos — src/main.py:40-83
I La base de producción es SQLite sobre el volumen `/app/data` — docker-compose.yml:9-12
I La revisión Alembic actual es `d6e1f2a3b4c5` — alembic/versions/d6e1f2a3b4c5_add_page_url_to_sources.py:13-17
I No existe hoy modelo, tabla, router ni servicio de ejecuciones asíncronas — src/db/models.py:1-75, src/main.py:1-105
