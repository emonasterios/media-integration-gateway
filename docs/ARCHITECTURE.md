# Media Integration Gateway — Arquitectura y Solución

## Visión General

Gateway de streaming extensible que normaliza catálogos de múltiples proveedores de contenido y expone interfaces uniformes para clientes IPTV (Xtream Codes), listas M3U/XMLTV y aplicaciones web REST.

**Stack**: FastAPI 3.11 + SQLite (async) + FlareSolverr + Docker Compose

---

## Diagrama de Arquitectura

```
┌─────────────────────────────────────────────────────────────────┐
│                    Media Integration Gateway                     │
│  FastAPI (Python 3.11)                                           │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐      │
│  │  REST/JSON   │  │  M3U/XMLTV   │  │   Xtream Codes   │      │
│  │  /api/v1/*   │  │  /iptv/*     │  │   /player_api.php│      │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘      │
│         └─────────────────┼───────────────────┘                 │
│                           ▼                                     │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              CatalogService (multi-provider)            │    │
│  │  - Normaliza modelos Pydantic canónicos                 │    │
│  │  - Fusiona catálogos de todos los adapters activos      │    │
│  │  - Caché SQLite con TTL (opcional Redis)                │    │
│  └──────────────────────┬────────────────────────────────┘    │
│                         ▼                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐    │
│  │ Cuevana3     │  │ CuevanNet    │  │  (más adapters)  │    │
│  │ Adapter      │  │ Adapter      │  │                  │    │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘    │
│         └─────────────────┼───────────────────┘               │
│                           ▼                                     │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              VideoResolver + FlareSolverr               │    │
│  │  - voe.sx       → HLS/MP4 directo                       │    │
│  │  - doodstream   → HLS/MP4 directo                       │    │
│  │  - streamtape   → HLS/MP4 directo                       │    │
│  │  - morencius    → HLS (Dean Edwards Packer)             │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Componentes Principales

### 1. CatalogService (`src/services/catalog.py`)

Orquesta múltiples `MediaProvider` (adapters):

- **Cache en memoria** con TTL configurable (`_catalog_cache` + `_catalog_locks`)
- **Cache persistente** opcional vía `CatalogCache` (SQLite)
- **Búsqueda local** sobre catálogo cacheado (filtrado por título)
- **Resolución bajo demanda**: `resolve_playback()` delega al adapter correspondiente

```python
catalog = CatalogService(
    providers=[Cuevana3Adapter(), CuevanNetAdapter()],
    cache=CatalogCache(db_session),
    catalog_ttl_seconds=3600
)
```

### 2. BaseAdapter (`src/adapters/base.py`)

Contrato abstracto que todo proveedor debe implementar:

```python
class MediaProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def search(self, query: str) -> SearchResult: ...

    @abstractmethod
    async def get_details(self, media_id: str) -> MediaItem: ...

    @abstractmethod
    async def get_seasons(self, media_id: str) -> list[Season]: ...

    @abstractmethod
    async def get_episodes(self, media_id: str, season_number: int) -> list[Episode]: ...

    @abstractmethod
    async def resolve_playback(self, media_id: str) -> PlaybackDescriptor: ...

    @abstractmethod
    async def get_catalog(self, category: str | None = None) -> list[MediaItem]: ...
```

### 3. Adapters Implementados

| Adapter | Sitio | Catálogo | Resolución | Anti-bot |
|---------|-------|----------|------------|----------|
| `Cuevana3Adapter` | cuevana3i.cc | ~1300 películas | Voe, Doodstream, Playmogo | FlareSolverr |
| `CuevanNetAdapter` | cuevan.net | ~240 películas + ~210 series | Streamtape, Morencius | **Ninguno** |

### 4. VideoResolver (`src/services/video_resolver.py`)

Resuelve embeds de servidores externos a URLs de video directo (MP4/HLS):

| Dominio | Método | Salida |
|---------|--------|--------|
| `doodstream.com` + aliases | `pass_md5` + token + timestamp | MP4 directo |
| `voe.sx` + unblocks | FlareSolverr + regex en scripts | HLS/MP4 |
| `streamtape.com` | `div#videolink` + scripts | MP4 directo |
| `morencius.com` | FlareSolverr + Dean Edwards Packer unpack | HLS (m3u8) |

**Validación estricta**: `_validate_video_url()` hace HEAD siguiendo redirects y rechaza:
- Content-Type HTML/JSON/text
- Status ≥ 400
- Dominios placeholder conocidos (test-videos.co.uk, etc.)
- 302 sin resolver final

### 5. FlareSolverrClient (`src/services/flaresolverr.py`)

Cliente **síncrono** (problema conocido — ver § Problemas) para bypass Cloudflare:

