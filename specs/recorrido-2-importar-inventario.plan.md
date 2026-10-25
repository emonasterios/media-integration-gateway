<!-- spec:897a5dc4cf840358cb1b926d7eafedcb -->
REGLAS OBLIGATORIAS PARA EL EJECUTOR:
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

## PASO 1: Servicio de importación transaccional e idempotente en `src/services/catalog_inventory.py`

FALLO DE FONDO QUE HARÍA REVENTAR LA EJECUCIÓN SI NO SE CORRIGE PRIMERO:
En el catálogo operativo (`media_gateway.db`), la tabla `media` NO tiene restricción de unicidad por título ni año (existen obras homónimas legítimas en el inventario), mientras que la tabla `sources` impone unicidad técnica en `(provider, url)`. Si el importador intenta insertar en `media` antes de verificar si la fuente ya existe en `sources`, cada reejecución creará filas huérfanas duplicadas en `media`, rompiendo la idempotencia obligatoria (cero inserciones en una 2ª corrida). Asimismo, si no se exige `--catalog-db` explícito o se usa autocommit, `--dry-run` persistirá cambios o ante un fallo quedará una carga parcial rota.

ARCHIVO A EDITAR:
`src/services/catalog_inventory.py`

QUÉ DEBE QUEDAR:
Leer `src/services/catalog_inventory.py` y añadir (sin modificar las clases ni funciones ya existentes) la función `import_inventory_to_catalog(inventory_db_path: str, catalog_db_path: str, dry_run: bool = False) -> dict` con la siguiente lógica:

1. Validaciones previas del inventario (rechazo inmediato antes de tocar el destino):
   - Abrir conexión de solo lectura a `inventory_db_path`.
   - Consultar la última corrida en `runs` (ordenada por `id DESC LIMIT 1`). Si no existe o su campo `status != 'complete'`, lanzar `ValueError("El inventario no tiene una corrida completada")`.
   - Consultar la tabla `categories`: si alguna fila tiene `status != 'complete'`, o si `confirmed_page != last_page` (o si `confirmed_pages != total_pages`), lanzar `ValueError("Hay categorías incompletas o con discrepancia de páginas")`.
   - Si no hay filas en `movies`, retornar resumen con ceros.

2. Carga y mapeo en memoria de películas y categorías:
   - Extraer de `movies`: `provider`, `provider_id`, `title`, `year`, `poster_url`, `page_url`.
   - Hacer join con `movie_categories` y `categories` sobre `(provider, category_slug)` para obtener el nombre visible `categories.name` (NO el slug).
   - Para cada `(provider, provider_id)`, agrupar los nombres visibles de categorías únicos y ordenados alfabéticamente en un JSON determinista: `json.dumps(sorted(list(set(cat_names))), ensure_ascii=False)`.

