<!-- spec:3fb53c7a29df8580857be087787a1628 -->
REGLAS OBLIGATORIAS:
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

ADVERTENCIA DE FONDO (CRÍTICO):
El flujo heredado depende de la etiqueta `a.next` para avanzar en la paginación. Si se sigue usando `a.next` para este inventario, el proceso solicitará páginas inexistentes (`last_page + 1`), entrará en bucles o fallará silenciosamente. El límite de páginas de cada categoría DEBE determinarse exclusivamente a partir del número máximo anunciado en la paginación numérica (`a.page-link` / `.page-numbers`) leído en la primera página, recorriendo estrictamente `1..last_page` sin solicitar jamás `last_page + 1`. Asimismo, no deben abrirse fichas individuales (`get_details`) ni resolvers de video, ya que provocarían bloqueos HTTP y excederían la memoria y el alcance del inventario.

## PASO 1
- Archivo a modificar: `src/adapters/cuevana3.py`
- Objetivo: Añadir funciones de extracción para categorías del menú y para el límite de paginación numérico, sin alterar los métodos existentes.
- Qué debe quedar:
  1. En `src/adapters/cuevana3.py`, añadir una función o método `extract_menu_categories(html: str, base_url: str = "https://cuevana3i.cc") -> list[dict]`:
     - Parsea el HTML buscando enlaces con el patrón `/genero/<slug>/`.
     - Normaliza el `slug` (en minúsculas y sin barras al inicio o final).
     - Deduplica por `slug` y devuelve una lista de diccionarios con `slug`, `name` (texto visible limpio) y `url` canónica absoluta.
  2. En `src/adapters/cuevana3.py`, añadir una función o método `extract_last_page(html: str) -> int`:
     - Parsea los enlaces o elementos de paginación (`a.page-link`, `.page-numbers`, etc.).
     - Extrae todos los números enteros de las páginas anunciadas y devuelve el valor entero máximo encontrado. Si no hay paginación numérica, devuelve `1`.
     - No depender de `a.next` para fijar el límite.
  3. Comprobar que el archivo compila sin errores de sintaxis y que las pruebas previas siguen pasando.

## PASO 2
- Archivo a crear: `src/services/catalog_inventory.py`
- Objetivo: Crear la capa de base de datos SQLite dedicada y transaccional para el inventario y consulta de estado fuera de línea.
- Qué debe quedar:
  1. En `src/services/catalog_inventory.py`, implementar la clase `CatalogInventoryDB` usando el módulo estándar `sqlite3`:
     - Método `__init__(db_path: str)`: guarda la ruta y asegura la creación del directorio padre si no existe.
     - Método `init_db()`: crea las tablas con esquema relacional si no existen:
       - `runs`: `id INTEGER PRIMARY KEY AUTOINCREMENT`, `status TEXT DEFAULT 'in_progress'`, `created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP`, `updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP`, `error TEXT`.
       - `categories`: `slug TEXT PRIMARY KEY`, `name TEXT`, `url TEXT`, `last_page INTEGER DEFAULT 0`, `confirmed_page INTEGER DEFAULT 0`, `status TEXT DEFAULT 'pending'`, `error TEXT`.
       - `movies`: `provider TEXT`, `provider_id TEXT`, `title TEXT`, `year INTEGER`, `url TEXT`, `poster TEXT`, `PRIMARY KEY (provider, provider_id)`.
       - `movie_categories`: `provider TEXT`, `provider_id TEXT`, `category_slug TEXT`, `PRIMARY KEY (provider, provider_id, category_slug)`, `FOREIGN KEY (category_slug) REFERENCES categories(slug)`.
     - Método `save_page_items(category_slug: str, page_number: int, items: list[dict])`:
       - Ejecuta una transacción atómica por página.
       - Inserta o ignora duplicados en `movies` mediante `INSERT INTO movies (provider, provider_id, title, year, url, poster) VALUES (...) ON CONFLICT(provider, provider_id) DO UPDATE SET title=excluded.title, year=excluded.year, poster=excluded.poster`.
       - Inserta relaciones en `movie_categories` con `INSERT OR IGNORE INTO movie_categories (provider, provider_id, category_slug) VALUES (...)`.
       - Actualiza en `categories`: `confirmed_page = page_number`, `status = 'in_progress'` (o 'complete' si `page_number == last_page`).
     - Método `get_status() -> dict`:
       - Consulta SQLite sin llamadas a la red.
       - Retorna un diccionario con:
         - `run_status`: estado del run actual (`'complete'`, `'incomplete'`, `'in_progress'`).
         - `current_category`: slug de la categoría actualmente en curso o None.
         - `confirmed_page`: última página confirmada de la categoría en curso.
         - `last_page`: última página fijada de la categoría en curso.
         - `categories_completed`: conteo de categorías con `status = 'complete'`.
         - `categories_total`: conteo total de categorías registradas.
         - `unique_movies_count`: total de registros en la tabla `movies`.
         - `last_error`: último mensaje de error registrado en `runs` o en la última categoría fallida.
  2. Comprobar que el archivo compila sin errores de sintaxis.

