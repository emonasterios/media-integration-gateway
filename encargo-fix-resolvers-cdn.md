# Encargo: Fix resolvers de video + validación CDN vivo

## Qué hay que hacer

### 1. Resolver streamwish/vimeos/bysejikuar con FlareSolverr + unpack `eval(p,a,c,k,e,d)`

**Archivo**: `src/adapters/cuevana3.py`

En `_build_playback_descriptor`, **antes** de los resolvers custom (doodstream/voe/streamtape/morencius), añadir intento con FlareSolverr para dominios que lo necesiten (streamwish.to, vimeos.net, bysejikuar.com y sus alias).

```python
# En _build_playback_descriptor, después del bloque mediaflow_bridge y ANTES de los if VideoResolver.is_*:
# Dominios que requieren FlareSolverr + unpack eval(p,a,c,k,e,d)
_FLARE_UNPACK_DOMAINS = {
    "streamwish.to", "streamwish.com", "ajmidyad.sbs",
    "vimeos.net",
    "bysejikuar.com",
    "vidhide.com", "vidhidepro.com",
    "filelions.to", "filelions.com",
    "voe.sx", "voe-unblock.com", "voeunblock.com", "voeunbl0ck.com", "voeunblocker.com",
}

candidate_domain = urlparse(server_url).hostname or ""
base_domain = ".".join(candidate_domain.split(".")[-2:]) if candidate_domain.count(".") >= 1 else candidate_domain

if candidate_domain in _FLARE_UNPACK_DOMAINS or base_domain in _FLARE_UNPACK_DOMAINS:
    try:
        from src.services.flaresolverr import FlareSolverrClient
        flaresolverr = FlareSolverrClient()
        solution = flaresolverr.get_solution(server_url, max_timeout=60000)
        if solution and solution.get("response"):
            html = solution["response"]
            # Unpack eval(p,a,c,k,e,d) → buscar m3u8
            m3u8_url = _unpack_eval_and_extract_m3u8(html)
            if m3u8_url:
                # Verificar que el CDN está vivo (HEAD al master.m3u8)
                if await _check_cdn_alive(m3u8_url):
                    return PlaybackDescriptor(protocol="hls", url=m3u8_url, headers={})
    except Exception as e:
        logger.debug("FlareSolverr+unpack falló para %s: %s", server_url, e)
```

Añadir helper `_unpack_eval_and_extract_m3u8(html: str) -> Optional[str]` en la misma clase (reutilizar lógica del test manual).

Añadir helper `async def _check_cdn_alive(m3u8_url: str) -> bool` que haga `HEAD` al master.m3u8 con timeout 10s y acepte 200/206.

### 2. Validar CDN vivo antes de aceptar candidato en `stream_movie`

**Archivo**: `src/api/xtream.py` → endpoint `stream_movie`

Después de obtener `result = await catalog_service.resolve_playback(...)`, **antes** de devolver RedirectResponse o StreamingResponse:

```python
# Verificar que la URL de reproducción responde (HEAD con timeout 8s)
if not await _verify_playback_url(result.url, result.protocol):
    logger.warning("Playback URL no responde (CDN muerto): %s", result.url[:80])
    raise HTTPException(status_code=502, detail="Fuente de video no disponible (CDN caído)")
```

Helper `_verify_playback_url(url: str, protocol: str) -> bool`:
- `protocol == "hls"`: HEAD al master.m3u8 → 200/206 OK
- `protocol == "mp4"`: HEAD al URL → 200/206 OK + `Content-Type` video/*
- timeout 8s, seguir redirects (máx 3)

---

## Qué NO tocar

- `get_vod_info` y catálogo (ya funcionan, O(1) por PK)
- Estructura de BD / modelos
- Endpoints Xtream distintos a `stream_movie`
- FlareSolverr client (ya existe y funciona)

---

## ACEPTACION

python3 -m py_compile src/adapters/cuevana3.py src/api/xtream.py
python3 -m pytest tests/test_xtream.py -q
grep -q "_FLARE_UNPACK_DOMAINS" src/adapters/cuevana3.py
grep -q "def _unpack_eval_and_extract_m3u8" src/adapters/cuevana3.py
grep -q "async def _check_cdn_alive" src/adapters/cuevana3.py
grep -q "async def _verify_playback_url" src/api/xtream.py
grep -q "Fuente de video no disponible (CDN caído)" src/api/xtream.py

## PREMISES

- `src/adapters/cuevana3.py:699` — `_build_playback_descriptor` existe y es donde se encadenan mediaflow_bridge → resolvers custom → None
- `src/adapters/cuevana3.py:813` — `resolve_playback` itera candidatos y llama `_build_playback_descriptor` por cada uno
- `src/api/xtream.py:513` — `stream_movie` llama `catalog_service.resolve_playback` y hace redirect/proxy según `result.protocol`
- `src/services/flaresolverr.py:10` — `FlareSolverrClient` ya implementado y accesible desde el contenedor (`http://flaresolverr:8191`)
- `src/core/config.py:22` — `FLARESOLVERR_URL = "http://flaresolverr:8191"`
- FlareSolverr responde OK y devuelve HTML con `eval(p,a,c,k,e,d)` empaquetado para streamwish/vimeos/bysejikuar (verificado manualmente)
- El unpack manual del eval produce m3u8 en `premilkyway.com` que responde 200 en HEAD/GET sin headers especiales
- `mediaflow-proxy` 2.4.9 instalado pero sus extractores StreamWish/Voe/FileLions fallan con el nuevo JS ofuscado
