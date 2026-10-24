<!-- spec:b57928729270bf28ce19f64d24fd6cb2 -->
# ENCARGO: Estado persistente de presencia de fuentes — unidad 1 (esquema)

## REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- No modificar `scripts/sync_catalog.py`, adapters, resolvers, rutas API ni lógica de reproducción.
- No introducir borrado físico ni política automática de retiro.
- La migración debe preservar todas las filas existentes de `media` y `sources`.
- SQLite existente debe poder subir a `head`, bajar una revisión y volver a subir sin tocar `data/gateway.db`.

## PASO 1: Ampliar el modelo Source en src/db/models.py

Archivo a modificar:
- `src/db/models.py`

Objetivo:
Añadir a la clase `Source` exclusivamente los siguientes cinco campos para persistir la presencia de catálogo:
1. `catalog_presence`: `Column(String(16), nullable=False, default="present")`.
2. `last_seen_at`: `Column(DateTime(timezone=True), nullable=True)`.
3. `last_seen_run_id`: `Column(String(36), nullable=True)`. ATENCIÓN: NO crear `ForeignKey` a ninguna tabla; debe ser `String(36)` plano para evitar invalidar el historial al purgar corridas antiguas.
4. `missing_since`: `Column(DateTime(timezone=True), nullable=True)`.
5. `consecutive_misses`: `Column(Integer, nullable=False, default=0)`.

Asegurarse de que los tipos `String`, `DateTime` e `Integer` estén importados desde `sqlalchemy`.
NO añadir estos campos a `Media` ni a ninguna otra entidad.
El proyecto debe quedar compilando e importando `src.db.models` sin errores.

## PASO 2: Crear la migración reversible en alembic/versions/a9b4c3d2e5f6_source_catalog_presence.py

Archivo a crear:
- `alembic/versions/a9b4c3d2e5f6_source_catalog_presence.py`

Objetivo:
Crear la migración encadenada estrictamente a la revisión previa `f8a3b2c1d4e5`.

Configuración de la migración:
- `revision = 'a9b4c3d2e5f6'`
- `down_revision = 'f8a3b2c1d4e5'`
- `branch_labels = None`
- `depends_on = None`

En `upgrade()`:
Usar `with op.batch_alter_table("sources") as batch_op:` (necesario para SQLite) y añadir las 5 columnas:
- `catalog_presence`: `sa.Column('catalog_presence', sa.String(length=16), nullable=False, server_default='present')`
- `last_seen_at`: `sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True)`
- `last_seen_run_id`: `sa.Column('last_seen_run_id', sa.String(length=36), nullable=True)`
- `missing_since`: `sa.Column('missing_since', sa.DateTime(timezone=True), nullable=True)`
- `consecutive_misses`: `sa.Column('consecutive_misses', sa.Integer(), nullable=False, server_default='0')`

En `downgrade()`:
Usar `with op.batch_alter_table("sources") as batch_op:` y eliminar exclusivamente esas cinco columnas:
- `batch_op.drop_column('consecutive_misses')`
- `batch_op.drop_column('missing_since')`
- `batch_op.drop_column('last_seen_run_id')`
- `batch_op.drop_column('last_seen_at')`
- `batch_op.drop_column('catalog_presence')`

No tocar datos existentes ni otras tablas. El proyecto debe quedar compilando y Alembic debe reconocer la revisión.

## PASO 3: Pruebas de migración en tests/test_migrations.py

Archivo a modificar:
- `tests/test_migrations.py`

Objetivo:
Ampliar la suite de pruebas de migraciones para validar el ciclo completo sobre SQLite temporal (sin red y sin tocar `data/gateway.db`):
1. Crear una base temporal en la revisión `f8a3b2c1d4e5` con registros previos en `media` y `sources`.
2. Aplicar upgrade a `head` (`a9b4c3d2e5f6`):
   - Verificar que todas las filas previas se conservan intactas.
   - Verificar que en las filas existentes de `sources`, `catalog_presence` toma el valor `'present'`, `consecutive_misses` toma `0`, y `last_seen_at`, `last_seen_run_id` y `missing_since` son `None`.
3. Insertar una nueva fuente en `head` con valores explícitos (`catalog_presence='missing'`, timestamps asignados, `last_seen_run_id='run-test-id'`, `consecutive_misses=1`) y comprobar que persisten correctamente.
4. Aplicar downgrade de vuelta a `f8a3b2c1d4e5`:
   - Verificar que las cinco columnas nuevas se eliminan de `sources`.
   - Verificar que los registros de `media` y `sources` persisten tras el downgrade.
5. Aplicar nuevamente upgrade a `head` y comprobar que completa exitosamente restableciendo defaults compatibles.

El paso debe dejar todos los tests de `tests/test_migrations.py` y la suite completa en verde.

ACEPTACION
grep -q 'catalog_presence' src/db/models.py
grep -q 'consecutive_misses' src/db/models.py
grep -q 'last_seen_run_id' src/db/models.py
test -f alembic/versions/a9b4c3d2e5f6_source_catalog_presence.py
grep -q "down_revision = 'f8a3b2c1d4e5'" alembic/versions/a9b4c3d2e5f6_source_catalog_presence.py
grep -q "revision = 'a9b4c3d2e5f6'" alembic/versions/a9b4c3d2e5f6_source_catalog_presence.py
grep -q 'batch_alter_table("sources")' alembic/versions/a9b4c3d2e5f6_source_catalog_presence.py
grep -q 'catalog_presence' tests/test_migrations.py
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_migrations.py
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q
test ! -e data/gateway.db
git diff --exit-code origin/main -- scripts/sync_catalog.py src/adapters src/api src/services/video_resolver.py src/services/mediaflow_bridge.py

PREMISES

- `Source` vive en `src/db/models.py` y actualmente no representa presencia o ausencia en el catálogo.
- La cabeza Alembic actual es `f8a3b2c1d4e5_sync_progress_redesign.py` con revisión `f8a3b2c1d4e5`.
- `tests/test_migrations.py` ya prueba upgrade/downgrade sobre SQLite temporal mediante `DATABASE_URL`.
- La sincronización actual aún puede reconciliar con borrado; esta unidad no toca ese comportamiento.
- `origin/main` apunta a `0f832de` y la suite verificada tiene 172 pruebas en verde.
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
