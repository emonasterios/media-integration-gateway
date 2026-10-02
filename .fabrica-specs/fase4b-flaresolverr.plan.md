<!-- spec:41e76b7238b133e51f0f58e812047833 -->
REGLAS OBLIGATORIAS:
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- Cada paso debe dejar el proyecto COMPILANDO y en estado funcional.

ATENCIÓN - FALLO DE FONDO A PREVENIR:
En el entorno de ejecución y tests el contenedor de FlareSolverr no siempre estará levantado. Si el cliente o el adaptador lanzan excepciones no controladas al no poder contactar con FlareSolverr, reventará todo el flujo de reproducción. FlareSolverr DEBE tratarse como un acelerador/bypass opcional: ante cualquier fallo de conexión o timeout, el flujo DEBE capturar la excepción y hacer fallback automático y limpio a `httpx`.

## PASO 1: Configuración de FlareSolverr y servicio en Docker Compose
Archivos: `src/core/config.py` y `docker-compose.yml`

1. Leer `src/core/config.py` e incorporar en la clase de configuración (Settings) el campo para la URL del servicio FlareSolverr con su valor por defecto:
   `FLARESOLVERR_URL: str = "http://flaresolverr:8191"`
2. Leer `docker-compose.yml` y añadir el servicio `flaresolverr` manteniendo los servicios existentes:
   - Imagen: `ghcr.io/flaresolverr/flaresolverr:latest`
   - Nombre de contenedor: `flaresolverr`
   - Puertos: `"8191:8191"`
   - Variables de entorno: `LOG_LEVEL=info`
   - Política de reinicio: `restart: unless-stopped`
3. Verificar que `src/core/config.py` no tiene errores de sintaxis (`python3 -m py_compile src/core/config.py`).

## PASO 2: Cliente HTTP para la API de FlareSolverr
Archivo: `src/services/flaresolverr.py`

1. Crear `src/services/flaresolverr.py` implementando la clase `FlareSolverrClient`:
   - En el constructor `__init__(self, base_url: str | None = None)` tomar `base_url` o por defecto `settings.FLARESOLVERR_URL` importado de `src.core.config`.
   - Implementar método para peticiones GET: `get_solution(self, url: str, max_timeout: int = 60000) -> dict | None`.
   - Realizar petición HTTP POST a `{self.base_url}/v1` con cabecera `Content-Type: application/json` y payload:
     `{"cmd": "request.get", "url": url, "maxTimeout": max_timeout}`
   - Si la respuesta HTTP devuelve estado 200 y JSON con `{"status": "ok", "solution": ...}`, devolver el diccionario `solution` (que contiene `url`, `cookies`, `headers`, `response`).
   - Manejar cualquier error de conexión (`httpx.ConnectError`, `httpx.TimeoutException`, etc.) o status != "ok" capturando la excepción y retornando `None`, asegurando que no propague una caída fatal.
2. Verificar que el archivo compila sin errores (`python3 -m py_compile src/services/flaresolverr.py`).

## PASO 3: Integración de FlareSolverr y fallback en el adaptador de Cuevana3
Archivo: `src/adapters/cuevana3.py`

1. Leer `src/adapters/cuevana3.py`.
2. Importar `FlareSolverrClient` desde `src.services.flaresolverr`.
3. Instanciar o inyectar `FlareSolverrClient` en el adaptador `Cuevana3Adapter`.
4. Implementar un método auxiliar de detección de desafío Cloudflare:
   - Detectar si una respuesta tiene código 403, 503 o si el contenido HTML incluye marcadores de Cloudflare como `"Just a moment..."`, `"cf-browser-verification"`, o `"<title>Attention Required! | Cloudflare</title>"`.
