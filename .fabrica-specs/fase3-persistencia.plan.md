<!-- spec:fb2f378fcfa2db095a5a587a5245b8c7 -->
REGLAS OBLIGATORIAS:
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

FALLO DE FONDO CRÍTICO:
Si se implementan modelos o servicios que importen `sqlalchemy` o `alembic` sin declarar sus dependencias en la configuración del proyecto, el sistema fallará en tiempo de ejecución con `ModuleNotFoundError` en cuanto se intente correr cualquier test o módulo. Las dependencias deben quedar aseguradas como primer paso.

## PASO 1: Dependencias en pyproject.toml
Archivo: `pyproject.toml`
Qué hacer:
1. Leer `pyproject.toml`.
2. En la sección `dependencies`, añadir `sqlalchemy>=2.0.0` y `alembic>=1.13.0` si no están presentes.
3. No modificar ninguna otra dependencia ni versión existente.

## PASO 2: Configuración de base de datos y caché en src/core/config.py
Archivo: `src/core/config.py`
Qué hacer:
1. Leer `src/core/config.py`.
2. Agregar a la clase de configuración (Settings) los siguientes atributos con sus valores por defecto:
   - `DATABASE_URL: str = "sqlite:///./media_gateway.db"`
   - `CACHE_TTL_SECONDS: int = 3600`
3. Mantener todas las configuraciones y atributos existentes intactos.

## PASO 3: Conexión y sesión de base de datos en src/db/__init__.py y src/db/database.py
Archivos: `src/db/__init__.py`, `src/db/database.py`
Qué hacer:
1. Crear `src/db/__init__.py` exportando `Base`, `engine`, `SessionLocal`, `get_db`, `init_db`.
2. Crear `src/db/database.py`:
   - Configurar `Base = declarative_base()`.
   - Configurar `engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {})`.
   - Configurar `SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)`.
   - Definir función generadora `get_db()` que abra sesión, haga `yield` y cierre en el bloque `finally`.
   - Definir función `init_db()` que invoque `Base.metadata.create_all(bind=engine)`.

## PASO 4: Modelos SQLAlchemy en src/db/models.py
Archivo: `src/db/models.py`
Qué hacer:
1. Crear `src/db/models.py` importando `Base` desde `src.db.database`.
2. Definir los siguientes 4 modelos SQLAlchemy con sus claves foráneas y relaciones:
   - `Media`: tabla `media`, columnas: `id` (Integer, primary_key=True), `title` (String, nullable=False), `original_title` (String, nullable=True), `media_type` (String, nullable=False), `year` (Integer, nullable=True), `synopsis` (Text, nullable=True), `poster_url` (String, nullable=True), `created_at` (DateTime, default=datetime.utcnow), `updated_at` (DateTime, default=datetime.utcnow, onupdate=datetime.utcnow), y relación `sources = relationship("Source", back_populates="media", cascade="all, delete-orphan")`.
   - `Source`: tabla `sources`, columnas: `id` (Integer, primary_key=True), `media_id` (Integer, ForeignKey("media.id"), nullable=False), `provider` (String, nullable=False), `url` (String, nullable=False), `quality` (String, nullable=True), `language` (String, nullable=True), y relación `media = relationship("Media", back_populates="sources")`.
   - `Favorite`: tabla `favorites`, columnas: `id` (Integer, primary_key=True), `media_id` (Integer, ForeignKey("media.id"), nullable=False), `created_at` (DateTime, default=datetime.utcnow), y relación `media = relationship("Media")`.
   - `History`: tabla `history`, columnas: `id` (Integer, primary_key=True), `media_id` (Integer, ForeignKey("media.id"), nullable=False), `viewed_at` (DateTime, default=datetime.utcnow), `progress` (Float, default=0.0), y relación `media = relationship("Media")`.
3. Exportar `Media`, `Source`, `Favorite`, `History` en `src/db/__init__.py`.

## PASO 5: Tests unitarios de modelos y persistencia en tests/test_db.py
Archivo: `tests/test_db.py`
Qué hacer:
1. Crear `tests/test_db.py`.
2. Escribir pruebas unitarias utilizando una base de datos SQLite en memoria (`sqlite:///:memory:`):
   - Probar que `init_db()` crea las tablas correctamente.
   - Probar inserción y recuperación de un registro `Media` con uno o más registros `Source` asociados.
   - Probar inserción y consulta de un registro en `Favorite` asociado a un `Media`.
   - Probar inserción y consulta de un registro en `History` asociado a un `Media`.
3. Asegurar que los tests se ejecuten limpiamente con pytest sin alterar la suite previa.

