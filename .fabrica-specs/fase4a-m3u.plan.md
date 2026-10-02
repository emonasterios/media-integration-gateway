<!-- spec:6183086d9fb883a0a15e6ff86976a48b -->
# ENCARGO: Implementación de Endpoint M3U para IPTV (Fase 4a)

## FALLO DE FONDO IDENTIFICADO
El endpoint de resolución existente en `src/api/routes.py` es exclusivamente `POST /playback/resolve/{provider}/{media_id}`. Los clientes y reproductores IPTV que consumen playlists M3U solo realizan peticiones HTTP GET a las URLs indicadas en la lista (`/api/v1/resolve/{provider}/{media_id}`). Si no se expone este endpoint mediante GET, la aplicación compilará y generará el archivo M3U, pero **reventará en ejecución** arrojando errores 404 (Not Found) o 405 (Method Not Allowed) tan pronto como cualquier reproductor intente reproducir un elemento. Esto se corrige como PASO 1 antes de conectar la playlist.

## REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- Cada paso debe dejar el proyecto COMPILANDO y pasando los tests existentes.

---

## PASO 1: Habilitar endpoint GET de resolución en `src/api/routes.py`

- **Archivo a modificar**: `src/api/routes.py`
- **Acción**:
  1. Leer `src/api/routes.py` para identificar cómo está implementado el endpoint `POST /playback/resolve/{provider}/{media_id}` y cómo interactúa con `CatalogService` y las dependencias de base de datos/caché.
  2. Añadir un endpoint `GET /resolve/{provider}/{media_id}` (que al estar bajo el prefijo `/api/v1` responderá en `/api/v1/resolve/{provider}/{media_id}`) y permitir también GET en `/playback/resolve/{provider}/{media_id}` si procede.
  3. El endpoint debe resolver la reproducción invocando `catalog_service.resolve_playback(provider=provider, media_id=media_id)` (o el método equivalente existente). Si el resultado contiene una URL de stream (`stream_url`), redirigir con `RedirectResponse(url=result.stream_url, status_code=307)` o devolver la respuesta con la información de reproducción para clientes HTTP.
- **Resultado esperado**: `src/api/routes.py` admite peticiones GET en `/api/v1/resolve/{provider}/{media_id}` y los 57 tests preexistentes siguen pasando.

---

## PASO 2: Crear el generador de playlist M3U en `src/api/m3u.py`

- **Archivo a crear**: `src/api/m3u.py`
- **Acción**:
  1. Leer `src/services/cache.py` para verificar la signatura de `CatalogCache` y su método `get_cached_catalog()`.
  2. Leer `src/models/catalog.py` para verificar los atributos de `MediaItem` (`media_id`, `title`, `media_type`, `year`, `provider`).
  3. En `src/api/m3u.py`, crear un `APIRouter()` de FastAPI con el endpoint `GET /playlist.m3u`.
  4. El endpoint debe obtener los elementos cacheados a través de `CatalogCache` (inyectando la sesión de BD con `Depends(get_db)` de `src.db.database` si la clase lo requiere) SIN realizar scraping en la petición.
  5. Generar el texto de la playlist con formato estricto:
     - Primera línea: `#EXTM3U`
     - Por cada `MediaItem` cacheado:
       - Determinar el grupo: si `item.media_type` es `"movie"` o `"pelicula"`, usar `group-title="Peliculas"`; si es serie, `group-title="Series"`; por defecto `"Peliculas"`.
       - Formatear el nombre con año si está presente: `{item.title} ({item.year})` si tiene `year`, o `{item.title}` si no lo tiene.
       - Línea de metadatos: `#EXTINF:-1 group-title="{grupo}",{titulo_con_año}`
       - Línea de URL: `{base_url}/api/v1/resolve/{item.provider}/{item.media_id}`, donde `base_url` se toma de `str(request.base_url).rstrip("/")` (o `http://localhost:8000` por defecto).
  6. Devolver un objeto `Response` con `content=m3u_text` y `media_type="application/x-mpegurl"`.
- **Resultado esperado**: `src/api/m3u.py` exporta el router configurado y genera el formato M3U válido a partir de la caché sin errores de sintaxis.

---

## PASO 3: Registrar el router M3U en `src/main.py`

- **Archivo a modificar**: `src/main.py`
- **Acción**:
  1. Leer `src/main.py` para ver cómo se instancia `create_app()` y cómo se registran los routers existentes (como el de `src/api/routes.py`).
  2. Importar el router definido en `src/api/m3u.py`.
  3. Registrar el router en la aplicación mediante `app.include_router(m3u_router)` SIN prefijo `/api/v1` (o con ruta directa) para que el endpoint responda exactamente en `GET /playlist.m3u`.
- **Resultado esperado**: La aplicación expone la ruta `/playlist.m3u` en la raíz y mantiene todas las rutas anteriores intactas.

---

## PASO 4: Crear suite de tests en `tests/test_m3u.py`

- **Archivo a crear**: `tests/test_m3u.py`
- **Acción**:
  1. Leer `tests/test_smoke.py` o `tests/test_cache.py` para ver la configuración de fixtures (`client`, base de datos de test, app).
  2. Crear `tests/test_m3u.py` cubriendo:
     - `test_get_playlist_empty_cache`: llamada a `GET /playlist.m3u` cuando la caché está vacía devuelve HTTP 200, Content-Type `application/x-mpegurl` y contenido `#EXTM3U\n`.
     - `test_get_playlist_with_cached_items`: poblar la caché con un `MediaItem` (ej. `media_id="signal-one"`, `title="Signal One"`, `year=2026`, `media_type="movie"`, `provider="cuevana3"`). Verificar que `GET /playlist.m3u` contiene:
       - `#EXTM3U`
       - `#EXTINF:-1 group-title="Peliculas",Signal One (2026)`
       - `/api/v1/resolve/cuevana3/signal-one`
     - `test_get_resolve_endpoint`: llamada `GET /api/v1/resolve/cuevana3/signal-one` responde adecuadamente (redirección 307 o 200 según mock/implementación del resolver).
  3. Ejecutar `pytest tests/test_m3u.py` y verificar que pase en verde.
- **Resultado esperado**: `tests/test_m3u.py` pasa completamente y el total de tests pasa sin regresiones.

---

ACEPTACION
test -f src/api/m3u.py
grep -q "playlist.m3u" src/api/m3u.py
grep -q "#EXTM3U" src/api/m3u.py
grep -q "group-title=" src/api/m3u.py
grep -q "m3u" src/main.py
grep -q "/resolve/{provider}/{media_id}" src/api/routes.py
test -f tests/test_m3u.py
grep -q "playlist.m3u" tests/test_m3u.py
python3 -m pytest tests/test_m3u.py -v
python3 -m pytest tests/ -v

PREMISES
- src/main.py crea la app con create_app() e incluye router de src/api/routes.py (prefijo /api/v1)
- src/api/routes.py tiene endpoints: /search, /catalog/{provider}, /details/{provider}/{media_id}, /seasons, /episodes, /playback/resolve/{provider}/{media_id}, /providers
- src/services/cache.py tiene CatalogCache con métodos populate(), get_cached_catalog(), get_cached_item()
- src/models/catalog.py tiene MediaItem con campos: media_id, title, media_type, year, poster_url, overview, provider, provider_id
- src/services/catalog.py tiene CatalogService con search(), get_catalog(), get_details(), get_seasons(), get_episodes(), resolve_playback()
- 57 tests pasando actualmente en main
- El endpoint de resolución es POST /api/v1/playback/resolve/{provider}/{media_id} (no GET)
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
