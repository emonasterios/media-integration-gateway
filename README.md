# Media Integration Gateway

Un gateway de streaming extensible que normaliza catálogos de múltiples proveedores de contenido y expone interfaces uniformes para clientes IPTV (Xtream Codes), listas M3U y aplicaciones web.

## ¿Qué hace?

Resuelve URLs de video directo (MP4/HLS) desde sitios de streaming con protección anti-bot, combinando catálogos de múltiples fuentes en un solo punto de acceso compatible con cualquier cliente IPTV.

## Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│                    Media Integration Gateway                 │
│  FastAPI (Python 3.11)                                       │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  REST/JSON   │  │  M3U/XMLTV   │  │   Xtream Codes   │   │
│  │  /api/v1/*   │  │  /iptv/*     │  │   /player_api.php│   │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘   │
│         └─────────────────┼───────────────────┘              │
│                           ▼                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              CatalogService (multi-provider)          │   │
│  │  - Normaliza modelos Pydantic canónicos               │   │
│  │  - Fusiona catálogos de todos los adapters activos    │   │
│  │  - Caché Redis opcional                               │   │
│  └──────────────────────┬───────────────────────────────┘   │
│                         ▼                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ Cuevana3     │  │ CuevanNet    │  │  (más adapters)  │   │
│  │ Adapter      │  │ Adapter      │  │                  │   │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘   │
│         └─────────────────┼───────────────────┘              │
│                           ▼                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              VideoResolver + FlareSolverr             │   │
│  │  - voe.sx       → HLS/MP4 directo                     │   │
│  │  - doodstream   → HLS/MP4 directo                     │   │
│  │  - streamtape   → HLS/MP4 directo                     │   │
│  │  - morencius    → HLS (Dean Edwards Packer)           │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Principios

- **Desacoplamiento**: los clientes no conocen la implementación de cada proveedor
- **Extensibilidad**: nuevas fuentes se incorporan implementando `BaseAdapter`
- **Modelo canónico**: películas, series, temporadas y episodios usan estructuras Pydantic comunes
- **Resolución bajo demanda**: la URL de reproducción se obtiene cuando el usuario la solicita
- **Redirect, no proxy**: para videos directos (MP4/HLS) se redirige al CDN; la TV maneja byte-range nativamente

## Estructura del proyecto

```
media-integration-gateway/
├── src/
│   ├── api/
│   │   ├── routes.py          # Endpoints REST/JSON
│   │   ├── m3u.py             # Endpoints M3U/XMLTV
│   │   └── xtream.py          # Endpoints Xtream Codes API
│   ├── core/
│   │   └── config.py          # Configuración (env vars)
│   ├── db/
│   │   ├── database.py        # Async SQLAlchemy engine
│   │   └── models.py          # Modelos ORM
│   ├── models/
│   │   ├── catalog.py         # Modelos Pydantic canónicos
│   │   └── xtream.py          # Modelos Xtream Codes
│   ├── services/
│   │   ├── catalog.py         # CatalogService (multi-provider)
│   │   ├── cache.py           # Caché (Redis/memory)
│   │   ├── flaresolverr.py    # Cliente FlareSolverr (anti-bot)
│   │   └── video_resolver.py  # Resolución de embeds → URL directa
│   ├── adapters/
│   │   ├── base.py            # BaseAdapter (interfaz)
│   │   ├── cuevana3.py        # Adapter cuevana3i.cc
│   │   └── cuevan_net.py      # Adapter cuevan.net
│   └── main.py                # Punto de entrada FastAPI
├── tests/
├── alembic/                   # Migraciones DB
├── Dockerfile
├── docker-compose.yml
├── docker-compose-infra.yml   # FlareSolverr + Redis
└── pyproject.toml
```

## Stack

| Componente | Tecnología |
|---|---|
| Backend/API | FastAPI (Python 3.11) |
| Base de datos | SQLite (async) → escalable a PostgreSQL |
| Anti-bot | FlareSolverr (servicio externo) |
| Caché | Redis (opcional) |
| Deploy | Docker Compose |

## Adapters implementados

### Cuevana3 (`cuevana3i.cc`)
- **Catálogo**: ~1300 películas
- **Paginación**: scraping con paginación `/page/N/`
- **Resolución**: Voe.sx, Doodstream, Playmogo
- **Anti-bot**: FlareSolverr para bypass de Cloudflare

### CuevanNet (`cuevan.net`)
- **Catálogo**: ~240 películas + ~210 series
- **Paginación**: query param `?page=N` (configurable, default 10 páginas)
- **Embeds**: URLs firmadas con `expires` + `signature`
- **Resolución**: Streamtape, Morencius
- **Anti-bot**: FlareSolverr para bypass de Cloudflare

### VideoResolver — dominios soportados

| Dominio | Método | Salida |
|---|---|---|
| `voe.sx` | FlareSolverr + regex | HLS/MP4 directo |
| `doodstream.com` | FlareSolverr + regex | HLS/MP4 directo |
| `streamtape.com` | FlareSolverr + regex | HLS/MP4 directo |
| `morencius.com` | FlareSolverr + deobfuscación Dean Edwards Packer | HLS (m3u8) |

## Endpoints

### Xtream Codes API (para clientes IPTV/TV)

| Endpoint | Método | Descripción |
|---|---|---|
| `/player_api.php` | GET | Autenticación + info de cuenta |
| `/player_api.php?action=get_vod_streams` | GET | Catálogo completo de películas |
| `/player_api.php?action=get_series` | GET | Catálogo de series |
| `/player_api.php?action=get_vod_info&vod_id=N` | GET | Detalle de película |
| `/movie/{user}/{pass}/{stream_id}` | GET | URL de reproducción (302 redirect) |
| `/series/{user}/{pass}/{series_id}/{season}/{episode}` | GET | URL de episodio |

### REST API

| Endpoint | Método | Descripción |
|---|---|---|
| `/api/v1/movies` | GET | Lista de películas (JSON) |
| `/api/v1/movies/{movie_id}` | GET | Detalle de película |
| `/api/v1/series` | GET | Lista de series |
| `/api/v1/series/{series_id}` | GET | Detalle de serie |
| `/api/v1/search?q=...` | GET | Búsqueda en catálogo |

### M3U / XMLTV

| Endpoint | Método | Descripción |
|---|---|---|
| `/iptv/playlist.m3u` | GET | Lista M3U completa |
| `/iptv/xmltv.xml` | GET | Guía XMLTV |

### Health

| Endpoint | Método | Descripción |
|---|---|---|
| `/healthz` | GET | Estado del servicio |

## Configuración

Variables de entorno (`.env`):

```bash
# Server
HOST=0.0.0.0
PORT=9193

# Database
DATABASE_URL=sqlite+aiosqlite:///./data/media_gateway.db

# FlareSolverr
FLARESOLVERR_URL=http://flaresolverr:8191

# Redis (opcional)
REDIS_URL=redis://redis:6379/0

# Xtream Codes
XTREAM_USER=test
XTREAM_PASS=test
```

## Desarrollo

```bash
# Crear entorno virtual
python3 -m venv .venv
source .venv/bin/activate

# Instalar dependencias
pip install -e ".[dev]"

# Ejecutar tests
pytest

# Iniciar servidor
uvicorn src.main:app --reload
```

## Deploy con Docker

### Infraestructura (FlareSolverr + Redis)

```bash
docker compose -f docker-compose-infra.yml up -d
```

### Gateway

```bash
docker compose up -d --build
```

### Verificar

```bash
curl http://localhost:9193/healthz
# {"status":"ok"}
```

## Agregar un nuevo adapter

1. Crear `src/adapters/mi_provider.py` heredando de `BaseAdapter`
2. Implementar: `name`, `paginate()`, `parse_item()`, `get_playback_url()`
3. Registrar en `src/main.py`:
   ```python
   from src.adapters.mi_provider import MiProviderAdapter
   adapter = MiProviderAdapter()
   catalog = CatalogService(providers=[..., adapter])
   ```
4. El endpoint Xtream fusiona automáticamente el catálogo

## Catálogo combinado actual

| Provider | Películas | Series | Total |
|---|---|---|---|
| Cuevana3 | ~1300 | — | ~1300 |
| CuevanNet | ~240 | ~210 | ~450 |
| **Total** | **~1540** | **~210** | **~1750** |

## Licencia

Uso personal.
