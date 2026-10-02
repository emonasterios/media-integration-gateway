<!-- spec:861680ab46edbda5a5d3739d6b5bf2c2 -->
REGLAS DE TRABAJO:
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

ADVERTENCIA DE FONDO (CRÍTICO):
En `src/models/xtream.py`, el modelo `XtreamUserInfo` DEBE incluir explícitamente el campo `auth: int = 1`. De lo contrario, las respuestas válidas no incluirán `auth=1` y los clientes Xtream fallarán al validar credenciales. Además, en los endpoints de `src/api/xtream.py`, los parámetros `username: str = ""` y `password: str = ""` deben tener valores por defecto para permitir que una petición sin credenciales o con credenciales vacías devuelva el JSON esperado `{"user_info": {"auth": 0}, "server_info": {}}` en lugar de fallar con un error 422 de validación de FastAPI.

## PASO 1: Modelos Pydantic en `src/models/xtream.py`

Crear el archivo nuevo `src/models/xtream.py`.
Debe definir los modelos Pydantic necesarios para la compatibilidad con Xtream Codes API:

1. `XtreamUserInfo`:
   - `username: str`
   - `password: str`
   - `auth: int = 1`
   - `status: str = "Active"`
   - `exp_date: str = "4102444800"`
   - `is_trial: str = "0"`
   - `active_cons: str = "0"`
   - `created_at: str = ""`
   - `max_connections: str = "1"`
   - `allowed_output_formats: list[str] = ["m3u8", "mp4", "ts"]`

2. `XtreamServerInfo`:
   - `url: str`
   - `port: str = "8080"`
   - `https_port: str = ""`
   - `server_protocol: str = "http"`
   - `rtmp_port: str = ""`
   - `timezone: str = "America/Caracas"`
   - `timestamp_now: str = ""`
   - `time_now: str = ""`

3. `XtreamAccountInfo`:
   - `user_info: XtreamUserInfo`
   - `server_info: XtreamServerInfo`

4. `XtreamCategory`:
   - `category_id: str`
   - `category_name: str`
   - `parent_id: int = 0`

5. `XtreamCategoriesResponse`:
   - `categories: list[XtreamCategory]`

6. `XtreamVodStream`:
   - `num: int`
   - `name: str`
   - `stream_type: str = "movie"`
   - `stream_id: int`
   - `stream_icon: str = ""`
   - `rating: str = "0"`
   - `rating_5based: float = 0.0`
   - `added: str = ""`
   - `category_id: str = "1"`
   - `container_extension: str = "mp4"`
   - `custom_sid: str = ""`
   - `direct_source: str = ""`

7. `XtreamSeriesStream`:
   - `num: int`
   - `name: str`
   - `series_id: int`
   - `cover: str = ""`
   - `plot: str = ""`
   - `cast: str = ""`
   - `director: str = ""`
   - `genre: str = ""`
   - `releaseDate: str = ""`
   - `last_modified: str = ""`
   - `rating: str = "0"`
   - `rating_5based: float = 0.0`
   - `backdrop_path: list = []`
   - `youtube_trailer: str = ""`
   - `episode_run_time: int = 0`
   - `category_id: str = "2"`

8. `XtreamPanelInfo`:
   - `live_streams: int = 0`
   - `vod_streams: int = 0`
   - `series_streams: int = 0`
   - `episodes: int = 0`
   - `active_connections: int = 0`
   - `max_connections: int = 1`

9. `XtreamPanelResponse`:
   - `panel_info: XtreamPanelInfo`

Verificar que el archivo compila sin errores de sintaxis (`python3 -c "import src.models.xtream"`).

## PASO 2: Router y conversión en `src/api/xtream.py`

Crear el archivo nuevo `src/api/xtream.py`.
1. Leer primero `src/api/m3u.py` para reutilizar el mismo patrón de inyección de dependencias para `CatalogService` (función `get_catalog_service` o `Depends`).
2. Importar `MediaType` y `MediaItem` desde `src.models.catalog`.
3. Implementar las funciones auxiliares de mapeo:
   - `_media_item_to_vod_stream(item: MediaItem, index: int) -> dict`: mapea `num=index`, `name=item.title`, `stream_type="movie"`, `stream_id=1000 + index`, `stream_icon=item.poster_url or ""`, `added=str(int(item.year * 31536000)) if item.year else ""`, `category_id="1"`, `container_extension="mp4"`, etc.
   - `_media_item_to_series_stream(item: MediaItem, index: int) -> dict`: mapea `num=index`, `name=item.title`, `series_id=2000 + index`, `cover=item.poster_url or ""`, `plot=item.overview or ""`, `releaseDate=f"{item.year}-01-01" if item.year else ""`, `category_id="2"`, etc.
4. Crear el router FastAPI sin prefijo de ruta: `router = APIRouter(tags=["xtream"])`.
5. Implementar el endpoint `@router.get("/player_api.php")`:
   - Parámetros: `request: Request`, `username: str = ""`, `password: str = ""`, `action: str | None = None`, `catalog_service: CatalogService = Depends(...)`.
   - Autenticación: si `not username or not password`, retornar `{"user_info": {"auth": 0}, "server_info": {}}`.
   - Con autenticación válida:
     - `action == "get_vod_categories"`: devolver `{"categories": [{"category_id": "1", "category_name": "Peliculas", "parent_id": 0}]}`.
     - `action == "get_series_categories"`: devolver `{"categories": [{"category_id": "2", "category_name": "Series", "parent_id": 0}]}`.
     - `action == "get_live_categories"`: devolver `{"categories": [{"category_id": "3", "category_name": "TV en Vivo", "parent_id": 0}]}`.
     - `action == "get_vod_streams"`: obtener el catálogo mediante `catalog_service`, filtrar ítems con `media_type == MediaType.MOVIE`, convertirlos con `_media_item_to_vod_stream` y devolver la lista de diccionarios.
     - `action == "get_series"`: obtener el catálogo mediante `catalog_service`, filtrar ítems con `media_type == MediaType.SERIES`, convertirlos con `_media_item_to_series_stream` y devolver la lista de diccionarios.
     - `action == "get_live_streams"`: devolver la lista vacía `[]`.
     - Sin `action` (o vacío): devolver estructura completa `XtreamAccountInfo` o dict con `user_info` (incluyendo `auth=1`, `username`, `password`, status activo) y `server_info` (incluyendo `url=str(request.base_url).rstrip("/")`, port, timestamp_now, time_now).
