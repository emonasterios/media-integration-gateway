---
name: add-vimeos-waaw-vidhide-bysejikuar-resolvers
description: >
  Agregar 4 resolvers de video para hosts de Cuevana sin cobertura:
  vimeos.net, waaw.to, vidhidepro.com, bysejikuar.com.
---

# Encargo: Agregar resolvers para vimeos.net, waaw.to, vidhidepro.com, bysejikuar.com

## Contexto
El adapter de Cuevana (`src/adapters/cuevana3.py`) llama a `resolve_with_mediaflow` como primer intento.
Los hosts sin extractor en mediaflow-proxy caen al fallback sin resolver.

Investigación de campo (VERIFICADA):
- **vimeos.net** — Página con script `eval(function(p,a,c,k,e,d))` que al desofuscar revela `sources: [{file: "...m3u8..."}]`. URL m3u8 confirmada: `https://p4.vimeos.zip/hls2/03/00010/kfoithrzjnbi_,n,h,.urlset/master.m3u8?t=...`
- **waaw.to** — Página `/f/{id}` contiene iframe a `/e/{id}`. Hay que analizar el iframe para extraer video.
- **vidhidepro.com** — JS packed pero con formato diferente al estándar. El extractor de mediaflow no lo reconoce.
- **bysejikuar.com** — Sin extractor. Dominio frecuente en el catálogo.

## Qué hacer

### 1. Crear `src/services/resolvers/__init__.py`
Módulo vacío para el paquete de resolvers.

### 2. Crear `src/services/resolvers/unpacker.py`
Función `unpack_js(packed: str) -> str` que:
- Extrae los argumentos p,a,c,k del patrón `eval(function(p,a,c,k,e,d){...})`
- Implementa el algoritmo de unpack de Dean Edwards (el estándar p,a,c,k)
- Retorna el JS desofuscado

### 3. Crear `src/services/resolvers/vimeos.py`
Clase `VimeosResolver`:
- Fetch embed page con curl_cffi (Chrome impersonation, Referer: https://vimeos.net/)
- Extraer script `eval(function(p,a,c,k,e,d))` con regex
- Llamar a `unpack_js()` del módulo unpacker
- Extraer URL m3u8 del resultado (buscar `sources:`, `file:`, `m3u8`)
- Retornar dict: `{"destination_url": url, "request_headers": {"Referer": "https://vimeos.net/"}}`

### 4. Crear `src/services/resolvers/waaw.py`
Clase `WaawResolver`:
- Fetch página `/f/{id}` con curl_cffi
- Extraer URL del iframe (buscar `<iframe src="...">`)
- Fetch iframe `/e/{id}`
- Buscar URL de video: patrones `file:`, `source:`, `videoUrl`, `m3u8`, `.mp4`
- Retornar dict: `{"destination_url": url, "request_headers": {"Referer": "https://waaw.to/"}}`

### 5. Crear `src/services/resolvers/vidhide.py`
Clase `VidhideResolver`:
- Fetch page con curl_cffi
- Intentar unpack JS eval con `unpack_js()`
- Si no hay eval packed, buscar alternativas: iframe embed, data attributes, API calls
- Retornar dict: `{"destination_url": url, "request_headers": {"Referer": "https://vidhidepro.com/"}}`

### 6. Crear `src/services/resolvers/bysejikuar.py`
Clase `BysejikuarResolver`:
- Fetch embed page `/e/{id}` con curl_cffi
- Analizar HTML para encontrar video (iframe, script, data attributes)
- Retornar dict: `{"destination_url": url, "request_headers": {"Referer": "https://bysejikuar.com/"}}`

### 7. Integrar en `src/services/mediaflow_bridge.py`
Agregar al `_EXTRACTOR_MAP` los 4 nuevos dominios:
```python
from resolvers.vimeos import VimeosResolver
from resolvers.waaw import WaawResolver
from resolvers.vidhide import VidhideResolver
from resolvers.bysejikuar import BysejikuarResolver

_EXTRACTOR_MAP = {
    # ... existentes ...
    "vimeos.net": VimeosResolver,
    "waaw.to": WaawResolver,
    "vidhidepro.com": VidhideResolver,
    "bysejikuar.com": BysejikuarResolver,
}
```

## Límites
- NO modificar la estructura de `mediaflow_bridge.py` más allá de agregar imports y entradas al mapa
- NO tocar `sync_catalog.py`, `populate_catalog.py`, ni modelos de BD
- Cada resolver debe ser un archivo independiente en `src/services/resolvers/`
- Usar `curl_cffi` para las peticiones HTTP
- El unpacker JS debe ser un módulo compartido

## ACEPTACION
cd /app && python3 -m pytest tests/ -x -q
cd /app && python3 -c "import asyncio,sys;sys.path.insert(0,'/app/src');from adapters.cuevana3 import Cuevana3Adapter;async def t():a=Cuevana3Adapter();r=await a.resolve_playback('wardriver');print(f'OK: {r.url[:80]}');await a.close();asyncio.run(t())"

## PREMISES
- `src/adapters/cuevana3.py` importa `resolve_with_mediaflow` (línea ~15)
- `src/services/mediaflow_bridge.py` tiene `_EXTRACTOR_MAP` con DoodStream, Voe, FileLions, StreamWish
- `curl_cffi` está instalado en el contenedor
- vimeos.net devuelve HTML con script `eval(function(p,a,c,k,e,d))` que contiene URLs m3u8 (VERIFICADO)
- waaw.to/f/{id} redirige a iframe /e/{id} con player de video
- vidhidepro.com usa JS packed pero con formato diferente
- bysejikuar.com aparece frecuentemente en el catálogo de Cuevana
- El contenedor corre en `/app` con Python 3.11
- El directorio `src/services/resolvers/` no existe aún
