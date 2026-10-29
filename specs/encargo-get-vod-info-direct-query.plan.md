<!-- spec:27c9c4a91dfb8b2dcbb8300df53ca238 -->
# ENCARGO: Optimizar get_vod_info con query directo a SQLite

## REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- Cada paso debe dejar el proyecto COMPILANDO.

---

## PASO 1: Añadir función helper `_load_single_movie_from_db` en `src/api/xtream.py`

### Archivo a modificar
- `src/api/xtream.py`

### Objetivo
Añadir una función helper asíncrona para consultar una única película directamente en SQLite por su clave primaria `media_id`, evitando cargar y ordenar todo el catálogo en memoria.

### Instrucciones
1. Leer `src/api/xtream.py` y ubicar la sección previa a los endpoints del router (cerca de donde está definido `_load_catalog_from_db`).
2. Comprobar que los imports necesarios (`aiosqlite`, `json`, `Path`, `MediaItem`, `MediaType`, `DB_PATH`) ya estén presentes en la cabecera. Si falta alguno, importarlo sin alterar los existentes.
3. Añadir la siguiente función helper:

```python
async def _load_single_movie_from_db(
    media_id: int,
    db_path: Path | str | None = None,
) -> MediaItem | None:
    """Carga UNA película por media_id (PK) desde SQLite. db_path permite tests aislados."""
    target = Path(db_path) if db_path else DB_PATH
    if not target.exists():
        return None
    async with aiosqlite.connect(str(target)) as db:
        async with db.execute(
            "SELECT m.id, m.title, m.original_title, m.media_type, m.year, m.synopsis, m.poster_url, m.genres, "
            "m.cast, m.director, m.duration, m.rating, m.country, "
            "s.url as source_url "
            "FROM media m "
            "LEFT JOIN sources s ON s.media_id = m.id AND s.provider = 'cuevana3' "
            "WHERE m.media_type = 'movie' AND m.id = ?",
            (media_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return MediaItem(
        media_id=str(row[0]),
        provider="cuevana3",
        provider_id=row[13] or str(row[0]),
        title=row[1],
        original_title=row[2],
        media_type=MediaType.MOVIE,
        year=row[4],
        overview=row[5],
        poster_url=row[6],
        genres=json.loads(row[7]) if row[7] else [],
        cast=json.loads(row[8]) if row[8] else [],
        director=row[9] or "",
        duration=row[10] or "",
        rating=row[11] or 0,
        country=row[12] or "",
    )
```

4. NO modificar todavía el endpoint `get_vod_info` ni ninguna otra función en este paso.
5. Guardar los cambios y verificar que el archivo compile sin errores de sintaxis (`python3 -m py_compile src/api/xtream.py`).

---

## PASO 2: Conectar consulta directa en `action == "get_vod_info"` en `src/api/xtream.py`

### Archivo a modificar
- `src/api/xtream.py`

### Objetivo
Sustituir la carga completa del catálogo y la búsqueda lineal en memoria dentro del bloque `if action == "get_vod_info":` por la llamada directa a `_load_single_movie_from_db(media_id)`.

### Instrucciones
1. Leer `src/api/xtream.py` y localizar el bloque `if action == "get_vod_info":` (aproximadamente entre líneas 283 y 311).
2. Verificar si en la función contenedora se obtiene `db_path` desde `request.app.state` (por ejemplo `getattr(request.app.state, "db_path", None)`), de forma que si existe soporte para aislar la base de datos en tests, se pase a la llamada.
3. Reemplazar el bloque existente de `if action == "get_vod_info":` exactamente por lo siguiente:

```python
    if action == "get_vod_info":
        vod_id = request.query_params.get("vod_id", "")
        try:
            stream_id = int(vod_id)
        except ValueError:
            return {}

        media_id = stream_id - MOVIE_STREAM_ID_BASE
        if media_id <= 0:
            return {}

        db_path = getattr(request.app.state, "db_path", None) if hasattr(request, "app") and hasattr(request.app, "state") else None
        item = await _load_single_movie_from_db(media_id, db_path=db_path)
        if item is None:
            return {}

        return {
            "info": {
                "name": item.title,
                "o_name": item.title,
                "movie_image": item.poster_url or "",
                "releasedate": str(item.year) if item.year else "",
                "plot": item.overview or "",
                "cast": ", ".join(item.cast or []),
                "director": item.director or "",
                "duration": item.duration or "",
                "rating": str(item.rating or 0),
                "country": item.country or "",
                "genre": ", ".join(item.genres),
            },
            "movie_data": _media_item_to_vod_stream(item, stream_id - MOVIE_STREAM_ID_BASE),
        }
```

4. Mantener intactas las demás acciones (`get_vod_streams`, `get_series`, etc.) y la función `_load_catalog_from_db`.
5. Guardar los cambios y verificar que compile y los tests pasen.

---

ACEPTACION
grep -q "async def _load_single_movie_from_db" src/api/xtream.py
grep -q "WHERE m.media_type = 'movie' AND m.id = ?" src/api/xtream.py
grep -q "media_id = stream_id - MOVIE_STREAM_ID_BASE" src/api/xtream.py
grep -q "item = await _load_single_movie_from_db(media_id" src/api/xtream.py
pytest tests/test_xtream.py -k "vod_info" -v
pytest tests/test_xtream.py -v

PREMISES
- `DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "gateway.db"` (línea 18)
- `MOVIE_STREAM_ID_BASE = 100_000` (línea 19)
- Tabla `media` tiene columnas: `id, title, original_title, media_type, year, synopsis, poster_url, genres, cast, director, duration, rating, country` (ver tests líneas 204-212, 854-862)
- Tabla `sources` tiene columnas: `id, media_id, provider, url, quality, language` (ver tests líneas 214-220, 864-870)
- `_movie_stream_id(movie, idx) = MOVIE_STREAM_ID_BASE + int(movie.media_id)` (línea 78)
- Los tests usan `temp_db_path` fixture que crea esquema compatible (líneas 199-232, 849-880)
- Test de regresión `test_get_vod_info_uses_db_not_provider` (líneas 978-1000) verifica que NO llama a proveedor

A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
