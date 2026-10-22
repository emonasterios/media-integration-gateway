---
name: add-vimeos-waaw-vidhide-bysejikuar-resolvers
description: >
  Agregar 4 resolvers de video para hosts de Cuevana sin cobertura:
  vimeos.net, waaw.to, vidhidepro.com, bysejikuar.com.
  vimeos.net usa Dean Edwards Packer (eval p,a,c,k) con objeto links (hls2/hls3/hls4).
  streamwish.to, bysejikuar.com, filelions.to usan patrón IDÉNTICO a vimeos/Morencius.
  waaw.to usa iframe anidado con player — enfoque distinto.
  vidhidepro.com necesita URL viva (expiró).
---

# Encargo: Resolver genérico Packer + integra 4 dominios

## Contexto
El adapter Cuevana (`src/adapters/cuevana3.py`) llama a `resolve_with_mediaflow` primero.
Hosts sin extractor en mediaflow-proxy caen a fallback sin resolver.

**Hallazgos de campo (2026-10-21):**
- **vimeos.net** ✅ — Deofusca con `_unpack_packer` idéntico a `resolve_morencius()`. Encuentra m3u8 en `p4.vimeos.zip/hls2/...`. **Patrón confirmado**.
- **streamwish.to / bysejikuar.com / filelions.to** — Estructura IDÉNTICA a vimeos/Morencius (mismo Packer, mismo objeto `links`). **Una implementación genérica cubre los 4 dominios**.
- **waaw.to** ❌ — iframe anidado (`/f/{id}` → `/e/{id}` → player). Scripts sin Packer visible. Requiere navegación DOM (puppeteer/playwright) o inspección XHR. **Fuera de scope Packer**.
- **vidhidepro.com** ❌ — URL de prueba expirada (\"This file does not exist\"). Presumiblemente Packer. Necesita URL viva de Cuevana3.

## Qué hacer

### 1. Crear `src/services/resolvers/unpacker.py`
Módulo compartido con `unpack_js(p, a, c, k)` idéntico al de `resolve_morencius()` en `video_resolver.py`.

### 2. Crear `src/services/resolvers/packer_generic.py`
Resolver genérico para hosts Dean Edwards Packer:
- Fetch embed page con `curl_cffi` (Chrome impersonation)
- Extraer script `eval(function(p,a,c,k,e,d))` via regex
- Deobfuscar con `unpack_js()`
- Parsear objeto `links = {"hls2": "...", "hls3": "...", "hls4": "..."}`
- Preferir `hls4` (relativa, más estable) → `hls2` (CDN con token) → `hls3`
- Validar URL con `_validate_video_url()` (HEAD, Referer, verify=False)
- Retornar dict con `destination_url`, `request_headers` (Referer: dominio host)

### 3. Crear `src/services/resolvers/waaw.py` (stub documentado)
Resolver para waaw.to — **documentar que requiere puppeteer/playwright**, no Packer:
- Fetch `/f/{id}` → seguir iframe a `/e/{id}`
- Extraer video del player (XHR o DOM)
- **No implementar todavía** — dejar stub con TODO y hallazgos

### 4. Crear `src/services/resolvers/vidhide.py` (stub documentado)
Resolver para vidhidepro.com — **pendiente URL viva**:
- Fetch con `curl_cffi`
- Intentar unpack Packer (formato puede diferir)
- **No implementar todavía** — dejar stub con TODO

### 5. Integrar en `src/services/mediaflow_bridge.py`
Agregar al `_EXTRACTOR_MAP`:
```python
"vimeos.net": PackerGenericResolver,
"streamwish.to": PackerGenericResolver,
"bysejikuar.com": PackerGenericResolver,
"filelions.to": PackerGenericResolver,
# "waaw.to": WaawResolver,  # TODO: puppeteer
# "vidhidepro.com": VidhideResolver,  # TODO: URL viva
```

### 6. Tests de aceptación (en container vm-infra)
```bash
docker exec -w /app media-integration-gateway python3 -c "
import asyncio, sys
sys.path.insert(0, '/app')
from services.resolvers.packer_generic import PackerGenericResolver

async def test():
    resolver = PackerGenericResolver()
    # Test vimeos.net (URL real de Cuevana)
    url = 'https://vimeos.net/embed-1gstefb4b25m.html'
    result = await resolver.resolve(url)
    print(f'vimeos.net: {result}')
    assert result and 'm3u8' in result['destination_url']
    print('✅ PackerGenericResolver OK')

asyncio.run(test())
"
```

## NO TOCAR
- `src/adapters/cuevana3.py` (solo usa mediaflow_bridge)
- `src/services/video_resolver.py` (fallback propio, no mediaflow)
- `src/services/mediaflow_bridge.py` más allá de imports y `_EXTRACTOR_MAP`
- `sync_catalog.py`, `populate_catalog.py`, modelos BD

## ACEPTACION
```bash
cd /app && python3 -m pytest tests/ -q
docker exec -w /app media-integration-gateway python3 -c "
import asyncio, sys
sys.path.insert(0, '/app')
from services.resolvers.packer_generic import PackerGenericResolver
async def test():
    r = PackerGenericResolver()
    res = await r.resolve('https://vimeos.net/embed-1gstefb4b25m.html')
    assert res and 'm3u8' in res['destination_url']
    print('vimeos.net:', res['destination_url'][:80])
asyncio.run(test())
"
```

## PREMISES
- `src/services/video_resolver.py` tiene `resolve_morencius()` con `_unpack_packer()` (líneas ~180-250)
- `src/services/mediaflow_bridge.py` tiene `_EXTRACTOR_MAP` con DoodStream, Voe, FileLions, StreamWish (línea ~40)
- `curl_cffi` instalado en contenedor (`/usr/local/lib/python3.11/site-packages/curl_cffi/`)
- vimeos.net devuelve HTML con `eval(function(p,a,c,k,e,d))` conteniendo `links.hls2/hls3/hls4` (VERIFICADO)
- streamwish.to, bysejikuar.com, filelions.to: misma estructura que vimeos/Morencius
- Contenedor corre en `/app` con Python 3.11
- Directorio `src/services/resolvers/` no existe — crearlo
- FlareSolverr en vm-infra puerto 8191 (usado por video_resolver.py fallback)