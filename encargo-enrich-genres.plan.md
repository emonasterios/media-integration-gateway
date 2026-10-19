<!-- spec:7ca84788aed182bcf0c57201c54da8f0 -->
REGLAS OBLIGATORIAS PARA EL EJECUTOR:
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

## PASO 1: Agregar campo `genres` al modelo Media
- **Archivo a modificar**: `src/db/models.py`
- **Objetivo**: Permitir almacenar los géneros de cada contenido en la base de datos.
- **Qué debe quedar**:
  1. En `src/db/models.py`, dentro de la clase `Media`, agregar el campo `genres = Column(Text, nullable=True)` justo después de la línea de `poster_url`.
  2. Verificar que `Text` y `Column` estén importados desde `sqlalchemy`.
  3. Comprobar que el archivo compile sin errores ejecutando `python3 -m py_compile src/db/models.py`.

## PASO 2: Crear y aplicar migración de Alembic para la columna `genres`
- **Archivo a crear**: `alembic/versions/b4c8d1e2f3a4_add_genres_to_media.py`
- **Objetivo**: Actualizar el esquema de la base de datos SQLite para incluir la columna `genres`.
- **Qué debe quedar**:
  1. Crear el script de migración con `revision = 'b4c8d1e2f3a4'`, `down_revision = 'a4b9a06fc210'`.
  2. En la función `upgrade()`, ejecutar `op.add_column('media', sa.Column('genres', sa.Text(), nullable=True))`.
  3. En la función `downgrade()`, ejecutar `op.drop_column('media', 'genres')`.
  4. Ejecutar la migración con: `alembic upgrade head` asegurando que la base de datos aplique el cambio correctamente.

## PASO 3: Serialización y deserialización de géneros en `CatalogCache`
- **Archivo a modificar**: `src/services/cache.py`
- **Objetivo**: Asegurar que `genres` se guarde como string JSON en la base de datos y se deserialice a lista de Python al recuperarlo.
- **Qué debe quedar**:
  1. En `src/services/cache.py`, importar `json` si no está presente.
  2. En el método `save_media` (alrededor de la línea 60), antes de persistir los valores del item, verificar:
     ```python
     if "genres" in item_data and isinstance(item_data["genres"], list):
         item_data["genres"] = json.dumps(item_data["genres"])
     ```
  3. En los métodos de lectura/recuperación donde se instancia `MediaItem` a partir del modelo `Media` (por ejemplo en `get_media`, `get_all_media` o el helper que convierte el modelo ORM `Media` a diccionario/objeto de dominio), asegurar la deserialización:
     ```python
     if media.genres and isinstance(media.genres, str):
         genres_list = json.loads(media.genres)
     ```
     asignando la lista resultante al campo `genres` del item retornado.
  4. Comprobar que compile con `python3 -m py_compile src/services/cache.py`.

## PASO 4: Crear el script de enriquecimiento de géneros `scripts/enrich_genres.py`
- **Archivo a crear**: `scripts/enrich_genres.py`
- **Objetivo**: Script independiente para recorrer películas sin géneros en la BD, consultar detalles con el adaptador y actualizar la BD con rate limiting.
- **Qué debe quedar**:
  1. Implementar `scripts/enrich_genres.py` con soporte de argumentos mediante `argparse`:
     - `--limit`: entero opcional para limitar la cantidad de películas a procesar.
     - `--provider`: string con valor por defecto `'cuevana3'`.
  2. Conectar a la base de datos usando `SessionLocal` desde `src.db.database` y consultar películas en el modelo `Media` (`media_type == 'movie'` y `(Media.genres == None | Media.genres == '[]')`). Si se especificó `--limit`, aplicar el límite a la consulta.
  3. Para el proveedor `cuevana3`, instanciar `Cuevana3Adapter` de `src.adapters.cuevana3`.
  4. Por cada película a enriquecer:
     - Invocar `await adapter.get_details(media.id)` (o el método síncrono/asíncrono según la firma en `Cuevana3Adapter`) para extraer la ficha con sus géneros.
     - Si se obtienen géneros, serializar la lista a JSON con `json.dumps(genres)` y actualizar `media.genres` en la sesión de base de datos, haciendo `commit()`.
     - Rate limit: pausar 2 segundos entre cada petición a la web (`asyncio.sleep(2)` o `time.sleep(2)`).
     - Progreso: imprimir un mensaje de log en consola cada 10 películas procesadas.
  5. Permitir la ejecución directa como script CLI (`if __name__ == '__main__': ...`).
  6. Comprobar que compile con `python3 -m py_compile scripts/enrich_genres.py`.

