# Encargo: Gateway V2 — Multi-sitio, URL desde BD, adapters dinámicos

## Contexto

El gateway actual (V1) tiene el dominio `cuevana3i.cc` hardcodeado en `src/adapters/cuevana3.py:38` (`BASE_URL`) y el adapter se instancia sin parámetros en `src/main.py:58`. Esto impide agregar contenido de otros sitios (ej: cuevana-8.com) sin modificar código.

La V2 debe leer la URL del source directamente desde la BD y despachar al resolver correcto según el host del video, sin depender de un adapter con dominio fijo.

## Principio de diseño

**La URL del source ES la fuente de verdad.** El `provider_id` en la BD debe ser la URL completa de la página del contenido (no un slug). Al reproducir:

1. Se lee `source.url` de la BD → esa es la página a scrapear
2. Se extrae el dominio base de esa URL → se usa como `base_url` para el scraper
3. Se scrapea la página para obtener los servidores de video
4. Se resuelve el video con los resolvers existentes (genéricos, ya funcionan)

## Qué NO tocar

- `src/adapters/cuevana3.py` — se mantiene intacto para V1
- `src/adapters/cuevan_net.py` — se mantiene intacto para V1
- `src/api/xtream.py` — se mantiene intacto para V1
- `src/services/video_resolver.py` — se mantiene intacto (resolvers genéricos)
- `src/services/mediaflow_bridge.py` — se mantiene intacto
- `src/db/models.py` — se mantiene intacto (el esquema ya soporta URLs completas)
- `src/services/cache.py` — se mantiene intacto
- Tests existentes — no se modifican

## Qué SÍ crear (archivos nuevos)

### 1. `src/adapters/universal.py` — Adapter multi-sitio

Un adapter que recibe la URL completa de la página y:
- Extrae el dominio base (`urlparse(url)._replace(path='', query='', fragment='').geturl()`)
- Usa ese dominio como `base_url` para el httpx client
- Hace scraping de la página (mismo algoritmo que `Cuevana3Adapter.resolve_playback` pero sin hardcodear dominio)
- Prueba cada servidor encontrado con los resolvers existentes

```python
class UniversalAdapter(MediaProvider):
    """Adapter que resuelve playback desde cualquier URL de página de contenido."""
    
    name = "universal"
    
    async def resolve_playback(self, page_url: str) -> PlaybackDescriptor:
        """page_url es la URL completa de la página (ej: https://cuevana-8.com/peliculas/the-creator)"""
        # 1. Extraer dominio base
        # 2. Fetch de la página con FlareSolverr fallback
        # 3. Extraer servidores (mismo algoritmo: li[data-server], scripts, links)
        # 4. Probar cada servidor con los resolvers existentes
        # 5. Si la URL es ya un MP4 directo (termina en .mp4/.mkv/.webm), devolverlo directo
```

**Detalle crítico — detección de MP4 directo:**
Si `page_url` contiene `.mp4`, `.mkv`, `.webm` en su path, devolver directamente:
```python
PlaybackDescriptor(protocol="mp4", url=page_url, referer=extract_domain(page_url))
```
Sin hacer scraping.

**Reutilización de código:**
El scraping de servidores debe reutilizar la lógica de `Cuevana3Adapter` pero sin el dominio hardcodeado. La forma limpia: extraer los métodos de extracción (`_extract_server_from_list`, `_extract_server_from_scripts`, `_is_known_server`, `_build_playback_descriptor`) a un módulo compartido `src/services/server_extraction.py` que reciba `soup` y `base_url` como parámetros.

### 2. `src/services/server_extraction.py` — Lógica de extracción compartida

Funciones puras que reciben `soup` (BeautifulSoup) y `base_url` (str):
- `extract_server_urls(soup, base_url) -> list[str]`
- `is_known_server(url) -> bool`
- `build_playback_descriptor(server_url, base_url) -> PlaybackDescriptor | None`

Estas funciones se copian/adaptan de `Cuevana3Adapter` pero como funciones independientes, sin referencia a `self._base`.

### 3. `src/services/flaresolverr.py` — Ya existe, se importa

