<!-- spec:03fba03a754f01c8e5551b693b2ad8e0 -->
# ENCARGO: Categorías dinámicas por género para películas en Xtream API

## REGLAS OBLIGATORIAS PARA EL EJECUTOR
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- Cada paso debe dejar el proyecto COMPILANDO y pasando tests.

---

## PASO 1: Implementar helpers de categorías y campo category_id en src/api/xtream.py

- **Archivo a modificar:** `src/api/xtream.py`
- **Objetivo:** Definir las funciones auxiliares `_build_genre_categories` y `_genre_to_id`, e integrar `category_id` en `_media_item_to_vod_stream`.
- **Detalle de lo que debe quedar:**
  1. En `src/api/xtream.py`, añadir las funciones helper antes de las rutas o endpoints:
     ```python
     def _build_genre_categories(movies: list[MediaItem]) -> list[dict]:
         genres: set[str] = set()
         for m in movies:
             genres.update(m.genres or [])
         if not genres:
             return [{"category_id": "1", "category_name": "Peliculas", "parent_id": 0}]
         sorted_genres = sorted(genres)
         return [
             {"category_id": str(i + 1), "category_name": g, "parent_id": 0}
             for i, g in enumerate(sorted_genres)
         ]

     def _genre_to_id(genres: list[str], sorted_genres: list[str]) -> str:
         if not genres or not sorted_genres:
             return "1"
         first = genres[0]
         if first in sorted_genres:
             return str(sorted_genres.index(first) + 1)
         return "1"
     ```
  2. Modificar la función `_media_item_to_vod_stream` para recibir opcionalmente `sorted_genres: list[str] | None = None` (con valor por defecto `None` para mantener compatibilidad).
  3. En el diccionario que retorna `_media_item_to_vod_stream`, incluir la clave `"category_id": _genre_to_id(item.genres, sorted_genres or [])`.

---

## PASO 2: Conectar categorías dinámicas y filtro por category_id en src/api/xtream.py

- **Archivo a modificar:** `src/api/xtream.py`
- **Objetivo:** Hacer que `get_vod_categories` devuelva las categorías reales basadas en los géneros del catálogo y que `get_vod_streams` filtre por `category_id`.
- **Detalle de lo que debe quedar:**
  1. En el endpoint o handler de `get_vod_categories`:
     - Obtener el catálogo de películas (`catalog_service.get_catalog(media_type=MediaType.MOVIE)`).
     - Aplicar la misma deduplicación por título usada en `get_vod_streams`.
     - Retornar el resultado de llamar a `_build_genre_categories(unique_movies)`.
  2. En el endpoint o handler de `get_vod_streams`:
     - Agregar el parámetro query opcional `category_id: str | None = None` (o `Query(None)` según use el router).
     - Extraer la lista de géneros únicos ordenados alfabéticamente a partir de las películas deduplicadas:
       ```python
       genres_set: set[str] = set()
       for m in unique_movies:
           genres_set.update(m.genres or [])
       sorted_genres = sorted(genres_set)
       ```
     - Si `category_id` está presente:
       - Intentar convertir `category_id` a entero (1-based index).
       - Si el índice es válido (`1 <= idx <= len(sorted_genres)`), obtener el género correspondiente `target_genre = sorted_genres[idx - 1]`.
       - Filtrar `unique_movies` para conservar solo aquellas donde `m.genres` no sea nulo y contenga `target_genre`. Si el `category_id` no es válido o está fuera de rango, retornar lista vacía `[]`.
     - Al transformar las películas con `_media_item_to_vod_stream`, pasar `sorted_genres=sorted_genres`.

---

## PASO 3: Añadir tests unitarios para categorías y filtrado en tests/test_xtream.py

- **Archivo a modificar:** `tests/test_xtream.py`
- **Objetivo:** Verificar que `get_vod_categories` devuelve categorías dinámicas ordenadas y que `get_vod_streams` filtra adecuadamente por `category_id`.
- **Detalle de lo que debe quedar:**
  1. Añadir un test que verifique `_build_genre_categories` y `_genre_to_id`.
  2. Añadir un test que llame al endpoint `action=get_vod_categories` y compruebe que devuelve la lista de categorías con IDs secuenciales basados en los géneros de los items.
  3. Añadir un test que llame a `action=get_vod_streams` con `category_id` y compruebe que sólo se retornan las películas que contienen dicho género y que cada item incluye el campo `"category_id"` correcto.

---

ACEPTACION
test -f src/api/xtream.py
test -f tests/test_xtream.py
grep -q "def _build_genre_categories" src/api/xtream.py
grep -q "def _genre_to_id" src/api/xtream.py
grep -q '"category_id":' src/api/xtream.py
grep -q "category_id" src/api/xtream.py
python3 -c "import sys; sys.path.insert(0, 'src'); from api.xtream import _build_genre_categories; from models.catalog import MediaItem, MediaType; m1=MediaItem(title='A',media_type=MediaType.MOVIE,provider_id='a',genres=['Acción','Thriller']); m2=MediaItem(title='B',media_type=MediaType.MOVIE,provider_id='b',genres=['Comedia']); cats=_build_genre_categories([m1,m2]); assert len(cats)==3; assert cats[0]['category_name']=='Acción'; assert cats[1]['category_name']=='Comedia'; assert cats[2]['category_name']=='Thriller'"
pytest tests/test_xtream.py

PREMISES
- `src/api/xtream.py:114` devuelve 1 categoría hardcodeada "Peliculas"
- `src/models/catalog.py:65` MediaItem tiene `genres: list[str]`
- `src/adapters/cuevana3.py:565-577` `_extract_genres` extrae géneros del HTML
- `src/api/xtream.py:122-131` `get_vod_streams` obtiene catálogo y aplica deduplicación
- `src/api/xtream.py:164` ya usa `", ".join(item.genres)` en el campo "genre" del response
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