3. Transacción atómica en el catálogo destino:
   - Conectar a `catalog_db_path` usando `sqlite3.connect(catalog_db_path, isolation_level=None)` (o transaccional explícito).
   - Ejecutar `PRAGMA foreign_keys = ON;` y abrir transacción con `BEGIN IMMEDIATE`.
   - Inicializar contadores: `read_inventory = len(movies)`, `read_category_relations`, `inserted = 0`, `updated = 0`, `unchanged = 0`.
   - Para cada película del inventario:
     - Buscar en `sources`: `SELECT id, media_id FROM sources WHERE provider = ? AND url = ?` usando `provider` y `url = provider_id`.
     - Si la fuente YA EXISTE:
       - Recuperar su `media_id`.
       - Comprobar si `media(title, year, poster_url, genres)` o `sources(page_url)` han cambiado.
       - Si cambiaron: actualizar `media` (`title`, `year`, `poster_url`, `genres`, `updated_at = datetime.now(timezone.utc).isoformat()`) y actualizar `sources` (`page_url = movie.page_url`, `catalog_presence = 'present'`, `last_seen_at = datetime.now(timezone.utc).isoformat()`, `missing_since = NULL`, `consecutive_misses = 0`). Incrementar `updated`.
       - Si no cambiaron: asegurar que `sources.catalog_presence = 'present'`, `sources.last_seen_at = now`, `missing_since = NULL`, `consecutive_misses = 0`. Incrementar `unchanged`.
     - Si la fuente NO EXISTE:
       - Insertar en `media`: `(title, year, media_type, poster_url, genres, created_at, updated_at)` con `media_type = 'movie'`.
       - Obtener el `lastrowid` generado (`new_media_id`).
       - Insertar en `sources`: `(media_id, provider, url, page_url, catalog_presence, last_seen_at, missing_since, consecutive_misses)` con `url = provider_id`, `catalog_presence = 'present'`, `last_seen_at = now`, `missing_since = NULL`, `consecutive_misses = 0`.
       - Incrementar `inserted`.
   - No marcar `missing` ni borrar ninguna fila preexistente en `media` o `sources`.
   - Si `dry_run is True`: ejecutar `ROLLBACK` y fijar `status = 'dry-run/rolled-back'`.
   - Si `dry_run is False`: ejecutar `COMMIT` y fijar `status = 'committed'`.
   - Si ocurre cualquier excepción en el bloque: ejecutar `ROLLBACK` y relanzar la excepción.
   - Retornar diccionario de resumen: `{"inventory_read": read_inventory, "category_relations_read": read_category_relations, "inserted": inserted, "updated": updated, "unchanged": unchanged, "status": status}`.

El archivo debe quedar compilando sin errores de sintaxis ni de importación.

## PASO 2: Conexión de la acción CLI en `scripts/sync_catalog.py`

ARCHIVO A EDITAR:
`scripts/sync_catalog.py`

QUÉ DEBE QUEDAR:
Leer `scripts/sync_catalog.py` y registrar la acción CLI para la importación del inventario:
1. Importar `import_inventory_to_catalog` desde `src.services.catalog_inventory`.
2. Añadir los argumentos al parser de argumentos:
   - `--inventory-import`: flag booleano (`action="store_true"`, ayuda: "Importar inventario validado del recorrido 1 al catálogo operativo").
   - `--inventory-db`: ruta string al SQLite origen del inventario.
   - `--catalog-db`: ruta string al SQLite destino del catálogo operativo.
   - Verificar si `--dry-run` ya existe en el parser; si no existe, añadir `--dry-run` (`action="store_true"`).
3. En la rutina de despacho del CLI:
   - Si `--inventory-import` está presente:
     - Validar que tanto `--inventory-db` como `--catalog-db` hayan sido proporcionados obligatoriamente. Si falta alguno, mostrar error en stderr y salir con código distinto de 0 (ej. `sys.exit(1)`).
     - Ejecutar `summary = import_inventory_to_catalog(inventory_db_path=args.inventory_db, catalog_db_path=args.catalog_db, dry_run=args.dry_run)`.
     - Imprimir por stdout el resumen estructurado e inequívoco con los campos:
       `Inventario leído: {summary['inventory_read']}`,
       `Relaciones de categorías: {summary['category_relations_read']}`,
       `Insertados: {summary['inserted']}`,
       `Actualizados: {summary['updated']}`,
       `Sin cambios: {summary['unchanged']}`,
       `Estado: {summary['status']}`.
     - Finalizar la ejecución sin invocar scraping ni resolvers.

El archivo debe quedar compilando y respondiendo a `python3 scripts/sync_catalog.py --help`.

## PASO 3: Suite de pruebas en `tests/test_catalog_inventory_import.py`

ARCHIVO A CREAR:
`tests/test_catalog_inventory_import.py`

QUÉ DEBE QUEDAR:
Crear `tests/test_catalog_inventory_import.py` con pruebas unitarias y de integración sobre bases SQLite temporales creadas en `tmp_path`, sin tocar red ni `/home/emon/media-integration-gateway/media_gateway.db`:

1. Fixtures para crear:
   - Base de inventario origen con tablas `runs`, `categories`, `movies`, `movie_categories`.
   - Base de catálogo operativo destino con tablas `media` y `sources` según el esquema de `src/db/models.py`.

