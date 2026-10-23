<!-- spec:6e4b09ce67b88f90abf750a3e2a42dd7 -->
# ENCARGO: Control persistente de la sincronización asíncrona del catálogo

REGLAS OBLIGATORIAS:
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

ADVERTENCIA DE FONDO CRÍTICA:
En SQLite, la restricción de unicidad para permitir múltiples registros terminados exige que `active_slot` sea estrictamente `NULL` (`None` en Python) en cualquier estado terminal (`completed`, `failed`, `interrupted`). Si se persiste cualquier valor entero (como `0`) al terminar o interrumpir una ejecución, SQLite disparará `IntegrityError` en la siguiente ejecución bloqueando el sistema para siempre. `active_slot` solo puede valer `1` mientras el estado sea `pending` o `running`, y debe volver a `None` en absolutamente todas las ramas de salida (éxito, fallo, interrupción o reinicio).

---

## PASO 1: Modelo persistente CatalogSyncRun con restricción de slot único

- **Archivos a tocar**: `src/db/models.py`
- **Fallo de fondo a evitar**: Si `active_slot` no es nullable o no tiene la restricción con nombre explícito `uq_catalog_sync_runs_active_slot`, la base no garantizará la exclusión mutua en SQLite.
- **Qué debe quedar**:
  1. En `src/db/models.py`, importar `UniqueConstraint` desde `sqlalchemy` si no está importado.
  2. Añadir la clase `CatalogSyncRun(Base)` con `__tablename__ = "catalog_sync_runs"`.
  3. Campos de la tabla:
     - `id`: `Column(String(36), primary_key=True)` (almacena UUID textual).
     - `status`: `Column(String(32), nullable=False, default="pending")` (valores: `pending`, `running`, `completed`, `failed`, `interrupted`).
     - `active_slot`: `Column(Integer, nullable=True)` (permite `1` cuando está activa, `None` al finalizar).
     - `checkpoint_path`: `Column(String, nullable=True)`.
     - `pages_completed`: `Column(Integer, nullable=False, default=0)`.
     - `items_discovered`: `Column(Integer, nullable=False, default=0)`.
     - `last_activity_at`: `Column(DateTime(timezone=True), nullable=True)`.
     - `created_at`: `Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))`.
     - `started_at`: `Column(DateTime(timezone=True), nullable=True)`.
     - `finished_at`: `Column(DateTime(timezone=True), nullable=True)`.
     - `error`: `Column(Text, nullable=True)`.
  4. Definir en `__table_args__`:
     `UniqueConstraint("active_slot", name="uq_catalog_sync_runs_active_slot")`
  5. Mantener intactos todos los demás modelos y relaciones existentes en `src/db/models.py`.

---

## PASO 2: Migración Alembic para la tabla catalog_sync_runs

- **Archivos a tocar**: `alembic/versions/e7f2a1b3c4d5_catalog_sync_runs.py`
- **Qué debe quedar**:
  1. En `alembic/versions/e7f2a1b3c4d5_catalog_sync_runs.py`:
     - Identificador de revisión: `revision = 'e7f2a1b3c4d5'`.
     - Revisión previa estricta: `down_revision = 'd6e1f2a3b4c5'`.
     - `branch_labels = None` y `depends_on = None`.
  2. En `upgrade()`:
     - Crear la tabla `catalog_sync_runs` con:
       - `sa.Column('id', sa.String(length=36), primary_key=True)`
       - `sa.Column('status', sa.String(length=32), nullable=False)`
       - `sa.Column('active_slot', sa.Integer(), nullable=True)`
       - `sa.Column('checkpoint_path', sa.String(), nullable=True)`
       - `sa.Column('pages_completed', sa.Integer(), nullable=False, server_default='0')`
       - `sa.Column('items_discovered', sa.Integer(), nullable=False, server_default='0')`
       - `sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=True)`
       - `sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)`
       - `sa.Column('started_at', sa.DateTime(timezone=True), nullable=True)`
       - `sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True)`
       - `sa.Column('error', sa.Text(), nullable=True)`
       - `sa.UniqueConstraint('active_slot', name='uq_catalog_sync_runs_active_slot')`
  3. En `downgrade()`:
     - Eliminar únicamente la tabla `catalog_sync_runs`: `op.drop_table('catalog_sync_runs')`.
     - Conservar todas las demás tablas y columnas existentes.

---

## PASO 3: Callback no intrusivo de progreso en el flujo de sincronización

- **Archivos a tocar**: `scripts/sync_catalog.py`
- **Qué debe quedar**:
  1. Localizar la función `sync_catalog(...)` en `scripts/sync_catalog.py`.
  2. Añadir el parámetro opcional con default `None`:
     `on_page_progress: Optional[Callable[[int, int], Awaitable[None]]] = None` (donde los parámetros son `pages_completed: int, items_discovered: int`).
  3. Dentro del bucle que procesa cada página descubierta, tras actualizar las variables o checkpoints de progreso de página, invocar el callback si fue proporcionado:
     ```python
     if on_page_progress is not None:
         await on_page_progress(pages_count, total_items)
     ```
  4. Respetar estrictamente los valores por defecto y comportamiento cuando no se pase callback, asegurando que la invocación directa desde CLI funcione exactamente igual que antes.

