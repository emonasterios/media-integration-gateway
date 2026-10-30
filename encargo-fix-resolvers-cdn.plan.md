<!-- spec:bbacf68a326d6740f69524ba85545427 -->
# Encargo: Fix resolvers de video con FlareSolverr + Unpack y validación de CDN vivo

## ADVERTENCIA DE FALLO DE FONDO (LEER ANTES DE EMPEZAR)
Existen dos riesgos críticos que compilan pero revientan en ejecución:
1. **Llamadas de red no controladas**: Tanto `_check_cdn_alive` en `src/adapters/cuevana3.py` como `_verify_playback_url` en `src/api/xtream.py` usan HTTP. Si no capturan excepciones de conexión (`httpx.RequestError`, timeouts) o si faltan imports (`httpx`, `urlparse`, `re`), reventarán con `NameError` o `500 Unhandled Exception` en lugar de saltar al siguiente candidato o retornar 502 controlado.
2. **Rotura de suite de tests en `test_xtream.py`**: Si los tests unitarios existentes ejecutan `stream_movie` con URLs simuladas/falsas, `_verify_playback_url` intentará conectar a la red real y fallará con 502, rompiendo `pytest tests/test_xtream.py`. Debe mockearse la verificación en los tests de `stream_movie` si fuera necesario para que la suite pase limpia sin conexión externa.

---

## REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

---

## PASO 1: Implementar FlareSolverr + Unpack eval(p,a,c,k,e,d) y check CDN en `src/adapters/cuevana3.py`

**Archivo a modificar**: `src/adapters/cuevana3.py`

**Objetivo**:
1. Asegurar que los imports necesarios estén presentes al inicio del archivo:
   - `from urllib.parse import urlparse`
   - `import httpx`
   - `import re`
   - `from typing import Optional` (si no estuviera)
   - Reutilizar el unpacker existente: `from src.services.resolvers.unpacker import unpack` (o implementar regex de desempaquetado si no estuviera disponible).

2. Definir en la clase o a nivel de módulo la función auxiliar:
   ```python
   def _unpack_eval_and_extract_m3u8(html: str) -> Optional[str]:
   ```
   - Debe buscar bloques `eval(function(p,a,c,k,e,d)...` o llamar a `unpack(script)` para obtener el código JavaScript decodificado.
   - Sobre el código desempaquetado (o sobre el HTML si ya contiene el enlace), buscar URLs directas de m3u8 con regex: `https?://[^\s"'<>]+\.m3u8[^\s"'<>]*`.
   - Retornar la URL del `.m3u8` encontrada o `None` si falla.

3. Definir la función auxiliar asíncrona:
   ```python
   async def _check_cdn_alive(m3u8_url: str) -> bool:
   ```
   - Realizar una petición `HEAD` a `m3u8_url` con timeout de 10 segundos y `follow_redirects=True`.
   - Si el status code es 200 o 206, retornar `True`.
   - Envolver en `try...except Exception` capturando cualquier error de red o timeout y retornar `False`.

4. En el método `_build_playback_descriptor`:
   - Justo después del bloque de `mediaflow_bridge` y ANTES de los resolvers custom (`if VideoResolver.is_*`), incorporar:
   ```python
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
               m3u8_url = _unpack_eval_and_extract_m3u8(html)
               if m3u8_url:
                   if await _check_cdn_alive(m3u8_url):
                       return PlaybackDescriptor(protocol="hls", url=m3u8_url, headers={})
       except Exception as e:
           logger.debug("FlareSolverr+unpack falló para %s: %s", server_url, e)
   ```

5. Comprobar que compila con `python3 -m py_compile src/adapters/cuevana3.py`.

---

## PASO 2: Validar CDN vivo en endpoint `stream_movie` en `src/api/xtream.py`

**Archivo a modificar**: `src/api/xtream.py`

**Objetivo**:
1. Asegurar los imports necesarios al inicio de `src/api/xtream.py`:
   - `import httpx`
   - `from fastapi import HTTPException` (ya presente)

2. Crear la función auxiliar asíncrona:
   ```python
   async def _verify_playback_url(url: str, protocol: str) -> bool:
   ```
   - Realizar una petición `HEAD` a la URL con `timeout=8.0`, `follow_redirects=True`, `max_redirects=3`.
   - Si `protocol == "hls"`: retornar `True` si `response.status_code in (200, 206)`.
   - Si `protocol == "mp4"`: retornar `True` si `response.status_code in (200, 206)` y `"video/"` está presente en el header `content-type`.
   - Si no cumple o ante cualquier excepción (`try...except Exception`), retornar `False`.

3. En el endpoint `stream_movie`:
   - Después de obtener `result = await catalog_service.resolve_playback(...)` y antes de retornar la respuesta (ya sea `RedirectResponse` o `StreamingResponse`), insertar:
   ```python
   if not await _verify_playback_url(result.url, result.protocol):
       logger.warning("Playback URL no responde (CDN muerto): %s", result.url[:80])
       raise HTTPException(status_code=502, detail="Fuente de video no disponible (CDN caído)")
   ```

4. Comprobar que compila con `python3 -m py_compile src/api/xtream.py`.

---

## PASO 3: Asegurar compatibilidad de tests en `tests/test_xtream.py`

**Archivo a modificar**: `tests/test_xtream.py`

**Objetivo**:
1. Ejecutar `python3 -m pytest tests/test_xtream.py -q`.
2. Si los tests existentes de `stream_movie` fallan debido a que `_verify_playback_url` intenta conectar a URLs dummy no existentes y lanza 502, aplicar mock/patch sobre `src.api.xtream._verify_playback_url` en dichos tests para que retorne `True` (o añadir el caso de test específico para cuando devuelve 502).
3. Asegurar que toda la suite de `tests/test_xtream.py` termine en verde (código de salida 0).

---

ACEPTACION
python3 -m py_compile src/adapters/cuevana3.py src/api/xtream.py
python3 -m pytest tests/test_xtream.py -q
grep -q "_FLARE_UNPACK_DOMAINS" src/adapters/cuevana3.py
grep -q "def _unpack_eval_and_extract_m3u8" src/adapters/cuevana3.py
grep -q "async def _check_cdn_alive" src/adapters/cuevana3.py
grep -q "async def _verify_playback_url" src/api/xtream.py
grep -q "Fuente de video no disponible (CDN caído)" src/api/xtream.py

PREMISES

- `src/adapters/cuevana3.py:699` — `_build_playback_descriptor` existe y es donde se encadenan mediaflow_bridge → resolvers custom → None
- `src/adapters/cuevana3.py:813` — `resolve_playback` itera candidatos y llama `_build_playback_descriptor` por cada uno
- `src/api/xtream.py:513` — `stream_movie` llama `catalog_service.resolve_playback` y hace redirect/proxy según `result.protocol`
- `src/services/flaresolverr.py:10` — `FlareSolverrClient` ya implementado y accesible desde el contenedor (`http://flaresolverr:8191`)
- `src/core/config.py:22` — `FLARESOLVERR_URL = "http://flaresolverr:8191"`
- FlareSolverr responde OK y devuelve HTML con `eval(p,a,c,k,e,d)` empaquetado para streamwish/vimeos/bysejikuar (verificado manualmente)
- El unpack manual del eval produce m3u8 en `premilkyway.com` que responde 200 en HEAD/GET sin headers especiales
- `mediaflow-proxy` 2.4.9 instalado pero sus extractores StreamWish/Voe/FileLions fallan con el nuevo JS ofuscado
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