5. Modificar el flujo de resolución (`resolve_playback` y navegación de URLs asociadas):
   - Cuando se detecte bloqueo de Cloudflare o al solicitar la URL de reproducción:
     a) Intentar resolver la página con `FlareSolverrClient.get_solution(url)`.
     b) Si FlareSolverr responde con solución válida, extraer el HTML y/o las cookies (especialmente `cf_clearance`) para continuar con la extracción de embeds.
     c) Si FlareSolverr devuelve `None` o falla la conexión, hacer fallback inmediato y transparente al cliente `httpx` estándar preexistente.
   - Respetar escrupulosamente la firma de retorno existente de `resolve_playback` sin alterar modelos de datos.
6. Verificar que el adaptador compila sin errores (`python3 -m py_compile src/adapters/cuevana3.py`).

## PASO 4: Pruebas unitarias de FlareSolverr y fallback
Archivo: `tests/test_flaresolverr.py`

1. Crear `tests/test_flaresolverr.py` con pruebas unitarias usando `pytest` y `unittest.mock`:
   - `test_flaresolverr_client_success`: mockear respuesta POST de FlareSolverr retornando status "ok" y verificar que `get_solution` retorna el diccionario de `solution`.
   - `test_flaresolverr_client_connection_error`: mockear fallo de conexión (`httpx.ConnectError`) y verificar que `get_solution` retorna `None` sin lanzar excepción.
   - `test_cuevana3_adapter_uses_flaresolverr_on_cloudflare`: mockear detección de Cloudflare en `Cuevana3Adapter` y verificar que invoca al cliente de FlareSolverr.
   - `test_cuevana3_adapter_fallback_when_flaresolverr_fails`: mockear que FlareSolverr retorna `None` o falla, y verificar que `Cuevana3Adapter` realiza fallback a `httpx` y no revienta.
2. Verificar que las pruebas compilan y se ejecutan exitosamente con `pytest tests/test_flaresolverr.py`.

## PASO 5: Script de integración de FlareSolverr
Archivo: `scripts/test_flaresolverr_integration.py`

1. Crear `scripts/test_flaresolverr_integration.py`:
   - Importar `settings` de `src.core.config`, `FlareSolverrClient` de `src.services.flaresolverr` y `Cuevana3Adapter` de `src.adapters.cuevana3`.
   - Comprobar que `settings.FLARESOLVERR_URL` está configurado.
   - Probar que `FlareSolverrClient` puede instanciarse correctamente.
   - Probar el comportamiento de fallback simulando que el endpoint de FlareSolverr no responde, asegurando que `get_solution` devuelve `None` sin excepciones no capturadas.
   - Probar que `Cuevana3Adapter` maneja el fallback sin interrupción fatal.
   - Si todo es correcto, imprimir `"FlareSolverr integration check passed"` y salir con `sys.exit(0)`.
2. Verificar la ejecución del script con `python3 scripts/test_flaresolverr_integration.py`.

ACEPTACION
grep -q "FLARESOLVERR_URL" src/core/config.py
grep -q "ghcr.io/flaresolverr/flaresolverr:latest" docker-compose.yml
test -f src/services/flaresolverr.py
grep -q "class FlareSolverrClient" src/services/flaresolverr.py
grep -q "FlareSolverrClient" src/adapters/cuevana3.py
test -f tests/test_flaresolverr.py
test -f scripts/test_flaresolverr_integration.py
python3 -c "import ast; ast.parse(open('src/services/flaresolverr.py').read())"
python3 -c "import ast; ast.parse(open('src/adapters/cuevana3.py').read())"
python3 -c "import ast; ast.parse(open('tests/test_flaresolverr.py').read())"
python3 -c "import ast; ast.parse(open('scripts/test_flaresolverr_integration.py').read())"
python3 scripts/test_flaresolverr_integration.py

PREMISES
- FlareSolverr API: POST /v1 con {cmd: "request.get", url: "...", maxTimeout: 60000}
- Respuesta: {status: "ok", solution: {url, cookies, headers, response}}
- Cookie cf_clearance se reusa en requests posteriores del mismo dominio
- El adapter ya tiene resolve_playback() que devuelve URL embed — ahí se inyecta el bypass
- Docker compose ya existe en la raíz del proyecto
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
