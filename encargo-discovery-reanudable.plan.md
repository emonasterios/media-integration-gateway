<!-- spec:9afb6b6555e6e2ea0ddbe85f9f0bb5c0 -->
# ENCARGO: Descubrimiento de Catálogo Reanudable y Seguro

## REGLAS OBLIGATORIAS DE EJECUCIÓN
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- Ejecutar y verificar que el proyecto compila y pasa pruebas tras cada paso.

---

## PASO 1: Mitigación de fallo de fondo y módulo de gestión de checkpoints atómicos (`src/services/catalog_checkpoint.py`)

### Fallo de fondo crítico a prevenir
Un crawler interrumpido a mitad de camino o una escritura no atómica puede generar un archivo corrupto o parcial. Si el script de sincronización intenta reconciliar un checkpoint parcial o corrupto, lo interpretará como el catálogo completo y activará la eliminación de miles de registros válidos de la base de datos. Por lo tanto, el sistema de checkpoint debe garantizar atonicidad absoluta mediante escritura en archivo temporal y reemplazo (`os.replace`), y debe prohibir por diseño cualquier reconciliación si el estado no es estrictamente `complete`.

### Archivo a crear
- `src/services/catalog_checkpoint.py`

### Qué debe quedar en `src/services/catalog_checkpoint.py`
1. Estructura de datos del checkpoint (ej. dataclass o Pydantic model `CatalogCheckpoint`):
   - `version`: int (ej. 1).
   - `provider`: str (ej. "cuevana3").
   - `category`: Optional[str].
   - `initial_path`: str.
   - `next_page`: Optional[str].
   - `pages_completed`: list[int] o int.
   - `items`: list[dict] deduplicados por `(provider, provider_id)` con metadatos del listado (`provider_id`, `title`, `url`, `poster`, `category`, etc.).
   - `status`: str, con valores estrictos `"incomplete"` o `"complete"`.
2. Función `save_checkpoint(checkpoint: CatalogCheckpoint, target_path: Path | str) -> None`:
   - Escribe primero en un archivo temporal en el mismo directorio (`target_path.with_suffix(".tmp")` o `NamedTemporaryFile(dir=target_path.parent, delete=False)`).
   - Realiza un flush y sync del archivo.
   - Reemplaza atómicamente el archivo final con `os.replace` para evitar truncamiento ante caídas.
3. Función `load_checkpoint(target_path: Path | str) -> CatalogCheckpoint`:
   - Lee y valida el JSON.
   - Si el archivo no existe, está corrupto o tiene una versión incompatible, lanza excepción descriptiva (`CheckpointError`, `CheckpointCorruptedError`).
4. Función `validate_for_reconciliation(checkpoint: CatalogCheckpoint, expected_provider: str, expected_category: Optional[str] = None) -> None`:
   - Valida que `checkpoint.status == "complete"`. Si es `"incomplete"`, lanza excepción estricta (`IncompleteSnapshotError`) que impida continuar.
   - Valida que `checkpoint.provider == expected_provider` y coincida la categoría. Si no coincide, lanza excepción (`IncompatibleCheckpointError`).
5. Función `add_items_deduplicated(existing_items: list[dict], new_items: list[dict]) -> list[dict]`:
   - Deduplica elementos por la clave compuesta `(item["provider"], item["provider_id"])` preservando orden.

---

## PASO 2: Descubrimiento reanudable página a página en el adaptador (`src/adapters/cuevana3.py`)

### Archivo a modificar
- `src/adapters/cuevana3.py`

### Qué debe quedar en `src/adapters/cuevana3.py`
1. Importar las utilidades de `src/services/catalog_checkpoint.py`.
2. Mantener intacta la signatura y el funcionamiento de `Cuevana3Adapter.get_catalog(category: Optional[str] = None) -> list[MediaItem]` para preservar retrocompatibilidad con tests existentes.
3. Agregar método `discover_resumable(self, checkpoint_path: Path | str, category: Optional[str] = None, page_limit: Optional[int] = None) -> CatalogCheckpoint`:
   - Si `checkpoint_path` existe, cargar con `load_checkpoint`. Si su estado era `complete`, puede retornar el checkpoint existente.
   - Si está `incomplete`, reanudar desde `checkpoint.next_page` sin volver a solicitar las URLs o páginas ya registradas en `pages_completed`.
   - Si no existe checkpoint, inicializar uno nuevo con `status="incomplete"`, `provider="cuevana3"`, `category=category`, `initial_path` configurada y `next_page` inicial.
   - Iterar página a página con los reintentos existentes (3 intentos HTTP con backoff exponencial).
   - Tras cada página descargada y parseada con éxito:
     * Extraer los elementos y deduplicarlos en el acumulador.
     * Actualizar `pages_completed` y el nuevo enlace `next_page` (usando el selector `a.next.page-numbers[href]`).
     * Si no hay más páginas siguientes (`next_page is None` o límite alcanzado sin páginas restantes), marcar `status="complete"`.
     * Persistir de inmediato y de forma atómica el progreso mediante `save_checkpoint`.
   - Si se produce un error de red no recuperable o interrupción, el último checkpoint guardado (`status="incomplete"`) queda íntegro en disco y se propaga el error sin destruir el progreso previo.