## PASO 5: Actualizar `get_vod_categories` en `src/api/xtream.py`
- **Archivo a modificar**: `src/api/xtream.py`
- **Objetivo**: Obtener las categorías VOD de películas extrayendo los géneros únicos guardados en la BD.
- **Qué debe quedar**:
  1. En `src/api/xtream.py`, en la función `get_vod_categories` (alrededor de la línea 113):
     - Consultar en la base de datos: `SELECT DISTINCT genres FROM media WHERE media_type='movie' AND genres IS NOT NULL AND genres != '[]'`.
     - Para cada registro, deserializar con `json.loads(row[0])` y acumular todos los géneros únicos en un conjunto (`set`).
     - Si se encuentran géneros, ordenarlos alfabéticamente y generar la lista de categorías con formato:
       `{"category_id": str(idx), "category_name": genre_name, "parent_id": 0}` para cada género (con `idx` incremental empezando en 1).
     - Fallback: si no hay géneros en la BD o el conjunto resultante está vacío, devolver la categoría por defecto:
       `[{"category_id": "1", "category_name": "Peliculas", "parent_id": 0}]`.
  2. No alterar los endpoints ni la lógica de streaming/proxy existentes en el archivo.
  3. Comprobar que compile con `python3 -m py_compile src/api/xtream.py`.

## PASO 6: Disparar enriquecimiento en background durante el warmup en `src/main.py`
- **Archivo a modificar**: `src/main.py`
- **Objetivo**: Iniciar el proceso de enriquecimiento en segundo plano sin bloquear el arranque del servidor.
- **Qué debe quedar**:
  1. En `src/main.py`, en el evento de inicio / warmup del catálogo (después de inicializar el caché):
     - Lanzar el script `scripts/enrich_genres.py` en segundo plano utilizando `subprocess.Popen([sys.executable, "scripts/enrich_genres.py"])` (o mediante `asyncio.create_task` si se encapsula como tarea async).
     - Asegurar que no se use `await` sobre este proceso para no demorar el inicio del servidor HTTP.
  2. Comprobar que compile con `python3 -m py_compile src/main.py`.

ACEPTACION
grep -q "genres = Column(Text" src/db/models.py
grep -q "add_column('media'" alembic/versions/*add_genres*.py
grep -q "json.dumps" src/services/cache.py
test -f scripts/enrich_genres.py
grep -q "get_details" scripts/enrich_genres.py
grep -q "argparse" scripts/enrich_genres.py
grep -q "genres" src/api/xtream.py
grep -q "category_id" src/api/xtream.py
grep -q "enrich_genres" src/main.py
python3 -m py_compile src/db/models.py src/services/cache.py scripts/enrich_genres.py src/api/xtream.py src/main.py
pytest tests/ -v

PREMISES
- src/db/models.py:12-26 — modelo Media sin campo genres
- src/adapters/cuevana3.py:242 — _extract_genres funciona en get_details
- src/adapters/cuevana3.py:186-198 — get_catalog crea MediaItem sin genres
- src/services/cache.py:60-102 — save_media persiste item_data pero genres no existe en el modelo
- src/api/xtream.py:113-160 — get_vod_categories lee del caché en memoria, no de la BD
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
