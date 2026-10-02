<!-- spec:e09c274135c2eab3b061469d482dc4a8 -->
REGLAS OBLIGATORIAS:
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

ADVERTENCIA DE FONDO (CRÍTICA):
En FastAPI, devolver un `str` directo desde una función de ruta hace que se serialice automáticamente como JSON con comillas dobles y saltos de línea escapados (`"\"#EXTM3U\\n...\""`). Esto corrompe por completo la playlist M3U e impide que cualquier reproductor IPTV la procese. El endpoint `GET /playlist.m3u` DEBE retornar una instancia de `Response(content=..., media_type="application/x-mpegurl")` (o `PlainTextResponse`). Además, debe consultar los elementos cacheados sin invocar a los adaptadores ni hacer scraping.

## PASO 1: Crear el endpoint de playlist M3U en `src/api/m3u.py`

Archivo a crear:
- `src/api/m3u.py`

Archivos de solo lectura para inspección previa:
- `src/models/catalog.py` (para ver los campos exactos del modelo `MediaItem`: `title`, `url`, `type`, etc.)
- `src/services/cache.py` (para ver cómo obtener los elementos del catálogo cacheado y si requiere inyección de dependencias como sesión de base de datos)
- `src/api/routes.py` (para ver la estructura exacta de la ruta de resolución `/api/v1/resolve/...`)

Qué debe quedar:
1. Crear `src/api/m3u.py` definiendo un router de FastAPI:
   ```python
   from fastapi import APIRouter, Depends, Request, Response
   ```
2. Crear la función del endpoint con la ruta `GET /playlist.m3u`.
3. Obtener los items cacheados a través del servicio existente en `src/services/cache.py` (usando dependencias si aplica, sin re-scrapear).
4. Generar el contenido en texto plano respetando el formato M3U:
   - Primera línea: `#EXTM3U`
   - Por cada item cacheado:
     - Línea de metadatos: `#EXTINF:-1 group-title="<Grupo>",<Titulo>` (donde `<Grupo>` corresponde al tipo del item, e.g. "Peliculas" si es película, y `<Titulo>` al título del item).
     - Línea de enlace: URL completa al endpoint de resolución (por ejemplo `http://localhost:8000/api/v1/resolve/<adapter>/<slug>` o construida a partir de `request.base_url`).
5. Retornar `Response(content=contenido_m3u, media_type="application/x-mpegurl")`.
6. Si la caché está vacía, debe devolver `#EXTM3U\n` con status 200 sin lanzar excepciones.

## PASO 2: Conectar el router M3U en `src/main.py`

Archivo a modificar:
- `src/main.py`

Qué debe quedar:
1. Leer `src/main.py`.
2. Importar el router creado en `src/api/m3u.py`:
   ```python
   from src.api.m3u import router as m3u_router
   ```
3. Registrar el router en la aplicación FastAPI (`app`):
   ```python
   app.include_router(m3u_router)
   ```
   Asegurarse de que quede expuesto en la raíz para que responda a `GET /playlist.m3u`.
4. NO alterar los routers ni middlewares existentes de `api/v1`.
5. Dejar el proyecto compilando sin errores de sintaxis o importación.

## PASO 3: Crear los tests del endpoint M3U en `tests/test_m3u.py`

Archivo a crear:
- `tests/test_m3u.py`

Archivos de solo lectura para inspección previa:
- `tests/test_smoke.py` o `tests/test_cache.py` (para ver cómo instanciar `TestClient` y cómo poblar o mockear la caché en tests)

Qué debe quedar:
1. Crear `tests/test_m3u.py` utilizando `pytest` y `starlette.testclient.TestClient` / `httpx`.
2. Test 1: `GET /playlist.m3u` con catálogo vacío devuelve HTTP 200, header `Content-Type` compatible con `mpegurl` (o texto) y el cuerpo contiene `#EXTM3U`.
3. Test 2: `GET /playlist.m3u` con items en la caché:
   - Devuelve HTTP 200.
   - El cuerpo contiene la cabecera `#EXTM3U`.
   - Contiene `#EXTINF:-1 group-title="Peliculas",Signal One (2026)` (o el formato correspondiente al item de prueba).
   - Contiene la URL de resolución esperada (`http://localhost:8000/api/v1/resolve/...`).
   - Verifica que el contenido NO esté serializado como JSON (no debe comenzar ni terminar con comillas dobles JSON).
4. Ejecutar la suite con `pytest tests/test_m3u.py` y verificar que pase en limpio sin romper los tests previos.

ACEPTACION
test -f src/api/m3u.py
grep -q "playlist.m3u" src/api/m3u.py
grep -q "EXTM3U" src/api/m3u.py
grep -q "Response(" src/api/m3u.py
grep -q "m3u" src/main.py
test -f tests/test_m3u.py
grep -q "playlist.m3u" tests/test_m3u.py
pytest tests/test_m3u.py

PREMISES
- src/main.py ya registra routers de api/v1
- src/services/cache.py tiene catálogo cacheado
- src/models/catalog.py tiene MediaItem con title, url, poster, type
- 57 tests pasando actualmente
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
