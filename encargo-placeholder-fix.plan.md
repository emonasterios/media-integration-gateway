<!-- spec:2ab29c9e8dce370f5c9d762f383a923b -->
# REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- Cada paso debe dejar el proyecto COMPILANDO.

---

## PASO 1: Rechazar URLs de placeholders en el validador de video

### Archivo a modificar
- `src/services/video_resolver.py`

### Instrucciones
1. Leer `src/services/video_resolver.py` antes de editar.
2. Asegurar que `urlparse` esté importado desde `urllib.parse`:
   ```python
   from urllib.parse import urlparse
   ```
3. Definir la tupla de dominios a rechazar a nivel de módulo o clase:
   ```python
   PLACEHOLDER_DOMAINS = (
       "test-videos.co.uk",
       "sample-videos.com",
       "file-examples.com",
   )
   ```
4. En el método `_validate_video_url`, tras seguir las redirecciones y obtener la variable `final_url`, extraer el hostname y rechazar si pertenece a un placeholder conocido:
   ```python
   final_host = urlparse(str(final_url)).hostname or ""
   if any(domain in final_host for domain in PLACEHOLDER_DOMAINS):
       logger.warning("URL rechazada: placeholder detectado (%s)", str(final_url)[:80])
       return False
   ```
5. Verificar compilación ejecutando: `python3 -m py_compile src/services/video_resolver.py`

---

## PASO 2: Eliminar fallback a embed y devolver HTTP 500 cuando falle la resolución

### Archivo a modificar
- `src/api/xtream.py`

### Instrucciones
1. Leer `src/api/xtream.py` antes de editar.
2. En las importaciones desde `fastapi`, importar `HTTPException`:
   ```python
   from fastapi import HTTPException
   ```
   (o añadir `HTTPException` a la línea existente `from fastapi import ...`).
3. En el endpoint `stream_movie`, localizar el bloque donde se maneja `result.protocol == "embed"`.
4. Si la resolución de VOE o Doodstream falla o no entrega video directo (`hls` o `mp4`), ELIMINAR cualquier redirección residual al embed original. En su lugar, registrar el error y lanzar `HTTPException` con código 500:
   ```python
   logger.error("No se pudo resolver video real para embed: %s", result.url)
   raise HTTPException(status_code=500, detail="No se pudo resolver fuente de video")
   ```
5. Al final del flujo de `stream_movie`, si el protocolo no es directo (`hls` o `mp4`), lanzar `HTTPException`:
   ```python
   raise HTTPException(status_code=500, detail="Fuente de video no disponible")
   ```
6. Verificar compilación ejecutando: `python3 -m py_compile src/api/xtream.py`

---

## PASO 3: Tests unitarios para el rechazo de placeholders y el error 500

### Archivos a modificar
- `tests/test_video_resolver.py`
- `tests/test_xtream.py`

### Instrucciones
1. Leer ambos archivos antes de editarlos.
2. En `tests/test_video_resolver.py`, añadir o actualizar un test para verificar que `_validate_video_url` devuelve `False` cuando la URL resultante tiene un host presente en `PLACEHOLDER_DOMAINS` (por ejemplo, `https://test-videos.co.uk/sample.mp4`).
3. En `tests/test_xtream.py`, añadir o actualizar un test para verificar que cuando `stream_movie` encuentra un embed que no se puede resolver a video directo, responde con status HTTP 500 (o lanza `HTTPException` con 500) en lugar de redirigir con 302 al embed.
4. Ejecutar la suite de tests para asegurar que pasan:
   ```bash
   pytest tests/test_video_resolver.py tests/test_xtream.py
   ```

---

ACEPTACION
grep -q "PLACEHOLDER_DOMAINS" src/services/video_resolver.py
grep -q "test-videos.co.uk" src/services/video_resolver.py
grep -q "placeholder detectado" src/services/video_resolver.py
grep -q "HTTPException" src/api/xtream.py
grep -q "No se pudo resolver video real para embed" src/api/xtream.py
grep -q "No se pudo resolver fuente de video" src/api/xtream.py
grep -q "Fuente de video no disponible" src/api/xtream.py
python3 -m py_compile src/services/video_resolver.py
python3 -m py_compile src/api/xtream.py
pytest tests/test_video_resolver.py tests/test_xtream.py

PREMISES
- src/api/xtream.py:280-304 — código actual de embed fallback que redirige sin validar
- src/api/xtream.py:237 — imports actuales (falta HTTPException)
- src/services/video_resolver.py:55-120 — _validate_video_url() que sigue redirects pero no rechaza placeholders
- Movie 1012 actualmente devuelve 302 a test-videos.co.uk (Big Buck Bunny placeholder)
- Movie 1044 funciona correctamente (cloudatacdn.com → video/mp4)
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
