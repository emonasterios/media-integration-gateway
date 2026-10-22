<!-- spec:b73a12249f041e63c2dd7585b6b72561 -->
REGLAS OBLIGATORIAS:
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

## PASO 1: Modelo de datos
- Archivo a modificar: `src/db/models.py`
- Qué hacer:
  - En la clase `Source`, añadir el campo `page_url = Column(String, nullable=True)`.
  - Mantener intacto el campo `url = Column(String, nullable=False)` que almacena el `provider_id`/slug.
  - Mantener la restricción única `UniqueConstraint("provider", "url", name="uq_sources_provider_url")` sin cambios en `Source.__table_args__`.
- Resultado esperado: `Source.__table__.columns['page_url'].nullable` es `True`, `Source.url` permanece inalterado y el proyecto compila e importa sin errores.

## PASO 2: Migración Alembic
- Archivo a crear: `alembic/versions/d6e1f2a3b4c5_add_page_url_to_sources.py`
- Qué hacer:
  - Crear la migración con identificador `revision = 'd6e1f2a3b4c5'` y `down_revision = 'c5d9e2f3a4b5'`.
  - En `upgrade()`: añadir la columna nullable `page_url` de tipo `sa.String()` a la tabla `sources` (`op.add_column('sources', sa.Column('page_url', sa.String(), nullable=True))`).
  - En `downgrade()`: eliminar la columna `page_url` usando `batch_alter_table` (`with op.batch_alter_table('sources') as batch_op: batch_op.drop_column('page_url')`) para garantizar compatibilidad con SQLite.
- Resultado esperado: La migración enlaza directamente con `c5d9e2f3a4b5` como revisión previa y es capaz de aplicarse y revertirse en SQLite sin errores.

## PASO 3: Guardado y preservación de page_url en sincronización
- Archivo a modificar: `scripts/sync_catalog.py`
- Qué hacer:
  - En la función `persist_page_batch`:
    - Al instanciar un nuevo `Source`, asignar `page_url=item.get("url")`.
    - Al actualizar un `Source` existente: comprobar si `item.get("url")` contiene un valor no vacío; si es así, actualizar `source.page_url = item["url"]`. Si `item.get("url")` es `None` o está ausente, NO modificar `source.page_url` para conservar el valor previo.
  - En la función `sync_from_checkpoint`:
    - Aplicar la misma lógica: al crear o actualizar registros de `Source`, asignar `page_url=item.get("url")` sólo cuando `item.get("url")` contenga valor, asegurando total compatibilidad con checkpoints antiguos que no traigan la clave `"url"`.
- Resultado esperado: Los flujos de sincronización persisten la URL completa en `page_url` sin perder valores preexistentes cuando los datos entrantes omiten el campo.

## PASO 4: Pruebas de sincronización de catálogo
- Archivo a modificar: `tests/test_catalog_sync.py`
- Qué hacer:
  - Añadir pruebas unitarias/integración para:
    1. Creación de una fuente verificando que `page_url` se guarda con el contenido de `item["url"]`.
    2. Actualización de una fuente existente con un nuevo valor en `item["url"]` comprobando que `page_url` se actualiza.
    3. Conservación del valor preexistente de `page_url` cuando un lote entrante no define `url` o viene como `None`.
    4. Sincronización desde checkpoint sin el campo `url` demostrando compatibilidad hacia atrás.
- Resultado esperado: Las pruebas de sincronización cubren creación, actualización y preservación de `page_url`, pasando en verde.

## PASO 5: Pruebas de migración de base de datos
- Archivo a modificar: `tests/test_migrations.py`
- Qué hacer:
  - Ampliar o ajustar la suite de pruebas de migraciones para validar el salto completo hasta `head`:
    1. Verificar que al aplicar todas las migraciones sobre SQLite, la columna `page_url` en la tabla `sources` existe y es nullable.
    2. Verificar que los registros existentes en `sources` antes de la migración conservan sus datos intactos y su `page_url` queda en `None`.
    3. Verificar que el downgrade de la revisión `d6e1f2a3b4c5` elimina la columna `page_url` limpiamente en SQLite.
- Resultado esperado: Las pruebas de migración ejecutan el ciclo completo de `upgrade` y `downgrade` sin fallos.

ACEPTACION
test -f alembic/versions/d6e1f2a3b4c5_add_page_url_to_sources.py
grep -q "page_url = Column(String, nullable=True)" src/db/models.py
grep -q "item.get(\"url\")" scripts/sync_catalog.py
grep -q "page_url" scripts/sync_catalog.py
grep -q "d6e1f2a3b4c5" alembic/versions/d6e1f2a3b4c5_add_page_url_to_sources.py
grep -q "c5d9e2f3a4b5" alembic/versions/d6e1f2a3b4c5_add_page_url_to_sources.py
grep -q "page_url" tests/test_catalog_sync.py
grep -q "page_url" tests/test_migrations.py
. /home/emon/media-integration-gateway/.venv/bin/activate && python -c "from src.db.models import Source; assert Source.__table__.columns['page_url'].nullable is True; assert Source.__table_args__[0].columns.keys() == ['provider', 'url']"
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_catalog_sync.py tests/test_migrations.py

PREMISES

I `Source` solo tiene `provider` y `url`; no existe un campo para la URL completa — src/db/models.py:30-44
I La identidad única vigente sigue siendo `(provider, url)` — src/db/models.py:33-35
I El crawler ya incluye la URL completa en cada ítem descubierto — src/adapters/cuevana3.py:445-455
I `persist_page_batch` guarda únicamente `provider_id` dentro de `Source.url` — scripts/sync_catalog.py:95-134
I `sync_from_checkpoint` también guarda únicamente `provider_id` dentro de `Source.url` — scripts/sync_catalog.py:222-250
I La revisión Alembic actual de integridad es posterior a la migración de géneros — alembic/versions/c5d9e2f3a4b5_sources_integrity.py:14-15
I Las migraciones se prueban sobre SQLite preexistente hasta `head` — tests/test_migrations.py:16-27
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