---

## PASO 3: Integración de subcomandos y protecciones en CLI (`scripts/sync_catalog.py`)

### Archivo a modificar
- `scripts/sync_catalog.py`

### Qué debe quedar en `scripts/sync_catalog.py`
1. Incorporar argumentos en el parser CLI (manteniendo compatibilidad total con opciones actuales `--dry-run`, `--limit`, `--category`):
   - `--checkpoint-path`: ruta del archivo de checkpoint (por defecto `data/cuevana3_checkpoint.json`).
   - `--discover-only`: ejecuta únicamente la fase de rastreo y guardado de checkpoint, sin abrir sesión de base de datos ni reconciliar.
   - `--status`: muestra el resumen del checkpoint actual (proveedor, categoría, páginas completadas, total de ítems descubiertos, estado `complete`/`incomplete`, próxima página) y finaliza con código 0.
   - `--from-checkpoint`: reconcilia el catálogo de la base de datos exclusivamente leyendo los ítems desde un checkpoint en disco en lugar de rastrear en vivo.
2. Barrera estricta antes de abrir base de datos:
   - Al usar `--from-checkpoint` (o en el flujo de reconciliación tras descubrimiento), invocar `validate_for_reconciliation()`.
   - Si el checkpoint tiene `status != "complete"` o el archivo está ausente/corrupto, imprimir error en `stderr` y abortar inmediatamente con código de salida distinto de cero, SIN abrir `AsyncSessionLocal` y con CERO escrituras en la base de datos.
3. Mantener intactas las protecciones existentes:
   - `--dry-run` hace rollback.
   - `--limit` desactiva eliminación masiva.
   - Umbral de bajas de seguridad (>25%) bloquea la reconciliación salvo confirmación.

---

## PASO 4: Pruebas unitarias e integración del checkpoint y reanudación (`tests/test_catalog_checkpoint.py` y `tests/test_cuevana3.py`)

### Archivos a tocar
- `tests/test_catalog_checkpoint.py` (crear)
- `tests/test_cuevana3.py` (modificar agregando pruebas de reanudación)

### Qué debe quedar en `tests/test_catalog_checkpoint.py`
Pruebas exhaustivas para el gestor de checkpoints:
1. `test_atomic_save_and_load`: verifica que `save_checkpoint` persiste los metadatos y `load_checkpoint` los reconstruye fielmente.
2. `test_atomic_write_resistance_to_corruption`: simula un archivo temporal corrupto/interrumpido y comprueba que el checkpoint previo permanece inalterado.
3. `test_incomplete_status_blocks_reconciliation`: un checkpoint con `status="incomplete"` arroja excepción ante `validate_for_reconciliation` y garantiza cero escrituras.
4. `test_incompatible_provider_or_category`: valida el rechazo ante proveedor distinto o categoría no coincidente.
5. `test_deduplication_by_provider_and_id`: verifica deduplicación estable de ítems en múltiples tandas por `(provider, provider_id)`.

### Qué debe quedar en `tests/test_cuevana3.py`
Pruebas del crawler reanudable con mocks de respuestas HTTP:
1. `test_discover_resumable_completes_over_20_pages`: simula más de 20 páginas con paginación `next`, valida que recorra todas, escriba checkpoint en cada una y termine con `status="complete"`.
2. `test_intermediate_failure_saves_incomplete_checkpoint`: simula fallo de red en la página 15; valida que el checkpoint en disco conserve 14 páginas completadas, los ítems confirmados y estado `"incomplete"`.
3. `test_resume_from_incomplete_checkpoint`: partiendo del checkpoint anterior en página 15, reanuda el proceso y comprueba que NO se vuelven a solicitar las páginas 1 a 14 y que avanza hasta completar.
4. `test_cli_sync_catalog_incomplete_no_db_write`: simula la invocación de `sync_catalog.py --from-checkpoint` con un snapshot incompleto y comprueba que aborta sin realizar cambios en BD.

---

## PASO 5: Documentación de procedimientos y formato de checkpoint (`docs/operations/catalog-sync-2026-10-21.md`)