## PASO 6: Configuración de migraciones Alembic en alembic.ini y alembic/env.py
Archivos: `alembic.ini`, `alembic/env.py`
Qué hacer:
1. Crear archivo `alembic.ini` en la raíz del proyecto configurado con `script_location = alembic` y apuntando a SQLite por defecto.
2. Crear directorio `alembic/` y `alembic/versions/` si no existen.
3. Crear `alembic/env.py` configurando:
   - Importar `Base` desde `src.db.database` y todos los modelos desde `src.db.models`.
   - Asignar `target_metadata = Base.metadata`.
   - Obtener la URL de conexión desde `src.core.config.settings.DATABASE_URL`.
   - Definir funciones `run_migrations_offline` y `run_migrations_online` estándar de Alembic.

## PASO 7: Servicio de caché con TTL configurable en src/services/cache.py
Archivo: `src/services/cache.py`
Qué hacer:
1. Crear `src/services/cache.py`.
2. Definir la clase `CatalogCache` que reciba una sesión de base de datos (`db: Session`) y un tiempo de expiración opcional (`ttl_seconds: int = settings.CACHE_TTL_SECONDS`).
3. Implementar métodos:
   - `get_media(title: str, media_type: Optional[str] = None) -> Optional[Media]`: busca en la tabla `media`. Si existe, comprueba si `updated_at` está dentro de la ventana de tiempo del TTL. Si expiró, retorna `None`. Si está vigente, retorna la entidad con sus `sources`.
   - `save_media(item_data: dict, sources_data: list[dict]) -> Media`: crea o actualiza el registro en `Media` con `updated_at = datetime.utcnow()`, sincroniza las `sources` asociadas y persiste con commit en la base de datos.
   - `is_valid(media: Media) -> bool`: verifica si `datetime.utcnow() - media.updated_at <= timedelta(seconds=self.ttl_seconds)`.

## PASO 8: Integración de la caché en src/services/catalog.py
Archivo: `src/services/catalog.py`
Qué hacer:
1. Leer `src/services/catalog.py`.
2. Modificar `CatalogService` para soportar caché opcional (recibiendo `cache: Optional[CatalogCache] = None` o creándolo con `SessionLocal()` si está disponible).
3. En el método de búsqueda / obtención de catálogo:
   - Antes de llamar a los adapters de scraping, consultar si el medio solicitado ya se encuentra en caché/DB y está vigente según el TTL.
   - Si la caché retorna un medio válido, devolver los datos cacheados sin invocar a los adapters externos.
   - Si no está en caché o expiró, invocar al adapter correspondiente, guardar el resultado obtenido en la base de datos vía la caché y retornar el resultado.
4. Mantener total compatibilidad con los 30 tests existentes (si no se provee sesión o la BD está vacía, debe scrapear normalmente manteniendo los retornos esperados).

## PASO 9: Tests unitarios de caché y flujo completo en tests/test_cache.py
Archivo: `tests/test_cache.py`
Qué hacer:
1. Crear `tests/test_cache.py`.
2. Escribir pruebas unitarias que validen:
   - Hit de caché: cuando un medio existe en DB y su tiempo no supera el TTL, `CatalogService` retorna el contenido desde la DB y no invoca al adapter de scraping.
   - Miss de caché: cuando un medio no existe en DB, se invoca al adapter y el resultado queda persistido en SQLite.
   - Expiración de TTL: cuando el registro en DB tiene un `updated_at` más antiguo que `CACHE_TTL_SECONDS`, se detecta expirado y se fuerza una nueva consulta al adapter actualizando la DB.
3. Asegurar que todos los tests pasen junto con la suite completa preexistente.

ACEPTACION
grep -q "sqlalchemy" pyproject.toml
grep -q "alembic" pyproject.toml
grep -q "DATABASE_URL" src/core/config.py
grep -q "CACHE_TTL_SECONDS" src/core/config.py
test -f src/db/database.py
grep -q "Base" src/db/database.py
grep -q "init_db" src/db/database.py
test -f src/db/models.py
grep -q "class Media" src/db/models.py
grep -q "class Source" src/db/models.py
grep -q "class Favorite" src/db/models.py
grep -q "class History" src/db/models.py
test -f alembic.ini
test -f alembic/env.py
test -f src/services/cache.py
grep -q "class CatalogCache" src/services/cache.py
grep -q "CatalogCache" src/services/catalog.py
test -f tests/test_db.py
test -f tests/test_cache.py
python3 -m pytest tests/test_db.py tests/test_cache.py
python3 -m pytest tests/

PREMISES
- src/services/catalog.py usa CatalogService con adapters
- src/models/catalog.py tiene MediaItem, Movie, Series, etc.
- 30 tests pasando actualmente
- pyproject.toml tiene dependencias básicas
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