## PASO 3
- Archivo a modificar: `src/services/catalog_inventory.py`
- Objetivo: Implementar el servicio de orquestación reanudable del inventario por categorías.
- Qué debe quedar:
  1. En `src/services/catalog_inventory.py`, implementar la clase `CatalogInventoryService`:
     - Método `run_inventory(db_path: str, adapter) -> dict`:
       - Inicializa `CatalogInventoryDB(db_path).init_db()`.
       - Si el estado de la corrida en la DB ya es `complete`, retorna el estado sin realizar peticiones de red.
       - Si no hay categorías en la base de datos:
         - Descarga la página `/peliculas/` usando `adapter`.
         - Usa `extract_menu_categories` de `src.adapters.cuevana3` para obtener las categorías deduplicadas por `slug`.
         - Registra las categorías en la tabla `categories` con estado `pending`.
       - Itera sobre las categorías:
         - Si una categoría ya tiene `status = 'complete'`, omitirla sin volver a descargarla.
         - Si `last_page` no está fijado (`last_page <= 0`):
           - Descarga la página 1 de la categoría (`/genero/<slug>/`).
           - Extrae `last_page` numérico con `extract_last_page`.
           - Guarda `last_page` en la base de datos.
         - Determina la página de reanudación: `start_page = confirmed_page + 1`.
         - Si `start_page <= last_page`, recorre de forma determinista `page` en `range(start_page, last_page + 1)`:
           - NUNCA solicita `last_page + 1` ni sigue `a.next`.
           - Descarga el HTML de la página `page`.
           - Extrae los ítems de listado usando el parser de listado existente del adaptador (`provider`, `provider_id`, `url`, `title`, `year`, `poster`). Excluye de forma estricta las series (entradas con URL conteniendo `/serie/`). No llama a `get_details` ni resolvers.
           - Si la página está vacía antes de `last_page` o se produce un error HTTP/parseo:
             - Registra el error en la categoría y en el run.
             - Marca la categoría como `incomplete` y el run como `incomplete`.
             - Retorna el estado actual sin borrar el progreso confirmado.
           - Si la página contiene ítems válidos, persiste la página con `db.save_page_items(category_slug, page, items)`.
         - Si todas las páginas `1..last_page` fueron confirmadas, marca la categoría como `complete`.
       - Si todas las categorías en la DB quedan con `status = 'complete'`, marca el run como `complete`.
     - Función auxiliar o método `get_inventory_status(db_path: str) -> dict` que exponga `CatalogInventoryDB(db_path).get_status()` sin red.
  2. Comprobar que el archivo compila sin errores de sintaxis.

## PASO 4
- Archivo a modificar: `scripts/sync_catalog.py`
- Objetivo: Conectar los comandos de inventario (`--inventory-discover`, `--inventory-status`, `--inventory-db`) en el CLI.
- Qué debe quedar:
  1. En `scripts/sync_catalog.py`, dentro de la configuración de argumentos de línea de comandos:
     - Añadir `--inventory-discover` (acción booleana / `action="store_true"`, help="Iniciar o reanudar inventario de películas por categorías").
     - Añadir `--inventory-status` (acción booleana / `action="store_true"`, help="Consultar estado del inventario SQLite sin acceder a la red").
     - Añadir `--inventory-db` (tipo string, default="data/cuevana3_inventory.sqlite", help="Ruta del archivo SQLite del inventario").
  2. En la ejecución del CLI:
     - Si se invoca `--inventory-status`:
       - Invoca `get_inventory_status(args.inventory_db)` de `src.services.catalog_inventory`.
       - Imprime por consola los campos: estado de la corrida, categoría actual, página confirmada/última, categorías completas/total, películas únicas y último error.
       - Termina con código 0 sin tocar la red.
     - Si se invoca `--inventory-discover`:
       - Instancia `Cuevana3Adapter` y `CatalogInventoryService`.
       - Ejecuta `service.run_inventory(args.inventory_db, adapter)`.
       - Muestra el resumen del estado obtenido.
  3. No alterar ni renombrar las opciones heredadas existentes (`--category`, `--discover-only`, etc.).
  4. Comprobar que `python scripts/sync_catalog.py --help` muestra las tres nuevas opciones y que el script no revienta al ejecutarse con `--help`.