2. Casos de prueba obligatorios:
   - `test_reject_incomplete_run`: falla con `ValueError` si la última corrida en `runs` no tiene `status='complete'`.
   - `test_reject_category_incomplete_or_page_mismatch`: falla si una categoría tiene `status != 'complete'` o `confirmed_page != last_page`.
   - `test_import_movies_canonical_url_and_visible_genres`: importa una película, verifica que `sources.url == provider_id`, `sources.page_url` tiene la URL canónica, `sources.catalog_presence == 'present'`, `sources.consecutive_misses == 0`, `sources.missing_since is None`, y `media.genres` contiene el JSON determinista con el nombre visible de las categorías (no el slug).
   - `test_movie_in_multiple_categories_deduplicated`: una película asociada a 3 categorías en `movie_categories` genera exactamente 1 fila en `media`, 1 fila en `sources`, y su `media.genres` contiene los 3 nombres ordenados.
   - `test_preserves_unrelated_existing_rows`: filas previas de otro proveedor u otra película en `media` y `sources` no se modifican ni se eliminan.
   - `test_update_existing_source_idempotent`: si la fuente ya existe en `sources`, actualiza metadatos sin crear otra fila en `media` ni en `sources`. Una segunda ejecución produce 0 inserciones (`inserted == 0`) y el conteo de filas en `media` y `sources` permanece exactamente igual.
   - `test_dry_run_leaves_destination_unmodified`: ejecutar con `dry_run=True` reporta el resumen de cambios calculados pero la base destino queda idéntica (cero filas persistidas).
   - `test_error_during_import_rolls_back_completely`: simular un fallo a mitad de la inserción y verificar que la transacción se revierte por completo (cero filas parciales).
   - `test_cli_inventory_import_help_and_invocation`: verificar mediante `subprocess` o `runner` que `scripts/sync_catalog.py --inventory-import` exige `--inventory-db` y `--catalog-db`, y que ejecuta la importación exitosamente imprimiendo el resumen.

El proyecto debe quedar compilando y pasando `pytest -q tests/test_catalog_inventory_import.py tests/test_catalog_inventory.py`.

ACEPTACION
test -f tests/test_catalog_inventory_import.py
grep -q "def import_inventory_to_catalog" src/services/catalog_inventory.py
grep -q "catalog_presence" src/services/catalog_inventory.py
grep -q "last_seen_at" src/services/catalog_inventory.py
grep -q "consecutive_misses" src/services/catalog_inventory.py
grep -q "import_inventory_to_catalog" scripts/sync_catalog.py
grep -q -- "--inventory-import" scripts/sync_catalog.py
grep -q -- "--inventory-db" scripts/sync_catalog.py
grep -q -- "--catalog-db" scripts/sync_catalog.py
grep -q "test_reject_incomplete_run" tests/test_catalog_inventory_import.py
grep -q "test_update_existing_source_idempotent" tests/test_catalog_inventory_import.py
grep -q "test_dry_run_leaves_destination_unmodified" tests/test_catalog_inventory_import.py
python3 scripts/sync_catalog.py --help | grep -q -- "--inventory-import"
python3 -m pytest -q tests/test_catalog_inventory_import.py tests/test_catalog_inventory.py

PREMISES

I El inventario dedicado usa `movies` con clave primaria `(provider, provider_id)` y `movie_categories` con la misma identidad más `category_slug` — src/services/catalog_inventory.py:44-67
I El recorrido 1 exige deduplicar por `(provider, provider_id)` y no modificar el catálogo público — specs/recorrido-1-inventario-categorias.md:24-31,52-53
I El catálogo operativo representa la identidad de proveedor mediante la restricción única `(provider, url)` en `sources` — src/db/models.py:30-38
I El catálogo operativo almacena géneros como texto JSON dentro de `media.genres` — src/db/models.py:12-24
I Las lecturas públicas solo publican fuentes `catalog_presence='present'` — src/api/xtream.py:33-39
I La SQLite real validada el 2026-10-25 contiene 18/18 categorías completas, 44,271 relaciones y 19,282 filas únicas por provider_id/URL — data/cuevana3_inventory.sqlite (validación operativa externa; no versionar la base)
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
