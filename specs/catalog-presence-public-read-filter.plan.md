<!-- spec:47399e7b5eaf13e3a621618b9e099ccb -->
# ENCARGO: Excluir fuentes ausentes (`catalog_presence='missing'`) de las lecturas públicas del catálogo

## Reglas obligatorias para el ejecutor
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- Mantener el proyecto compilando y pasando pruebas tras cada paso.

---

## ADVERTENCIA DE FONDO (CRÍTICO)
El método de conversión en `src/services/catalog.py` actualmente tiene un mecanismo de contingencia (*fallback*) que usa el ID interno de `Media` o toma cualquier fuente disponible si no encuentra una coincidencia exacta. Si no se elimina ese fallback y no se valida estrictamente que la fuente tenga `catalog_presence == "present"`, los medios ausentes seguirán filtrándose a las APIs públicas como si estuvieran disponibles, simulando IDs inexistentes y provocando fallos en tiempo de ejecución.

---

## PASO 1: Filtrar fuentes ausentes en la caché y añadir su regresión
**Archivos a modificar:**
- `src/services/cache.py`
- `tests/test_cache.py`

**Instrucciones:**
1. En `src/services/cache.py`, localizar el método `get_by_source(provider: str, url: str)`.
   - Modificar la consulta SQLAlchemy que busca la fuente para que además de coincidir por `provider` y `url`, verifique que `Source.catalog_presence == "present"`.
   - Si la fuente existe pero tiene `catalog_presence == "missing"`, la consulta no debe devolver el medio asociado (debe retornar `None`).
   - No alterar la lógica de reconciliación ni el guardado en base de datos.
2. En `tests/test_cache.py`:
   - Añadir un caso de prueba asíncrono donde se inserte un `Media` con una `Source` cuyo `catalog_presence="missing"`.
   - Verificar que `cache.get_by_source(provider, url)` retorne `None`.
   - Verificar que otra fuente con `catalog_presence="present"` sí sea recuperada por `get_by_source`.

---

## PASO 2: Filtrar presencia en el servicio de catálogo desacoplado
**Archivos a modificar:**
- `src/services/catalog.py`

**Instrucciones:**
1. En `src/services/catalog.py`, inspeccionar `_load_catalog_from_db(self, provider: str, ...)`.
   - Modificar la consulta para añadir el filtro `Source.catalog_presence == "present"` sobre el proveedor solicitado (unir `Media.sources` y filtrar `Source.provider == provider` y `Source.catalog_presence == "present"`).
2. En `_convert_db_media_to_item(self, media, provider: str)`:
   - Buscar únicamente fuentes donde `s.provider == provider and getattr(s, "catalog_presence", "present") == "present"`.
   - ELIMINAR cualquier fallback a otras fuentes (`media.sources[0]`) o a `str(media.id)` cuando no haya una fuente presente del proveedor solicitado. Si no hay fuente presente para ese proveedor, el método debe retornar `None`.
   - Al iterar medios en `_load_catalog_from_db`, ignorar los que devuelvan `None` al convertirse a ítem de catálogo.

---

## PASO 3: Filtrar fuentes ausentes en la generación de listas M3U y probar regresión
**Archivos a modificar:**
- `src/api/m3u.py`
- `tests/test_m3u.py`

**Instrucciones:**
1. En `src/api/m3u.py`, revisar el endpoint `get_playlist`:
   - En la consulta que carga los medios y sus fuentes, asegurar que solo se consideren medios con al menos una fuente con `Source.catalog_presence == "present"`.
   - Al construir las entradas de la playlist (`#EXTINF`), seleccionar `provider` y `provider_id` exclusivamente de una fuente que tenga `catalog_presence == "present"`. Nunca tomar la primera fuente si esta tiene `catalog_presence == "missing"`.
   - Si un medio no tiene fuentes presentes, omitirlo por completo de la playlist.
2. En `tests/test_m3u.py`:
   - Crear un test que inserte dos películas en la base de datos de prueba: una con `Source(catalog_presence="present")` y otra con `Source(catalog_presence="missing")`.
   - Invocar el endpoint de playlist `/m3u` (o la función generadora).
   - Aseverar que la película con fuente "present" aparece en el texto M3U generado y que la película con fuente "missing" NO aparece en el texto.

---

## PASO 4: Filtrar fuentes ausentes en las rutas y consultas de Xtream Codes
**Archivos a modificar:**
- `src/api/xtream.py`

**Instrucciones:**
1. En `src/api/xtream.py`, localizar la función `_load_catalog_from_db`:
   - Reemplazar la cláusula `LEFT JOIN sources s ON s.media_id = m.id AND s.provider = 'cuevana3'` por un `JOIN sources s ON s.media_id = m.id AND s.provider = 'cuevana3' AND s.catalog_presence = 'present'`.
   - Asegurarse de usar `DISTINCT` o agrupar para evitar registros duplicados si un medio tuviese múltiples fuentes.
2. En `_load_single_movie_from_db`:
   - Asegurarse de que la consulta exija que la fuente asociada de `cuevana3` tenga `catalog_presence = 'present'`.
   - Si no existe una fuente `cuevana3` presente, la función debe devolver `None`. No permitir que `get_vod_info` ni la ruta de streaming `/movie/...` sirvan películas cuya fuente esté marcada como `missing`.
3. En `get_vod_categories`:
   - Asegurarse de que las categorías VOD se deriven únicamente de películas visibles que tengan fuentes presentes (utilizando `_load_catalog_from_db` o filtrando con la misma condición de presencia).

---

## PASO 5: Añadir pruebas de regresión completas para Xtream Codes
**Archivos a modificar:**
- `tests/test_xtream.py`

**Instrucciones:**
1. En `tests/test_xtream.py`, añadir pruebas de regresión que siembren simultáneamente:
   - Película A con fuente `cuevana3` y `catalog_presence="present"`.
   - Película B con fuente `cuevana3` y `catalog_presence="missing"`.
2. Validar en los tests:
   - `action=get_vod_streams`: la lista solo contiene la película A; la película B queda excluida.
   - `action=get_vod_info` con el stream_id de la película B: devuelve respuesta vacía o error/404, mientras que para la película A devuelve su detalle correctamente.
   - Endpoint `/movie/{username}/{password}/{stream_id}.mp4` con el stream_id de la película B: responde con código de estado 404.
   - `action=get_vod_categories`: una categoría perteneciente exclusivamente a la película B no debe listarse.
3. Ejecutar los tests para confirmar que pasan completamente.

---

ACEPTACION
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_xtream.py tests/test_m3u.py tests/test_cache.py tests/test_smoke.py
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q
! rg -n 'LEFT JOIN sources s ON s.media_id = m.id AND s.provider = .cuevana3.' src/api/xtream.py
rg -n 'catalog_presence' src/api/xtream.py src/api/m3u.py src/services/catalog.py src/services/cache.py

PREMISES
- `src/api/xtream.py:31-39` lista el catálogo con `LEFT JOIN sources` y sin filtrar `catalog_presence`, por lo que una fuente ausente sigue publicada.
- `src/api/xtream.py:97-104` carga detalle/reproducción por PK sin exigir una fuente presente.
- `src/api/m3u.py:64-82` selecciona todos los medios y acepta cualquier primera fuente cargada.
- `src/services/catalog.py:164-169` filtra por proveedor pero no por presencia.
- `src/services/catalog.py:106-125` cae a otra fuente o al ID interno si no encuentra la fuente solicitada.
- `src/services/cache.py:51-60` resuelve por provider/url sin filtrar presencia.
- `src/db/models.py:46` declara `catalog_presence` no nulo con valor predeterminado `present`.
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