### Archivo a modificar
- `docs/operations/catalog-sync-2026-10-21.md`

### Qué debe quedar en `docs/operations/catalog-sync-2026-10-21.md`
1. Registrar el diseño del checkpoint:
   - Ruta por defecto: `data/cuevana3_checkpoint.json`.
   - Estructura JSON: `version`, `provider`, `category`, `next_page`, `pages_completed`, `items`, `status`.
2. Procedimiento de recuperación ante fallos tardíos (ej. fallo en página 860):
   - Comando para consultar estado actual: `python scripts/sync_catalog.py --status`.
   - Comando para reanudar el descubrimiento: `python scripts/sync_catalog.py --discover-only`.
   - Comando para reconciliar en dry-run una vez completado: `python scripts/sync_catalog.py --from-checkpoint --dry-run`.
   - Comando para reconciliación final efectiva: `python scripts/sync_catalog.py --from-checkpoint`.
3. Documentar la garantía de protección: un checkpoint `incomplete` jamás es aceptado por el proceso de reconciliación en la base de datos.

---

ACEPTACION
test -f src/services/catalog_checkpoint.py
test -f tests/test_catalog_checkpoint.py
grep -q "CatalogCheckpoint" src/services/catalog_checkpoint.py
grep -q "os.replace" src/services/catalog_checkpoint.py
grep -q "validate_for_reconciliation" src/services/catalog_checkpoint.py
grep -q "discover_resumable" src/adapters/cuevana3.py
grep -q -- "--discover-only" scripts/sync_catalog.py
grep -q -- "--from-checkpoint" scripts/sync_catalog.py
grep -q -- "--status" scripts/sync_catalog.py
grep -q "cuevana3_checkpoint.json" docs/operations/catalog-sync-2026-10-21.md
cd /home/emon/media-integration-gateway && . .venv/bin/activate && python scripts/sync_catalog.py --help
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest -q tests/test_cuevana3.py
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest -q tests -k 'checkpoint or resume or resumable or discovery'

PREMISES

- I1 interface — `Cuevana3Adapter.get_catalog(category: Optional[str] = None) -> list[MediaItem]` — `src/adapters/cuevana3.py:135`.
- L1 literal — la ruta inicial es `/peliculas/` sin categoría o `/genero/{category}/` con categoría — `src/adapters/cuevana3.py:137`.
- P1 precedent — el rastreo actual acumula elementos en memoria, deduplica por `provider_id` y avanza mediante `a.next.page-numbers[href]`; es el comportamiento que la fase durable debe preservar página a página — `src/adapters/cuevana3.py:138`, `src/adapters/cuevana3.py:205`, `src/adapters/cuevana3.py:227`.
- P2 precedent — cada página conserva tres intentos HTTP y pausa creciente entre reintentos; al agotarlos lanza `CatalogCrawlError` antes de devolver catálogo — `src/adapters/cuevana3.py:152`, `src/adapters/cuevana3.py:170`.
- P3 precedent — la sincronización llama primero a `get_catalog()`, construye el snapshot y solo después abre `AsyncSessionLocal`; separar descubrimiento de reconciliación debe conservar esa barrera — `scripts/sync_catalog.py:35`, `scripts/sync_catalog.py:38`, `scripts/sync_catalog.py:53`.
- L2 literal — la identidad usada por sincronización es `PROVIDER = "cuevana3"` junto con `item.provider_id`, y las fuentes persistidas guardan ese proveedor y el `provider_id` en `url` — `scripts/sync_catalog.py:24`, `scripts/sync_catalog.py:39`, `scripts/sync_catalog.py:97`.
- P4 precedent — `--limit` deshabilita borrados, `--dry-run` hace rollback y la protección de bajas masivas rechaza una proporción superior a 25% salvo autorización explícita; estas protecciones deben mantenerse — `scripts/sync_catalog.py:46`, `scripts/sync_catalog.py:64`, `scripts/sync_catalog.py:147`.
- P5 precedent — el registro operativo constata fallo en página 860, ausencia de snapshot completo y ninguna ejecución real posterior — `docs/operations/catalog-sync-2026-10-21.md:5`, `docs/operations/catalog-sync-2026-10-21.md:10`, `docs/operations/catalog-sync-2026-10-21.md:13`.
- L3 literal — el estado observado documenta 903 registros en `media`; este encargo no autoriza modificar ese estado — `docs/operations/catalog-sync-2026-10-21.md:19`.
- L4 literal — la verificación del repo ejecuta `pytest tests/ -v` — `.fabrica-verify:1`.
- P6 precedent — la aceptación permanente comprueba que las lecturas Xtream con BD configurada salgan de SQLite — `.fabrica-aceptacion:3`.
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
