<!-- spec:5eafbc727381e7acb38b5447a8fa60ff -->
# ENCARGO: Blindaje de integridad de `sources` en SQLite (FKs y unicidad de provider+url)

## REGLAS OBLIGATORIAS DE EJECUCIÓN
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- Cada paso se ejecuta por separado en una sesión limpia: debe dejar el proyecto compilando y pasando pruebas.

---

## ADVERTENCIA DE FALLO DE FONDO (CRÍTICO)
SQLite desactiva por defecto la verificación de Foreign Keys (`foreign_keys=OFF`). Aunque el modelo SQLAlchemy declare `ForeignKey("media.id")`, SQLite aceptará silenciosamente fuentes huérfanas en ejecución a menos que se registre un listener en `engine.sync_engine` para el evento `connect` que ejecute `PRAGMA foreign_keys=ON` en la conexión SQLite DBAPI. Asimismo, SQLite no soporta `ALTER TABLE ADD CONSTRAINT` directo: cualquier migración de Alembic que modifique restricciones sobre tablas SQLite debe usar obligatoriamente `op.batch_alter_table(...)`, y fallará de inmediato si antes no se depuran los registros huérfanos y duplicados existentes en `sources`.

---

## PASO 1: Activar `PRAGMA foreign_keys=ON` en SQLite en `src/db/database.py`

**Archivo:** `src/db/database.py`

**Acción:**
1. Leer `src/db/database.py`.
2. Importar `event` de `sqlalchemy`.
3. Tras la instanciación de `engine = create_async_engine(...)`, registrar un listener sobre `engine.sync_engine` para el evento `"connect"`:
   - El listener recibe `(dbapi_connection, connection_record)`.
   - Si la conexión subyacente corresponde a SQLite (o la URL del engine comienza por `sqlite`), obtener un cursor del `dbapi_connection`, ejecutar `"PRAGMA foreign_keys=ON"` y cerrar el cursor.
4. Asegurar que no afecte a otros dialectos si la URL no es SQLite.
5. Dejar el archivo compilando sin alterar la creación de sesiones ni el resto de funciones.

---

## PASO 2: Declarar restricción única `(provider, url)` en el modelo `Source`

**Archivo:** `src/db/models.py`

**Acción:**
1. Leer `src/db/models.py`.
2. Asegurar que `UniqueConstraint` esté importado de `sqlalchemy`.
3. En la clase `Source`, agregar `__table_args__`:
   ```python
   __table_args__ = (
       UniqueConstraint("provider", "url", name="uq_sources_provider_url"),
   )
   ```
4. Conservar intactos los campos existentes (`id`, `media_id`, `provider`, `url`, etc.) y las relaciones (`media`).
5. Verificar que el archivo compila sin errores de sintaxis.

---

## PASO 3: Crear migración de limpieza y unicidad en Alembic

**Archivo:** `alembic/versions/c5d9e2f3a4b5_sources_integrity.py`

**Acción:**
1. Crear el archivo `alembic/versions/c5d9e2f3a4b5_sources_integrity.py` con:
   - `revision = 'c5d9e2f3a4b5'`
   - `down_revision = 'b4c8d1e2f3a4'` (revisión actual según el repositorio)
   - `branch_labels = None`
   - `depends_on = None`
2. En la función `upgrade()`:
   a. Ejecutar mediante `op.execute(...)` la purga de fuentes huérfanas:
      ```sql
      DELETE FROM sources WHERE media_id NOT IN (SELECT id FROM media);
      ```
   b. Ejecutar mediante `op.execute(...)` la deduplicación de fuentes conservando deterministamente la de menor `id`:
      ```sql
      DELETE FROM sources WHERE id NOT IN (
          SELECT MIN(id) FROM sources GROUP BY provider, url
      );
      ```
   c. Utilizar el modo por lotes compatible con SQLite para añadir la restricción única:
      ```python
      with op.batch_alter_table("sources") as batch_op:
          batch_op.create_unique_constraint("uq_sources_provider_url", ["provider", "url"])
      ```
3. En la función `downgrade()`:
   - Revertir únicamente la restricción (sin resucitar datos borrados):
     ```python
     with op.batch_alter_table("sources") as batch_op:
         batch_op.drop_constraint("uq_sources_provider_url", type_="unique")
     ```
4. Comprobar que no hay errores de sintaxis en el archivo.

---

## PASO 4: Idempotencia al registrar fuentes en `src/services/catalog.py`

**Archivo:** `src/services/catalog.py`

**Acción:**
1. Leer `src/services/catalog.py` en las funciones donde se crean o vinculan objetos `Source` a un `Media`.
2. Asegurar que antes de insertar un nuevo `Source`, se verifique si ya existe una fuente con la combinación `(provider, url)` en la base de datos o en la colección local de fuentes para ese medio, actualizando los campos necesarios en lugar de provocar un error de clave duplicada (`IntegrityError`).
3. No alterar la lógica de negocio del catálogo ni modificar llamadas ajenas a la persistencia de fuentes.
4. Dejar el archivo compilando.

---

## PASO 5: Pruebas unitarias de FKs y unicidad en `tests/test_db.py`

**Archivo:** `tests/test_db.py`

**Acción:**
1. Leer `tests/test_db.py`.
2. Añadir tests asíncronos que validen:
   a. Que al abrir una sesión/conexión SQLite con la configuración de la app, `PRAGMA foreign_keys` retorna `1`.
   b. Que intentar insertar un `Source` con un `media_id` inexistente levanta `sqlalchemy.exc.IntegrityError` por fallo de Foreign Key.
   c. Que intentar insertar dos `Source` con idéntico `provider` y `url` levanta `sqlalchemy.exc.IntegrityError` por violación de `uq_sources_provider_url`.
3. Ejecutar los tests con `pytest tests/test_db.py` para asegurar que pasen en verde.

---

ACEPTACION
grep -q "foreign_keys=ON" src/db/database.py
grep -q "uq_sources_provider_url" src/db/models.py
test -f alembic/versions/c5d9e2f3a4b5_sources_integrity.py
grep -q "uq_sources_provider_url" alembic/versions/c5d9e2f3a4b5_sources_integrity.py
grep -q "batch_alter_table" alembic/versions/c5d9e2f3a4b5_sources_integrity.py
python3 -m pytest tests/test_db.py tests/test_cache.py tests/test_catalog_sync.py
python3 -m pytest tests/
git diff --check

PREMISES

I El engine async actual se crea sin listener de conexión que active `PRAGMA foreign_keys=ON` — src/db/database.py:24
I `Source.media_id` declara una FK hacia `media.id` — src/db/models.py:35
I El modelo `Source` contiene `provider` y `url`, pero no declara `__table_args__` ni unicidad — src/db/models.py:30
I La migración inicial crea `sources` con FK y clave primaria, pero sin unicidad sobre `(provider, url)` — alembic/versions/a4b9a06fc210_initial_migration.py:51
I La sincronización actual contiene una limpieza explícita de fuentes huérfanas para residuos creados cuando SQLite no aplicó la FK — scripts/sync_catalog.py:270
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
