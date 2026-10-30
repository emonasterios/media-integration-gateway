# Encargo: Optimizar get_vod_info con query directo a SQLite

## Problema
El endpoint `get_vod_info` (líneas 283-311 en `src/api/xtream.py`) carga TODO el catálogo de películas (19,522 filas), lo ordena en Python y busca linealmente el `stream_id`. Esto causa latencia de 200-500ms por petición cuando la app hace focus en una película.

## Solución
Cambiar a query directo: `vod_id` → `media_id = vod_id - MOVIE_STREAM_ID_BASE` → `SELECT ... WHERE m.id = ?`.

## Qué TOCAR
- `src/api/xtream.py`: bloque `if action == "get_vod_info":` (líneas 283-311)
- Añadir función helper `_load_single_movie_from_db(media_id)` arriba del router

## Qué NO tocar
- `get_vod_streams` (sigue cargando todo para lista paginada)
- `get_series` 
- `_load_catalog_from_db` (la usan otros endpoints)
- Tests (deben seguir pasando)

## Código NUEVO (helper)
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

## Código MODIFICADO (bloque get_vod_info)
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

    item = await _load_single_movie_from_db(media_id)
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

## PREMISES
- `DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "gateway.db"` (línea 18)
- `MOVIE_STREAM_ID_BASE = 100_000` (línea 19)
- Tabla `media` tiene columnas: `id, title, original_title, media_type, year, synopsis, poster_url, genres, cast, director, duration, rating, country` (ver tests líneas 204-212, 854-862)
- Tabla `sources` tiene columnas: `id, media_id, provider, url, quality, language` (ver tests líneas 214-220, 864-870)
- `_movie_stream_id(movie, idx) = MOVIE_STREAM_ID_BASE + int(movie.media_id)` (línea 78)
- Los tests usan `temp_db_path` fixture que crea esquema compatible (líneas 199-232, 849-880)
- Test de regresión `test_get_vod_info_uses_db_not_provider` (líneas 978-1000) verifica que NO llama a proveedor

## ACEPTACION
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_xtream.py::test_get_vod_info_uses_db_not_provider -v
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_xtream.py::test_player_api_get_vod_info -v
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_xtream.py -k "vod_info" -v
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_xtream.py -v