El `FlareSolverrClient` ya existe y funciona. Se importa desde el adapter universal.

### 4. `src/api/routes_v2.py` — Nuevos endpoints (opcional, si se quiere API separada)

Si se decide tener endpoints separados para V2, crear aquí. Si no, se integra en `main.py` como provider adicional.

### 5. Modificación mínima en `src/main.py` — Registrar el nuevo adapter

Solo agregar `UniversalAdapter()` a la lista de providers en `create_app()`:

```python
from src.adapters.universal import UniversalAdapter
# ...
universal = UniversalAdapter()
catalog = CatalogService(providers=[adapter, cuevan_net, universal], cache=CatalogCache(db))
```

Esto es lo ÚNICO que se modifica en código existente.

## Flujo de playback V2

```
IPTV → stream_movie(stream_id)
  → _load_catalog_from_db() → MediaItem(provider="universal", provider_id="https://cuevana-8.com/peliculas/the-creator")
  → catalog_service.resolve_playback("universal", "https://cuevana-8.com/peliculas/the-creator")
  → UniversalAdapter.resolve_playback(page_url)
    → ¿URL es MP4 directo? → PlaybackDescriptor(protocol="mp4", url=page_url)
    → ¿No? → Fetch página → Extraer servidores → Probar resolvers → PlaybackDescriptor
  → xtream.py: si mp4 → proxy_stream, si hls → redirect, si embed → resolver
```

## ACEPTACION

```bash
# 1. El archivo universal.py existe y tiene la clase UniversalAdapter
test -f /home/emon/media-integration-gateway/src/adapters/universal.py
grep -q "class UniversalAdapter" /home/emon/media-integration-gateway/src/adapters/universal.py

# 2. El archivo server_extraction.py existe con funciones de extracción
test -f /home/emon/media-integration-gateway/src/services/server_extraction.py
grep -q "def extract_server_urls" /home/emon/media-integration-gateway/src/services/server_extraction.py

# 3. main.py registra UniversalAdapter sin modificar V1
grep -q "UniversalAdapter" /home/emon/media-integration-gateway/src/main.py
grep -q "cuevana3i.cc" /home/emon/media-integration-gateway/src/adapters/cuevana3.py

# 4. cuevana3.py intacto (no se modificó)
python3 -c "from src.adapters.cuevana3 import Cuevana3Adapter; print('OK')"

# 5. Insertar película de cuevana-8.com y reproducir
# (se hace manualmente en BD, luego se verifica que stream_movie devuelva 200 o 302)

# 6. Tests existentes pasan
cd /home/emon/media-integration-gateway && python -m pytest tests/ -q
```

## PREMISES

- `src/adapters/cuevana3.py:38` — `BASE_URL = "https://cuevana3i.cc"` (hardcodeado)
- `src/adapters/cuevana3.py:50-53` — `__init__` acepta `base_url` como parámetro pero se usa el default
- `src/adapters/cuevana3.py:807-874` — `resolve_playback` hace scraping de servidores con dominio fijo
- `src/adapters/cuevana3.py:880-882` — `_slug_from_url` extrae el último segmento de la URL
- `src/services/video_resolver.py:19-52` — Resolvers genéricos por dominio (DOODSTREAM_DOMAINS, VOE_DOMAINS, etc.)
- `src/services/flaresolverr.py` — `FlareSolverrClient` existe y funciona
- `src/db/models.py:30-44` — `Source` tiene campo `url` (String) donde se guarda la URL completa
- `src/services/catalog.py:215-216` — `resolve_playback(provider, media_id)` despacha al adapter por nombre
- `src/main.py:58-60` — Se instancian adapters y se registran en `CatalogService`
- `src/api/xtream.py:456` — `stream_movie` llama `catalog_service.resolve_playback(media.provider, media.provider_id)`
- `src/api/xtream.py:484-494` — Si protocol es "mp4", hace proxy_stream con Referer
- `src/api/xtream.py:496-498` — Si protocol es "hls", hace redirect 302
- `tests/test_xtream.py` — Tests existentes que usan provider fake "cuevana3"
