# Fase 5: Xtream Codes API Compatible

Implementar endpoints compatibles con la API de Xtream Codes para que clientes IPTV (IPTV Smarters, TiviMate, etc.) puedan consumir el catálogo del gateway.

## QUÉ HACER

### 1. Nuevo archivo: `src/api/xtream.py`

Router FastAPI con prefijo vacío (las rutas de Xtream Codes son planas, sin `/api/v1/`).

Endpoints requeridos (todos GET):

```python
# Autenticación — devuelve account info + server info
@router.get("/player_api.php")
async def player_api(username: str, password: str, action: str | None = None):
    ...

# Panel info
@router.get("/panel_api.php")
async def panel_api(username: str, password: str):
    ...
```

**Lógica de autenticación:**
- `username` y `password` son obligatorios en ambos endpoints
- Si no hay auth válida → devolver `{"user_info": {"auth": 0}, "server_info": {}}`
- Auth válida: cualquier username/password no vacío es válido (sin sistema de usuarios real aún)
- Si `action` está presente en `player_api.php`, despachar según el valor

**Actions soportadas en `player_api.php`:**

| action | respuesta |
|---|---|
| `get_vod_categories` | `{"categories": [{"category_id": "1", "category_name": "Peliculas", "parent_id": 0}]}` |
| `get_series_categories` | `{"categories": [{"category_id": "2", "category_name": "Series", "parent_id": 0}]}` |
| `get_live_categories` | `{"categories": [{"category_id": "3", "category_name": "TV en Vivo", "parent_id": 0}]}` |
| `get_vod_streams` | Lista de películas del catálogo (formato Xtream) |
| `get_series` | Lista de series del catálogo (formato Xtream) |
| `get_live_streams` | Lista vacía `[]` (no hay TV en vivo aún) |
| Sin action | Account info completo (default) |

**Formato de respuesta — account info (default):**
```json
{
  "user_info": {
    "username": "<username>",
    "password": "<password>",
    "status": "Active",
    "exp_date": "4102444800",
    "is_trial": "0",
    "active_cons": "0",
    "created_at": "2026-10-02",
    "max_connections": "1",
    "allowed_output_formats": ["m3u8", "mp4", "ts"]
  },
  "server_info": {
    "url": "<request.base_url>",
    "port": "8080",
    "https_port": "",
    "server_protocol": "http",
    "rtmp_port": "",
    "timezone": "America/Caracas",
    "timestamp_now": "<unix_timestamp>",
    "time_now": "2026-10-02 12:00:00"
  }
}
```

**Formato de respuesta — panel_api.php:**
```json
{
  "panel_info": {
    "live_streams": 0,
    "vod_streams": <count_peliculas>,
    "series_streams": <count_series>,
    "episodes": 0,
    "active_connections": 0,
    "max_connections": 1
  }
}
```

**Formato de streams VOD (get_vod_streams):**
Cada item del catálogo de películas se convierte a:
```json
{
  "num": 1,
  "name": "Nombre de la Película",
  "stream_type": "movie",
  "stream_id": 1001,
  "stream_icon": "https://poster.url/image.jpg",
  "rating": "0",
  "rating_5based": 0,
  "added": "1696204800",
  "category_id": "1",
  "container_extension": "mp4",
  "custom_sid": "",
  "direct_source": ""
}
```

**Formato de series (get_series):**
```json
{
  "num": 1,
  "name": "Nombre de la Serie",
  "series_id": 2001,
  "cover": "https://poster.url/image.jpg",
  "plot": "Sinopsis de la serie",
  "cast": "",
  "director": "",
  "genre": "",
  "releaseDate": "2026-01-01",
  "last_modified": "1696204800",
  "rating": "0",
  "rating_5based": 0,
  "backdrop_path": [],
  "youtube_trailer": "",
  "episode_run_time": 0,
  "category_id": "2"
}
```

### 2. Nuevo archivo: `src/models/xtream.py`

Modelos Pydantic para las respuestas de Xtream Codes:

```python
from pydantic import BaseModel
from typing import Optional

class XtreamUserInfo(BaseModel):
    username: str
    password: str
    status: str = "Active"
    exp_date: str = "4102444800"
    is_trial: str = "0"
    active_cons: str = "0"
    created_at: str = ""
    max_connections: str = "1"
    allowed_output_formats: list[str] = ["m3u8", "mp4", "ts"]

class XtreamServerInfo(BaseModel):
    url: str
    port: str = "8080"
    https_port: str = ""
    server_protocol: str = "http"
    rtmp_port: str = ""
    timezone: str = "America/Caracas"
    timestamp_now: str = ""
    time_now: str = ""

class XtreamAccountInfo(BaseModel):
    user_info: XtreamUserInfo
    server_info: XtreamServerInfo

class XtreamCategory(BaseModel):
    category_id: str
    category_name: str
    parent_id: int = 0

class XtreamCategoriesResponse(BaseModel):
    categories: list[XtreamCategory]

class XtreamVodStream(BaseModel):
    num: int
    name: str
    stream_type: str = "movie"
    stream_id: int
    stream_icon: str = ""
    rating: str = "0"
    rating_5based: float = 0.0
    added: str = ""
    category_id: str = "1"
    container_extension: str = "mp4"
    custom_sid: str = ""
    direct_source: str = ""

class XtreamSeriesStream(BaseModel):
    num: int
    name: str
    series_id: int
    cover: str = ""
    plot: str = ""
    cast: str = ""
    director: str = ""
    genre: str = ""
    releaseDate: str = ""
    last_modified: str = ""
    rating: str = "0"
    rating_5based: float = 0.0
    backdrop_path: list = []
    youtube_trailer: str = ""
    episode_run_time: int = 0
    category_id: str = "2"

class XtreamPanelInfo(BaseModel):
    live_streams: int = 0
    vod_streams: int = 0
    series_streams: int = 0
    episodes: int = 0
    active_connections: int = 0
    max_connections: int = 1

class XtreamPanelResponse(BaseModel):
    panel_info: XtreamPanelInfo
```

### 3. Funciones de conversión en `src/api/xtream.py`

```python
def _media_item_to_vod_stream(item: MediaItem, index: int) -> dict:
    """Convierte un MediaItem de película a formato Xtream VOD stream."""
    return {
        "num": index,
        "name": item.title,
        "stream_type": "movie",
        "stream_id": 1000 + index,
        "stream_icon": item.poster_url or "",
        "rating": "0",
        "rating_5based": 0.0,
        "added": str(int(item.year * 31536000)) if item.year else "",
        "category_id": "1",
        "container_extension": "mp4",
        "custom_sid": "",
        "direct_source": "",
    }

def _media_item_to_series_stream(item: MediaItem, index: int) -> dict:
    """Convierte un MediaItem de serie a formato Xtream series stream."""
    return {
        "num": index,
        "name": item.title,
        "series_id": 2000 + index,
        "cover": item.poster_url or "",
        "plot": item.overview or "",
        "cast": "",
        "director": "",
        "genre": "",
        "releaseDate": f"{item.year}-01-01" if item.year else "",
        "last_modified": "",
        "rating": "0",
        "rating_5based": 0.0,
        "backdrop_path": [],
        "youtube_trailer": "",
        "episode_run_time": 0,
        "category_id": "2",
    }
```

### 4. Registrar router en `src/main.py`

Incluir el router de xtream en la app:
```python
from src.api.xtream import router as xtream_router
app.include_router(xtream_router)
```

### 5. Tests: `tests/test_xtream.py`

Tests para:
- `test_player_api_auth_valid` — username/password válidos devuelven user_info con auth=1
- `test_player_api_auth_invalid` — sin credenciales o vacías devuelven auth=0
- `test_player_api_default_action` — sin action, devuelve account info completo
- `test_player_api_get_vod_categories` — devuelve lista de categorías VOD
- `test_player_api_get_series_categories` — devuelve lista de categorías series
- `test_player_api_get_live_categories` — devuelve lista de categorías live
- `test_player_api_get_live_streams` — devuelve lista vacía
- `test_panel_api` — devuelve panel_info con contadores
- `test_vod_stream_conversion` — MediaItem de película se convierte correctamente
- `test_series_stream_conversion` — MediaItem de serie se convierte correctamente

## QUÉ NO TOCAR
- No modificar `src/api/routes.py`
- No modificar `src/api/m3u.py`
- No modificar `src/adapters/`
- No modificar `src/services/`
- No modificar `src/models/catalog.py`
- No modificar tests existentes

## ACEPTACION
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/test_xtream.py -v
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v --tb=short | tail -5

## PREMISES
- src/main.py:1-65 — create_app() incluye routers de routes y m3u; xtream_router debe incluirse igual
- src/models/catalog.py:1-70 — MediaItem tiene title, media_type (MOVIE/SERIES), poster_url, overview, year
- src/adapters/base.py:17-47 — MediaProvider define la interfaz de adapters
- src/api/m3u.py:1-100 — Patrón existente de router con Depends(CatalogService)
- tests/test_m3u.py:49-86 — Fixture pattern con FakeProvider, db_engine, app_with_db, client
- .fabrica-verify existe en la raíz del repo
- Python 3.11 con FastAPI, pydantic, pytest, httpx disponibles en .venv
