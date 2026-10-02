<!-- spec:35fa7b83e0ef0272d2a84802cccea3f6 -->
REGLAS GENERALES OBLIGATORIAS:
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- Cada paso debe dejar el proyecto COMPILANDO y pasando tests.

## PASO 1: Crear el servicio de resolución de video directo en `src/services/video_resolver.py`

Archivo a crear:
- `src/services/video_resolver.py`

Crear el nuevo módulo `src/services/video_resolver.py` con el servicio `VideoResolver` que implemente la lógica de extracción para servidores Doodstream/Playmogo según el spike:
- Definir la tupla de dominios soportados:
  `DOODSTREAM_DOMAINS = ("doodstream.com", "dood.la", "dood.ws", "playmogo.com", "d000d.com", "dood.yt", "dooood.com")`
- Clase `VideoResolver`:
  - En `__init__(self) -> None`: crear `self._client = httpx.AsyncClient(follow_redirects=True, timeout=20.0, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"})`.
  - Método estático `is_doodstream(url: str) -> bool`: verifica si `url.lower()` contiene alguno de los dominios en `DOODSTREAM_DOMAINS`.
  - Método `async def resolve_doodstream(self, embed_url: str) -> Optional[PlaybackDescriptor]`:
    1. Obtener la página mediante `await self._client.get(embed_url)`. Si hay excepción, registrar warning y retornar `None`.
    2. Guardar `page_url = str(resp.url)` y `html = resp.text`.
    3. Extraer `token` usando regex `r"token=([a-zA-Z0-9]+)"`. Si no coincide, registrar debug y retornar `None`.
    4. Extraer `pass_path` usando regex `r"pass_md5/([^'\"]+)"`. Si no coincide, registrar debug y retornar `None`.
    5. Obtener URL base del CDN: `base_url = page_url.rsplit("/", 1)[0]`, `pass_url = f"{base_url}/pass_md5/{pass_path}"`.
    6. Hacer GET a `pass_url` con headers `{"Referer": page_url}`. Si falla o la respuesta `cdn_base` no empieza con `"http"`, retornar `None`.
    7. Generar sufijo aleatorio de 10 caracteres alfanuméricos (`string.ascii_letters + string.digits`), calcular `expiry = int(time.time() * 1000)`.
    8. Construir `video_url = f"{cdn_base}{random_suffix}?token={token}&expiry={expiry}"`.
    9. Retornar `PlaybackDescriptor(protocol="mp4", url=video_url, headers={"Referer": base_url})`.
  - Método `async def close(self) -> None`: ejecutar `await self._client.aclose()`.

Verificar que compila con:
```bash
python3 -m py_compile src/services/video_resolver.py
```

## PASO 2: Crear tests unitarios para `VideoResolver` en `tests/test_video_resolver.py`

Archivo a crear:
- `tests/test_video_resolver.py`

Crear `tests/test_video_resolver.py` cubriendo todos los casos de `VideoResolver` con mocks de `httpx`:
- `test_resolve_doodstream_success`: simular respuesta HTML con token y `pass_md5`, y respuesta del endpoint `pass_md5` con URL base CDN. Verificar que devuelve `PlaybackDescriptor` con `protocol="mp4"`, URL que contiene token, expiry y sufijo aleatorio de 10 caracteres, y header Referer correcto.
- `test_resolve_doodstream_no_token`: HTML sin token retorna `None`.
- `test_resolve_doodstream_no_pass_md5`: HTML sin `pass_md5` retorna `None`.
- `test_resolve_doodstream_http_error`: excepción HTTP en la petición inicial retorna `None`.
- `test_resolve_doodstream_pass_md5_error`: excepción HTTP en la petición `pass_md5` retorna `None`.
- `test_resolve_doodstream_invalid_pass_md5_response`: respuesta de `pass_md5` no válida (no empieza por http) retorna `None`.
- `test_is_doodstream_true`: verificar dominios válidos (`doodstream.com`, `playmogo.com`, `dood.la`, `d000d.com`).
- `test_is_doodstream_false`: verificar dominios que no corresponden (`voe.sx`, `vidhide.com`, `example.com`).

Ejecutar los tests creados para confirmar que pasan:
```bash
pytest tests/test_video_resolver.py
```

## PASO 3: Integrar `VideoResolver` en `Cuevana3Adapter` en `src/adapters/cuevana3.py`

Archivo a modificar:
- `src/adapters/cuevana3.py`

Leer `src/adapters/cuevana3.py` antes de editar.
Realizar las siguientes modificaciones puntuales:
1. Importar `VideoResolver`:
   ```python
   from src.services.video_resolver import VideoResolver
   ```
2. En `Cuevana3Adapter.__init__`, tras inicializar FlareSolverr:
   ```python
   self._video_resolver = VideoResolver()
   ```