## PASO 5
- Archivo a crear: `tests/test_catalog_inventory.py`
- Objetivo: Crear la suite de pruebas unitarias y de integración sin red para validar el inventario.
- Qué debe quedar:
  1. En `tests/test_catalog_inventory.py`, escribir pruebas con HTML simulado usando `unittest.mock` o fixtures:
     - `test_discover_and_deduplicate_categories_from_menu`: verifica que parsea `/genero/<slug>/` deduplicando por slug y preservando nombre y URL canónica.
     - `test_pagination_extracts_last_page_and_limits_strictly`: verifica que extrae el número más alto de `a.page-link` / `.page-numbers` y nunca solicita `last_page + 1`.
     - `test_resume_incomplete_category_skips_confirmed_pages`: simula una categoría con páginas 1 y 2 confirmadas de 4, comprobando que reanuda directamente en la página 3.
     - `test_skip_completed_categories`: verifica que una categoría con estado `complete` no realiza peticiones HTTP.
     - `test_deduplicate_movies_preserve_multiple_categories`: verifica que una película presente en dos categorías se guarda una sola vez en `movies` y mantiene ambas asociaciones en `movie_categories`.
     - `test_exclude_series`: verifica que los elementos con URL de serie se descartan.
     - `test_premature_empty_page_or_error_marks_incomplete`: simula un error HTTP o respuesta vacía antes de `last_page`, comprobando que no borra el progreso confirmado y deja el run y la categoría como `incomplete`.
     - `test_run_marks_complete_only_when_all_categories_finish`: comprueba que el run pasa a `complete` únicamente tras completar todas las categorías.
     - `test_status_query_works_offline`: verifica que la consulta de estado lee de SQLite sin realizar peticiones de red.
     - `test_no_detail_or_playback_calls`: comprueba que durante todo el recorrido no se invocan métodos de detalles individuales ni resolvers de reproducción.
  2. Ejecutar la suite de pruebas completa y verificar que todos los tests pasen.

ACEPTACION
test -f src/services/catalog_inventory.py
test -f tests/test_catalog_inventory.py
grep -q "def extract_menu_categories" src/adapters/cuevana3.py
grep -q "def extract_last_page" src/adapters/cuevana3.py
grep -q "class CatalogInventoryDB" src/services/catalog_inventory.py
grep -q "class CatalogInventoryService" src/services/catalog_inventory.py
grep -q -- "--inventory-discover" scripts/sync_catalog.py
grep -q -- "--inventory-status" scripts/sync_catalog.py
grep -q -- "--inventory-db" scripts/sync_catalog.py
python3 scripts/sync_catalog.py --help | grep -q -- '--inventory-discover'
python3 scripts/sync_catalog.py --help | grep -q -- '--inventory-status'
python3 -m pytest -q tests/test_catalog_inventory.py tests/test_catalog_sync.py tests/test_catalog_checkpoint.py tests/test_cuevana3.py

PREMISES

I El flujo actual inicia en `/peliculas/` o una sola categoría y depende de la paginación de esa ruta — src/adapters/cuevana3.py:287-326
I El flujo actual selecciona `a.next.page-numbers[href]` para decidir la página siguiente — src/adapters/cuevana3.py:499-519
I El parser actual ya distingue series por la URL y películas por defecto — src/adapters/cuevana3.py:472-486
I El checkpoint actual contiene la lista completa de ítems en JSON y se reemplaza atómicamente — src/services/catalog_checkpoint.py:54-102
I El CLI actual ofrece una sola categoría mediante `--category` y un modo `--discover-only` — scripts/sync_catalog.py:469-526
I El HTML vivo verificado el 2026-10-25 anunció 18 enlaces únicos `/genero/` en `/peliculas/`, página final 434 para películas y página final 125 para Acción — https://cuevana3i.cc/peliculas/ y https://cuevana3i.cc/genero/accion/
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
