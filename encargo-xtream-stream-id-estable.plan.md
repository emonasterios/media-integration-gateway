<!-- spec:44f8a5cac2536501e3b7961a41c10039 -->
REGLAS OBLIGATORIAS:
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

FALLO DE FONDO PREVIO:
En `src/api/xtream.py`, `stream_id` se calcula hoy como `1000 + index` (usando la posición ordinal tras ordenar o filtrar) y luego en `get_vod_info` y en la resolución de `/movie/` se busca por índice de lista o se asume correspondencia posicional. Si la lista se filtra por categoría o cambia de orden, el `stream_id` apunta a una película distinta o se sale de rango. La solución debe usar la identidad persistente `media.id` (presente en `MediaItem.media_id`), fijando `stream_id = 1000 + media_id`, y resolver siempre buscando el elemento con `item.media_id == stream_id - 1000`.

## PASO 1: Identidad estable y resolución por ID en `src/api/xtream.py`

**Archivo a modificar:** `src/api/xtream.py`

**Objetivo:**
Desvincular `stream_id` de la posición de la lista (`index`), basándolo exclusivamente en `item.media_id` con offset 1000, y centralizar la resolución de películas por `stream_id`.

**Instrucciones de edición:**
1. Leer `src/api/xtream.py` antes de tocar nada.
2. Definir helpers pequeños al inicio o sección de utilidades de `src/api/xtream.py`:
   - `def movie_stream_id(media_id: int) -> int: return 1000 + media_id`
   - `def media_id_from_stream_id(stream_id: int) -> int: return stream_id - 1000`
   - `def find_movie_by_stream_id(items: list, stream_id: int):` que busque y retorne el `MediaItem` cuyo `item.media_id == media_id_from_stream_id(stream_id)` (asegurando que `stream_id > 1000` y `item.media_id is not None`), o `None` si no existe.
3. En `get_vod_streams`:
   - Mantener `"num": index + 1` para la posición visual ordinal en la respuesta.
   - Cambiar `"stream_id": 1000 + index` por `"stream_id": movie_stream_id(item.media_id)` (o `1000 + item.media_id`).
   - Mantener el filtrado por `category_id` sin que altere el `stream_id` resultante para cada película.
4. En `get_vod_info`:
   - Reemplazar la resolución posicional (que dependía del índice en la lista) por la búsqueda mediante `find_movie_by_stream_id(movies, stream_id)`.
   - Si no se encuentra película para dicho `stream_id`, mantener la respuesta controlada existente (retornar estructura vacía / 404 según esté definido).
5. En la función de resolución para reproducción (alrededor de líneas 384-418, en `stream_movie` o su resolvedor auxiliar):
   - Reemplazar la enumeración o indexación posicional por la búsqueda con `find_movie_by_stream_id(movies, stream_id)`.
   - Garantizar que `/movie/.../{stream_id}` resuelva la misma película que devolvió `get_vod_streams` y `get_vod_info`.
6. Comprobar que `src/api/xtream.py` compila sin errores de sintaxis (`python3 -m py_compile src/api/xtream.py`).

## PASO 2: Pruebas de regresión de identidad estable en `tests/test_xtream.py`

**Archivo a modificar:** `tests/test_xtream.py`

**Objetivo:**
Actualizar las pruebas existentes que asumían `stream_id = 1000 + index` y agregar pruebas de regresión que verifiquen la estabilidad de la identidad de películas.

**Instrucciones de edición:**
1. Leer `tests/test_xtream.py` antes de editar.
2. Actualizar las aserciones de pruebas existentes donde se valide `stream_id` para que coincidan con `1000 + item.media_id` en lugar de la posición de índice `1000 + index`.
3. Añadir casos de prueba específicos que demuestren:
   - **Estabilidad ante reordenación:** Ordenar el catálogo de películas de forma distinta no altera el `stream_id` ni la película que resuelve cada `stream_id`.
   - **Estabilidad ante filtrado:** Filtrar `get_vod_streams` por `category_id` devuelve películas con el mismo `stream_id` exacto que cuando se consulta sin filtro.
   - **Coincidencia catálogo - detalle - reproducción:** Para un mismo `stream_id`, la película obtenida en `get_vod_streams`, la devuelta en `get_vod_info` y la resuelta en la ruta de reproducción de película corresponden al mismo registro (`media_id` y título coincidente).
   - **ID inexistente:** Un `stream_id` que no corresponde a ningún `media_id` (o fuera de rango `< 1000`) produce una respuesta controlada y esperada (sin excepciones no capturadas ni crashes).
4. Ejecutar la suite de tests para asegurar que pasan completamente (`pytest tests/test_xtream.py -q`).

ACEPTACION
! grep -q 'stream_id": 1000 + index' src/api/xtream.py
grep -q 'find_movie_by_stream_id' src/api/xtream.py
grep -q 'test_stream_id_stable_with_category_filter' tests/test_xtream.py
grep -q 'test_stream_id_stable_under_reordering' tests/test_xtream.py
grep -q 'test_movie_stream_id_matches_catalog_info_and_playback' tests/test_xtream.py
python3 -m py_compile src/api/xtream.py
pytest tests/test_xtream.py -q

PREMISES

src/api/xtream.py:21-50 carga `media.id` en `MediaItem.media_id` y por tanto ya dispone de una identidad persistente por registro.
src/api/xtream.py:111-127 publica hoy `stream_id` como `1000 + index`, una posición y no una identidad.
src/api/xtream.py:237-255 ordena y después vuelve a enumerar; con `category_id` filtra antes de enumerar, por lo que renumera las películas.
src/api/xtream.py:257-266 ordena otra lista para resolver `get_vod_info` mediante posición.
src/api/xtream.py:384-397 resuelve películas mediante enumeración posicional.
src/api/xtream.py:413-418 carga otra lista y llama al resolvedor posicional, causa directa de reproducir una película distinta.
src/db/models.py:12-17 declara `Media.id` como clave primaria entera.
tests/test_xtream.py:447-511 contiene las pruebas actuales de catálogo, detalle y ruta de película, pero no cubre estabilidad ante orden o filtrado.
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