3. Agregar un método auxiliar privado para construir el `PlaybackDescriptor` intentando primero resolución directa:
   ```python
   async def _build_playback_descriptor(self, server_url: str) -> PlaybackDescriptor:
       if VideoResolver.is_doodstream(server_url):
           try:
               direct = await self._video_resolver.resolve_doodstream(server_url)
               if direct:
                   return direct
           except Exception as e:
               logger.warning("Fallo resolviendo video directo de %s: %s", server_url, e)
       return PlaybackDescriptor(
           protocol="embed",
           url=server_url,
           headers={"Referer": self._base},
       )
   ```
4. En `resolve_playback()`, en cada uno de los 4 puntos de retorno que devuelven `PlaybackDescriptor(protocol="embed", url=server_url, ...)`:
   - Tras `li[data-server]`
   - Tras `_extract_server_from_list`
   - Tras `_extract_server_from_scripts`
   - En el fallback `for link in soup.find_all("a", href=True)`
   Reemplazar el retorno directo por `return await self._build_playback_descriptor(server_url)`.
5. En `Cuevana3Adapter.close()`:
   Agregar `await self._video_resolver.close()` antes de cerrar el cliente HTTP.

Comprobar que compila y que los tests existentes de Cuevana3 siguen funcionando:
```bash
python3 -m py_compile src/adapters/cuevana3.py
pytest tests/test_cuevana3.py
```

## PASO 4: Añadir tests de resolución directa en `tests/test_cuevana3.py`

Archivo a modificar:
- `tests/test_cuevana3.py`

Leer `tests/test_cuevana3.py` antes de editar.
Añadir al final del archivo los tests de integración de `Cuevana3Adapter` con `VideoResolver`:
1. `test_resolve_playback_direct_video_doodstream(adapter)`:
   - Mockear `adapter._video_resolver.resolve_doodstream` para devolver un `PlaybackDescriptor(protocol="mp4", url="https://cdn.example.com/video.mp4?token=abc&expiry=123", headers={"Referer": "https://playmogo.com"})`.
   - Simular HTML de Cuevana3 que contiene un enlace o `data-server` / `data-mdl` hacia `https://doodstream.com/e/jtri5tfbukk6`.
   - Invocar `await adapter.resolve_playback(...)` y verificar que el resultado tiene `protocol == "mp4"`.
2. `test_resolve_playback_doodstream_fallback_on_failure(adapter)`:
   - Mockear `adapter._video_resolver.resolve_doodstream` para devolver `None`.
   - Invocar `await adapter.resolve_playback(...)` con servidor Doodstream.
   - Verificar que hace fallback y retorna `protocol == "embed"`.
3. `test_adapter_close_closes_video_resolver(adapter)`:
   - Mockear `adapter._video_resolver.close = AsyncMock()`.
   - Llamar `await adapter.close()`.
   - Verificar que `adapter._video_resolver.close.assert_awaited_once()` se cumple.

Ejecutar todos los tests para asegurar que no hay regresiones:
```bash
pytest tests/
```

ACEPTACION
test -f src/services/video_resolver.py
grep -q "class VideoResolver" src/services/video_resolver.py
grep -q "DOODSTREAM_DOMAINS" src/services/video_resolver.py
grep -q "def is_doodstream" src/services/video_resolver.py
grep -q "async def resolve_doodstream" src/services/video_resolver.py
grep -q "from src.services.video_resolver import VideoResolver" src/adapters/cuevana3.py
grep -q "self._video_resolver = VideoResolver()" src/adapters/cuevana3.py
grep -q "resolve_doodstream" src/adapters/cuevana3.py
grep -q "self._video_resolver.close()" src/adapters/cuevana3.py
test -f tests/test_video_resolver.py
pytest tests/test_video_resolver.py
pytest tests/test_cuevana3.py
pytest tests/

PREMISES

- `src/adapters/cuevana3.py` tiene `resolve_playback()` que retorna `PlaybackDescriptor(protocol="embed", url=...)` en 4 puntos
- `src/adapters/cuevana3.py` tiene `close()` que llama `await self._client.aclose()`
- `src/models/catalog.py` define `PlaybackDescriptor` con campos: protocol, url, headers, expires_at, subtitles
- `src/services/flaresolverr.py` existe como referencia de estructura de servicio
- `tests/test_cuevana3.py` usa `MockResponse`, `adapter` fixture con `AsyncMock` para `_client`
- `tests/test_cuevana3.py` tiene `PLAYBACK_HTML` con `data-mdl="https://doodstream.com/e/abc123"`
- `.fabrica-verify` ejecuta `pytest tests/ -v`
- El venv está en `.venv/` y se activa con `. .venv/bin/activate`
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