---

## PASO 4: Esquemas DTO Pydantic para la sincronización

- **Archivos a tocar**: `src/models/catalog_sync.py`
- **Qué debe quedar**:
  1. En `src/models/catalog_sync.py`, crear los esquemas Pydantic necesarios para la API de sincronización:
     - `CatalogSyncRunRead(BaseModel)` con:
       - `id: str`
       - `status: str`
       - `active_slot: Optional[int] = None`
       - `checkpoint_path: Optional[str] = None`
       - `pages_completed: int = 0`
       - `items_discovered: int = 0`
       - `last_activity_at: Optional[datetime] = None`
       - `created_at: datetime`
       - `started_at: Optional[datetime] = None`
       - `finished_at: Optional[datetime] = None`
       - `error: Optional[str] = None`
       - Configuración Pydantic v2 `model_config = ConfigDict(from_attributes=True)` (o `orm_mode = True` si v1).
     - `CatalogSyncConflictDetail(BaseModel)` con:
       - `detail: str`
       - `active_run_id: str`
       - `status: str`
  2. No incluir campos de traceback ni logs internos en los esquemas expuestos.

---

## PASO 5: Servicio de control y recuperación de ejecuciones

- **Archivos a tocar**: `src/services/catalog_sync.py`
- **Qué debe quedar**:
  1. En `src/services/catalog_sync.py`, definir la excepción de dominio:
     ```python
     class ActiveRunConflictError(Exception):
         def __init__(self, active_run_id: str, status: str):
             self.active_run_id = active_run_id
             self.status = status
             super().__init__(f"Active sync run already exists: {active_run_id} ({status})")
     ```
  2. Crear la clase `CatalogSyncService`:
     - `__init__(self, session_factory, runner: Optional[Callable] = None)`:
       - Guarda `session_factory`.
       - Si no se inyecta `runner`, define uno por defecto que invoque `sync_catalog` con `allow_large_delete=False` y sin enriquecimiento.
       - Inicializa `self._running_tasks: set[asyncio.Task] = set()`.
     - `async def start() -> CatalogSyncRun`:
       - Genera `run_id = str(uuid.uuid4())`.
       - Abre sesión corta e intenta insertar `CatalogSyncRun` con `id=run_id`, `status="pending"`, `active_slot=1`, `created_at=datetime.now(timezone.utc)`.
       - Si ocurre `IntegrityError` por la restricción `uq_catalog_sync_runs_active_slot`:
         - Hacer rollback.
         - Consultar en la base el registro actual con `active_slot == 1`.
         - Lanzar `ActiveRunConflictError(active_run.id, active_run.status)`.
       - Tras confirmar el registro en BD, crear la tarea en segundo plano:
         `task = asyncio.create_task(self._execute_run(run_id))`
         `self._running_tasks.add(task)`
         `task.add_done_callback(self._running_tasks.discard)`
       - Devolver inmediatamente los datos del registro creado sin esperar a la tarea.
     - `async def _execute_run(self, run_id: str)`:
       - Transición a `running`: actualizar `status="running"`, `started_at` y `last_activity_at`.
       - Definir callback async de progreso para actualizar en transacciones breves `pages_completed`, `items_discovered` y `last_activity_at`.
       - Ejecutar el runner inyectado pasándole el callback.
       - Si el runner finaliza con checkpoint y este cumple `status == "complete"` y `stop_reason == "natural_end"` (o si el runner simulado devuelve éxito):
         - Transición terminal: `status="completed"`, `active_slot=None`, `finished_at=datetime.now(timezone.utc)`.
       - Ante `asyncio.CancelledError`:
         - Transición terminal: `status="interrupted"`, `active_slot=None`, `error="Task cancelled"`, `finished_at=datetime.now(timezone.utc)`.
         - Confirmar en BD y relanzar la cancelación si corresponde.
       - Ante cualquier otra `Exception as exc`:
         - Transición terminal: `status="failed"`, `active_slot=None`, `error=str(exc)[:500]`, `finished_at=datetime.now(timezone.utc)`.
     - `async def recover_interrupted_runs()`:
       - Al inicio, consultar registros con `status.in_(["pending", "running"])` o `active_slot.isnot(None)`.
       - Actualizarlos en BD a `status="interrupted"`, `active_slot=None`, `error="Interrupted by system restart"`, `finished_at=datetime.now(timezone.utc)`.
     - `async def shutdown()`:
       - Para cada tarea en `list(self._running_tasks)`: llamar a `task.cancel()`.
       - Esperar su finalización con `await asyncio.gather(*self._running_tasks, return_exceptions=True)`.
     - `async def get_run(self, run_id: str) -> Optional[CatalogSyncRun]`.
     - `async def get_latest_run(self) -> Optional[CatalogSyncRun]`:
       - Ordenado por `created_at.desc()`.

---

## PASO 6: Router API para la sincronización asíncrona