6. Implementar el endpoint `@router.get("/panel_api.php")`:
   - Parámetros: `username: str = ""`, `password: str = ""`, `catalog_service: CatalogService = Depends(...)`.
   - Si `not username or not password`, retornar `{"user_info": {"auth": 0}, "server_info": {}}`.
   - Si es válido, contar películas y series del catálogo y devolver `{"panel_info": {"live_streams": 0, "vod_streams": count_peliculas, "series_streams": count_series, "episodes": 0, "active_connections": 0, "max_connections": 1}}`.

Verificar que el archivo compila sin errores (`python3 -c "import src.api.xtream"`).

## PASO 3: Registrar router en `src/main.py`

Modificar el archivo existente `src/main.py`.
1. Leer `src/main.py` antes de editar para ver cómo se importa e incluye `m3u_router`.
2. Agregar la importación:
   ```python
   from src.api.xtream import router as xtream_router
   ```
3. En la función `create_app()`, registrar el router en la aplicación:
   ```python
   app.include_router(xtream_router)
   ```
4. No alterar ninguna otra ruta, middleware ni configuración de `src/main.py`.

Verificar que la aplicación carga correctamente (`python3 -c "from src.main import create_app; app = create_app()"`).

## PASO 4: Tests en `tests/test_xtream.py`

Crear el archivo nuevo `tests/test_xtream.py`.
1. Leer `tests/test_m3u.py` para reutilizar el mismo patrón de fixtures: mock o `FakeProvider`, inyección de base de datos sqlite en memoria, inicialización de `app_with_db` y cliente HTTP de testing (`httpx.AsyncClient` o `TestClient`).
2. Implementar los siguientes tests:
   - `test_player_api_auth_valid`: llamada GET a `/player_api.php?username=test&password=test` responde 200 y `data["user_info"]["auth"] == 1`.
   - `test_player_api_auth_invalid`: llamada GET a `/player_api.php` sin username/password o con campos vacíos responde `{"user_info": {"auth": 0}, "server_info": {}}`.
   - `test_player_api_default_action`: llamada válida sin parámetro `action` responde con `user_info` y `server_info`.
   - `test_player_api_get_vod_categories`: `action=get_vod_categories` responde con categoría 1 "Peliculas".
   - `test_player_api_get_series_categories`: `action=get_series_categories` responde con categoría 2 "Series".
   - `test_player_api_get_live_categories`: `action=get_live_categories` responde con categoría 3 "TV en Vivo".
   - `test_player_api_get_live_streams`: `action=get_live_streams` responde con `[]`.
   - `test_player_api_get_vod_streams`: `action=get_vod_streams` responde con la lista formateada de películas del catálogo.
   - `test_player_api_get_series`: `action=get_series` responde con la lista formateada de series del catálogo.
   - `test_panel_api`: `/panel_api.php?username=test&password=test` responde con `panel_info` y contadores de VOD y series.
   - `test_vod_stream_conversion`: comprueba unitariamente la función `_media_item_to_vod_stream` con un `MediaItem(media_type=MediaType.MOVIE)`.
   - `test_series_stream_conversion`: comprueba unitariamente la función `_media_item_to_series_stream` con un `MediaItem(media_type=MediaType.SERIES)`.
3. Ejecutar los tests con `pytest tests/test_xtream.py -v` y verificar que pasen al 100%.

ACEPTACION
test -f src/models/xtream.py
grep -q "class XtreamUserInfo" src/models/xtream.py
grep -q "auth: int = 1" src/models/xtream.py
grep -q "class XtreamVodStream" src/models/xtream.py
test -f src/api/xtream.py
grep -q "/player_api.php" src/api/xtream.py
grep -q "/panel_api.php" src/api/xtream.py
grep -q "_media_item_to_vod_stream" src/api/xtream.py
grep -q "_media_item_to_series_stream" src/api/xtream.py
grep -q "from src.api.xtream import router as xtream_router" src/main.py
grep -q "app.include_router(xtream_router)" src/main.py
test -f tests/test_xtream.py
grep -q "test_player_api_auth_valid" tests/test_xtream.py
grep -q "test_panel_api" tests/test_xtream.py
grep -q "test_vod_stream_conversion" tests/test_xtream.py
pytest tests/test_xtream.py

PREMISES
- src/main.py:1-65 — create_app() incluye routers de routes y m3u; xtream_router debe incluirse igual
- src/models/catalog.py:1-70 — MediaItem tiene title, media_type (MOVIE/SERIES), poster_url, overview, year
- src/adapters/base.py:17-47 — MediaProvider define la interfaz de adapters
- src/api/m3u.py:1-100 — Patrón existente de router con Depends(CatalogService)
- tests/test_m3u.py:49-86 — Fixture pattern con FakeProvider, db_engine, app_with_db, client
- .fabrica-verify existe en la raíz del repo
- Python 3.11 con FastAPI, pydantic, pytest, httpx disponibles en .venv
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
