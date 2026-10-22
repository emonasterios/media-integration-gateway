# Encargo: blindar integridad de `sources` en SQLite

## Objetivo

Impedir que vuelvan a aparecer fuentes huérfanas o duplicadas en la base SQLite del gateway, mediante cambios de código, esquema, migración y pruebas. Esta corrida NO debe desplegar ni modificar la base de producción.

## Premisas verificadas (2026-10-21)

- Repositorio canónico: `/home/emon/media-integration-gateway`, rama `main`, limpio y sincronizado con `origin/main` al despachar; HEAD `77dd486`.
- `src/db/database.py` crea el engine async SQLite sin instalar un listener que ejecute `PRAGMA foreign_keys=ON` en cada conexión.
- `src/db/models.py` define la FK `sources.media_id -> media.id`, pero `Source` no declara unicidad para `(provider, url)`.
- La migración inicial `alembic/versions/a4b9a06fc210_initial_migration.py` contiene la FK, pero tampoco una restricción única sobre `(provider, url)`.
- Auditoría de producción, solo lectura: existen 807 filas huérfanas en `sources`; 797 duplican proveedor+URL de una fuente válida y 10 no tienen contraparte vigente. Todas son `cuevana3`. `PRAGMA quick_check` fue correcto y la conexión inspeccionada tenía `foreign_keys=OFF`.
- El árbol actual incluye datos/artefactos locales ajenos al encargo; no borrarlos ni incorporarlos salvo que ya estén versionados y el cambio sea imprescindible.

## Alcance de implementación

1. Activar `PRAGMA foreign_keys=ON` de forma determinista para cada conexión SQLite creada por SQLAlchemy/aiosqlite, sin afectar otros motores.
2. Declarar en el modelo una restricción única explícita y estable sobre `sources(provider, url)`.
3. Crear una nueva migración Alembic compatible con SQLite que:
   - elimine primero solamente fuentes huérfanas (`media_id` inexistente);
   - consolide duplicados de `(provider, url)` conservando de forma determinista una fila válida (preferentemente el menor `id`);
   - agregue la restricción/índice único;
   - no elimine ninguna fila de `media`;
   - sea transaccional en la medida soportada por SQLite/Alembic y tenga downgrade razonable de la restricción (sin intentar resucitar datos limpiados).
4. Añadir pruebas focalizadas que demuestren:
   - toda conexión SQLite de la aplicación reporta `PRAGMA foreign_keys=1`;
   - insertar una fuente con `media_id` inexistente falla;
   - duplicar `(provider, url)` falla aunque cambie `media_id` u otros campos;
   - la migración parte de una base con duplicados y huérfanos, conserva medios válidos, limpia solo las fuentes inválidas/duplicadas y deja `PRAGMA foreign_key_check` sin resultados;
   - el esquema nuevo desde cero posee las mismas garantías.
5. Mantener compatibilidad con los flujos actuales de caché y sincronización. Si hoy algún flujo intenta insertar el mismo `(provider, url)` dos veces, corregirlo de manera idempotente y cubrirlo con prueba.

## Fuera de alcance / prohibiciones

- No conectarse con escritura a `vm-infra`.
- No borrar las 807 filas en producción.
- No desplegar, reiniciar contenedores ni ejecutar sincronizaciones reales.
- No copiar la base real al repositorio ni registrar datos de aplicación o secretos.
- No modificar `media` de producción ni introducir limpieza genérica que pueda borrar medios válidos.

## ACEPTACION

test -f alembic/versions/*sources*integrity*.py || test -n "$(grep -lE 'UniqueConstraint|create_unique_constraint|create_index' alembic/versions/*.py)"
. .venv/bin/activate && pytest -q tests/test_db.py tests/test_cache.py tests/test_catalog_sync.py
. .venv/bin/activate && pytest -q tests/
git diff --check

## Entrega esperada

Cambios pequeños y revisables, pruebas verdes y un commit/push automático de la fábrica. En el resumen final debe identificar la migración creada, explicar cómo activa FK por conexión y confirmar explícitamente que no tocó producción.

PREMISES

I El engine async actual se crea sin listener de conexión que active `PRAGMA foreign_keys=ON` — src/db/database.py:24
I `Source.media_id` declara una FK hacia `media.id` — src/db/models.py:35
I El modelo `Source` contiene `provider` y `url`, pero no declara `__table_args__` ni unicidad — src/db/models.py:30
I La migración inicial crea `sources` con FK y clave primaria, pero sin unicidad sobre `(provider, url)` — alembic/versions/a4b9a06fc210_initial_migration.py:51
I La sincronización actual contiene una limpieza explícita de fuentes huérfanas para residuos creados cuando SQLite no aplicó la FK — scripts/sync_catalog.py:270