- **Archivos a tocar**: `src/api/catalog_sync.py`
- **Qué debe quedar**:
  1. En `src/api/catalog_sync.py`, crear un `APIRouter()`:
     - `POST /runs` con código de respuesta `202 Accepted`:
       - Obtiene `service: CatalogSyncService` desde `request.app.state.catalog_sync_service`.
       - Llama a `await service.start()`.
       - Si captura `ActiveRunConflictError as exc`, lanza `HTTPException(status_code=409, detail={"detail": str(exc), "active_run_id": exc.active_run_id, "status": exc.status})`.
       - Retorna el modelo `CatalogSyncRunRead`.
     - `GET /runs/latest`:
       - Llama a `await service.get_latest_run()`.
       - Si no hay ninguno, lanza `HTTPException(status_code=404, detail="No catalog sync runs found")`.
       - Retorna `CatalogSyncRunRead`.
     - `GET /runs/{run_id}`:
       - Llama a `await service.get_run(run_id)`.
       - Si no existe, lanza `HTTPException(status_code=404, detail=f"Run {run_id} not found")`.
       - Retorna `CatalogSyncRunRead`.
  2. No exponer parámetros que permitan forzar borrado masivo ni modificar rutas de checkpoint arbitrarias desde la API.

---

## PASO 7: Integración del router y lifespan en la aplicación principal

- **Archivos a tocar**: `src/main.py`
- **Qué debe quedar**:
  1. En `src/main.py`, importar el router desde `src.api.catalog_sync` y el servicio `CatalogSyncService` desde `src.services.catalog_sync`.
  2. En el gestor de ciclo de vida (`lifespan`):
     - Antes del `yield`:
       - Si `app.state.catalog_sync_service` no fue inyectado previamente (por ejemplo en pruebas), instanciar `CatalogSyncService(session_factory=async_session)` y asignarlo a `app.state.catalog_sync_service`.
       - Ejecutar `await app.state.catalog_sync_service.recover_interrupted_runs()`.
     - Después del `yield` (en el bloque cleanup/shutdown):
       - Si `hasattr(app.state, "catalog_sync_service")` y no es None, ejecutar `await app.state.catalog_sync_service.shutdown()`.
  3. En `_build_app()` y/o `create_app()`:
     - Incluir el router:
       `app.include_router(catalog_sync_router, prefix="/api/v1/catalog-sync", tags=["Catalog Sync"])`
     - Mantener todos los demás routers (`/api/v1/enrichment`, `/api/v1/m3u`, xtream, etc.) exactamente como estaban.

---

## PASO 8: Suite de pruebas obligatorias para catalog-sync

- **Archivos a tocar**: `tests/test_catalog_sync_jobs.py`
- **Qué debe quedar**:
  1. Crear `tests/test_catalog_sync_jobs.py` con pruebas aisladas usando base de datos SQLite en memoria/temporal y runner falso (sin llamadas a red):
     - `test_start_run_returns_202_immediately`: verifica respuesta 202 con UUID y status `pending`, sin bloquearse con runners lentos.
     - `test_concurrent_start_returns_409`: dos llamadas concurrentes a `service.start()` resultan en exactamente un éxito y un `ActiveRunConflictError` / HTTP 409 con los datos de la activa.
     - `test_runner_progress_and_completion`: runner simulado emite 2 páginas, actualiza conteos en BD y finaliza en `completed` liberando `active_slot` (`active_slot is None`).
     - `test_runner_failure_frees_slot`: runner que lanza excepción pasa a estado `failed`, guarda mensaje de error acotado sin tracebacks y libera el slot (`active_slot is None`), permitiendo una nueva ejecución.
     - `test_runner_cancellation_frees_slot`: tarea cancelada pasa a `interrupted`, libera `active_slot` y permite una nueva ejecución.
     - `test_startup_recovery_cleans_orphaned_runs`: registros en `pending` o `running` previos pasan a `interrupted` al ejecutar la recuperación de arranque, mientras que registros `completed` no se alteran.
     - `test_get_latest_and_get_by_id`: cubre respuestas 200 y 404 para ambos endpoints.
  2. Comprobar que no se realizan conexiones externas ni escrituras sobre las rutas de producción.

---

ACEPTACION
grep -q "catalog_sync_runs" src/db/models.py
grep -q "uq_catalog_sync_runs_active_slot" src/db/models.py
grep -q "revision.*e7f2a1b3c4d5" alembic/versions/e7f2a1b3c4d5_catalog_sync_runs.py
grep -q "down_revision.*d6e1f2a3b4c5" alembic/versions/e7f2a1b3c4d5_catalog_sync_runs.py
grep -q "on_page_progress" scripts/sync_catalog.py
test -f src/models/catalog_sync.py
test -f src/services/catalog_sync.py
grep -q "recover_interrupted_runs" src/services/catalog_sync.py
test -f src/api/catalog_sync.py
grep -q "api/v1/catalog-sync" src/main.py
grep -q "recover_interrupted_runs" src/main.py
test -f tests/test_catalog_sync_jobs.py
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
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