```python
payload = {"cmd": "request.get", "url": url, "maxTimeout": 60000}
response = httpx.post(f"{base_url}/v1", json=payload, timeout=70)
return response.json().get("solution")
```

### 6. Endpoints API

| Interfaz | Prefijo | Endpoints Clave |
|----------|---------|-----------------|
| REST | `/api/v1` | `/search`, `/catalog/{provider}`, `/details/{provider}/{id}`, `/resolve/{provider}/{id}` |
| M3U/XMLTV | `/iptv` | `/playlist.m3u`, `/xmltv.xml` |
| Xtream Codes | `/` | `/player_api.php?action=*` |
| Health | `/` | `/healthz` |

---

## Modelo de Datos Canónico (Pydantic)

```python
class MediaItem(BaseModel):
    media_id: str              # "cuevana3:slug-pelicula"
    title: str
    media_type: MediaType      # MOVIE | SERIES | EPISODE
    year: int | None
    poster_url: str | None
    overview: str | None
    provider: str              # "cuevana3" | "cuevan_net"
    provider_id: str           # slug original del proveedor
    available_languages: list[str] = ["es"]
    # Enriquecidos (opcionales)
    director: str | None
    cast: list[str] | None
    country: str | None
    trailer_url: str | None
    duration: str | None
    genres: list[str] = []
    rating: float | None

class PlaybackDescriptor(BaseModel):
    protocol: str              # "mp4" | "hls" | "embed"
    url: str
    headers: dict = {}
```

---

## Base de Datos (SQLAlchemy Async)

```python
class Media(Base):
    __tablename__ = "media"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    media_type = Column(String, nullable=False)  # "movie" | "series" | "episode"
    year = Column(Integer)
    synopsis = Column(Text)
    poster_url = Column(String)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)  # Clave para TTL caché

class Source(Base):
    __tablename__ = "sources"
    id = Column(Integer, primary_key=True)
    media_id = Column(Integer, ForeignKey("media.id"))
    provider = Column(String, nullable=False)  # "cuevana3"
    url = Column(String, nullable=False)       # slug/provider_id
    quality = Column(String)
    language = Column(String)
```

**Caché TTL**: `CatalogCache.is_valid(media)` → `datetime.utcnow() - media.updated_at <= ttl_seconds`

---

## Despliegue

### Docker Compose (Producción)

```yaml
# docker-compose.yml
services:
  media-gateway:
    build: .
    ports: ["9193:8000"]
    environment:
      - DATABASE_URL=sqlite+aiosqlite:///./data/gateway.db
      - FLARESOLVERR_URL=http://flaresolverr:8191
    healthcheck: curl -f http://localhost:8000/healthz

  flaresolverr:
    image: ghcr.io/flaresolverr/flaresolverr:latest
    ports: ["8191:8191"]
```

```bash
docker compose up -d --build
curl http://localhost:9193/healthz  # {"status":"ok"}
```

### Desarrollo Local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn src.main:app --reload --port 9193
pytest tests/ -v
```

---

## Flujo de Resolución de Video

```
Cliente IPTV solicita /movie/user/pass/1234
         │
         ▼
Xtream endpoint stream_movie() → CatalogService.resolve_playback("cuevana3", "slug")
         │
         ▼
Cuevana3Adapter.resolve_playback()
  1. GET /pelicula/slug/ (con FlareSolverr fallback)
  2. Extrae TODOS los servidores candidatos (li[data-server], div[data-mdl], scripts, enlaces)
  3. Para cada candidato, prueba VideoResolver.resolve_*()
  4. Retorna PlaybackDescriptor(protocol="hls|mp4", url=direct_cdn_url)
         │
         ▼
stream_movie() → RedirectResponse 302 a URL directa del CDN
         │
         ▼
TV/Cliente reproduce con byte-range nativo (sin proxy)
```

**Principio**: *Redirect, no proxy* — el gateway solo resuelve y redirige; el CDN sirve el video.

---

## Extensibilidad: Agregar Nuevo Adapter

1. Crear `src/adapters/mi_proveedor.py` heredando `MediaProvider`
2. Implementar 6 métodos abstractos
3. Registrar en `src/main.py`:

```python
from src.adapters.mi_proveedor import MiProveedorAdapter
adapter = MiProveedorAdapter()
catalog = CatalogService(providers=[existing..., adapter])
```

El endpoint Xtream fusiona automáticamente el catálogo.

---

## Catálogo Actual (2026-10-03)

| Provider | Películas | Series | Total |
|----------|-----------|--------|-------|
| Cuevana3 | ~1300 | — | ~1300 |
| CuevanNet | ~240 | ~210 | ~450 |
| **Total** | **~1540** | **~210** | **~1750** |