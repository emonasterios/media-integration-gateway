<!-- spec:3a5356e7ea6f3a48401c5a02163512d6 -->
# ENCARGO: Implementación de Video Resolvers para vimeos.net, waaw.to, vidhidepro.com y bysejikuar.com

## REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- Cada paso debe dejar el proyecto COMPILANDO (`python3 -m py_compile ...`).

---

## PASO 1: Advertencia de importación y creación del módulo unpacker
**Fallo de fondo crítico:** En `src/services/mediaflow_bridge.py`, importar `from resolvers.vimeos ...` provocará `ModuleNotFoundError: No module named 'resolvers'` en tiempo de ejecución porque la raíz en `sys.path` es `/app/src`, no `src/services`. Los nuevos resolvers deben importarse de forma relativa dentro de `src/services/` como `from .resolvers.<modulo> import <Clase>` (o `from services.resolvers.<modulo> import <Clase>`). Además, la firma de cada extractor debe ser compatible con la interfaz que espera `mediaflow_bridge`: una clase instanciable con la URL (`__init__(self, url: str = "")`) y con un método asíncrono `async def extract(self, url: str | None = None) -> dict` que devuelva `{"destination_url": str, "request_headers": dict}`.

**Archivos a crear/tocar:**
- `src/services/resolvers/__init__.py`
- `src/services/resolvers/unpacker.py`

**Qué debe quedar:**
1. Crear el directorio `src/services/resolvers/` si no existe.
2. Crear `src/services/resolvers/__init__.py` como paquete Python (puede estar vacío o exponer utilidades).
3. En `src/services/resolvers/unpacker.py`, implementar la función `unpack_js(packed: str) -> str`:
   - Detectar mediante expresiones regulares el patrón estándar de empaquetado de Dean Edwards: `eval(function(p,a,c,k,e,d){...}(...))` o variantes con parámetros `(p, a, c, k, e, r)`.
   - Extraer la cadena empaquetada `p`, la base numérica `a` (entero), el conteo `c` (entero) y la tabla de palabras `k` (separada por `|`).
   - Implementar la función de decodificación en base `a` (convirtiendo identificadores en números y resolviendo contra la lista `k`).
   - Reemplazar cada token en `p` por su palabra desofuscada y retornar la cadena JS desofuscada resultante. Si no hay patrón packed, retornar la cadena original sin fallar.

---

## PASO 2: Resolver para vimeos.net
**Archivos a crear/tocar:**
- `src/services/resolvers/vimeos.py`

**Qué debe quedar:**
Crear la clase `VimeosResolver` con:
- `__init__(self, url: str = "")`: guarda `self.url = url`.
- Método asíncrono `async def extract(self, url: str | None = None) -> dict`:
  - Usar la URL provista o `self.url`.
  - Realizar petición HTTP GET a la página embed usando `curl_cffi.requests.AsyncSession(impersonate="chrome")` enviando cabecera `Referer: https://vimeos.net/`.
  - Buscar en la respuesta HTML el bloque script ofuscado con patrón `eval(function(p,a,c,k,e,...)`.
  - Invocar `unpack_js` importado desde `services.resolvers.unpacker` (o `.unpacker`).
  - Buscar la URL `.m3u8` dentro del script desofuscado (patrones tipo `sources:\s*\[{\s*file:\s*["']([^"']+)["']` o regex de URL m3u8).
  - Retornar un diccionario con la estructura:
    `{"destination_url": <url_m3u8>, "request_headers": {"Referer": "https://vimeos.net/"}}`
  - Si no se encuentra video, lanzar excepción informativa (por ejemplo, `ValueError`).

---

## PASO 3: Resolver para waaw.to
**Archivos a crear/tocar:**
- `src/services/resolvers/waaw.py`

**Qué debe quedar:**
Crear la clase `WaawResolver` con:
- `__init__(self, url: str = "")`: guarda `self.url = url`.
- Método asíncrono `async def extract(self, url: str | None = None) -> dict`:
  - Usar la URL provista o `self.url`.
  - Realizar petición HTTP GET usando `curl_cffi.requests.AsyncSession(impersonate="chrome")` con cabecera `Referer: https://waaw.to/`.
  - Si la URL apunta a `/f/{id}`, extraer la URL del iframe contenido (patrón `<iframe[^>]+src=["']([^"']+)["']`), resolviendo la URL absoluta (habitualmente `/e/{id}`).
  - Peticionar la URL del iframe con el `Referer` correspondiente.
  - Buscar en el HTML / scripts la URL del flujo de video (patrones `file:\s*["']([^"']+)["']`, `source:\s*["']([^"']+)["']`, enlaces directos a `.m3u8` o `.mp4`).
  - Retornar un diccionario con la estructura:
    `{"destination_url": <url_video>, "request_headers": {"Referer": "https://waaw.to/"}}`
  - Si no se encuentra video, lanzar excepción informativa.

---

## PASO 4: Resolver para vidhidepro.com
**Archivos a crear/tocar:**
- `src/services/resolvers/vidhide.py`

**Qué debe quedar:**
Crear la clase `VidhideResolver` con:
- `__init__(self, url: str = "")`: guarda `self.url = url`.
- Método asíncrono `async def extract(self, url: str | None = None) -> dict`:
  - Usar la URL provista o `self.url`.
  - Realizar petición HTTP GET usando `curl_cffi.requests.AsyncSession(impersonate="chrome")` con `Referer: https://vidhidepro.com/`.
  - Inspeccionar el HTML en busca de scripts packed evaluables con `unpack_js` de `.unpacker`.
  - Si no está empaquetado o tras desofuscar, extraer URL de stream `.m3u8` o `.mp4` (revisar variables JS como `sources`, `file:`, atributos data o llamadas a player).
  - Retornar un diccionario con la estructura:
    `{"destination_url": <url_video>, "request_headers": {"Referer": "https://vidhidepro.com/"}}`
  - Si no se encuentra video, lanzar excepción informativa.

---

## PASO 5: Resolver para bysejikuar.com
**Archivos a crear/tocar:**
- `src/services/resolvers/bysejikuar.py`

**Qué debe quedar:**
Crear la clase `BysejikuarResolver` con:
- `__init__(self, url: str = "")`: guarda `self.url = url`.
- Método asíncrono `async def extract(self, url: str | None = None) -> dict`:
  - Usar la URL provista o `self.url`.
  - Realizar petición HTTP GET a la página embed (`/e/{id}` o URL base recibida) con `curl_cffi.requests.AsyncSession(impersonate="chrome")` y `Referer: https://bysejikuar.com/`.
  - Analizar HTML y scripts buscando la fuente de video (enlaces `.m3u8`, etiquetas `<video>`, configuración del player o iframes anidados).
  - Retornar un diccionario con la estructura:
    `{"destination_url": <url_video>, "request_headers": {"Referer": "https://bysejikuar.com/"}}`
  - Si no se encuentra video, lanzar excepción informativa.

---

## PASO 6: Integración en mediaflow_bridge.py
**Archivos a crear/tocar:**
- `src/services/mediaflow_bridge.py`

**Qué debe quedar:**
1. Leer `src/services/mediaflow_bridge.py` para observar las importaciones existentes y la definición de `_EXTRACTOR_MAP`.
2. Agregar las importaciones de los nuevos resolvers usando rutas relativas seguras:
   ```python
   from .resolvers.vimeos import VimeosResolver
   from .resolvers.waaw import WaawResolver
   from .resolvers.vidhide import VidhideResolver
   from .resolvers.bysejikuar import BysejikuarResolver
   ```
3. Incorporar al diccionario `_EXTRACTOR_MAP` los cuatro nuevos dominios sin alterar las entradas previas:
   - `"vimeos.net": VimeosResolver,`
   - `"waaw.to": WaawResolver,`
   - `"vidhidepro.com": VidhideResolver,`
   - `"bysejikuar.com": BysejikuarResolver,`
4. Mantener intacto el resto de la lógica de puente y resolución en `mediaflow_bridge.py`.

---

ACEPTACION
test -f src/services/resolvers/__init__.py
test -f src/services/resolvers/unpacker.py
test -f src/services/resolvers/vimeos.py
test -f src/services/resolvers/waaw.py
test -f src/services/resolvers/vidhide.py
test -f src/services/resolvers/bysejikuar.py
grep -q "def unpack_js" src/services/resolvers/unpacker.py
grep -q "class VimeosResolver" src/services/resolvers/vimeos.py
grep -q "class WaawResolver" src/services/resolvers/waaw.py
grep -q "class VidhideResolver" src/services/resolvers/vidhide.py
grep -q "class BysejikuarResolver" src/services/resolvers/bysejikuar.py
grep -q "vimeos.net" src/services/mediaflow_bridge.py
grep -q "waaw.to" src/services/mediaflow_bridge.py
grep -q "vidhidepro.com" src/services/mediaflow_bridge.py
grep -q "bysejikuar.com" src/services/mediaflow_bridge.py
python3 -m py_compile src/services/resolvers/unpacker.py src/services/resolvers/vimeos.py src/services/resolvers/waaw.py src/services/resolvers/vidhide.py src/services/resolvers/bysejikuar.py src/services/mediaflow_bridge.py
python3 -c "import sys; sys.path.insert(0, 'src'); from services.mediaflow_bridge import _EXTRACTOR_MAP; assert 'vimeos.net' in _EXTRACTOR_MAP and 'waaw.to' in _EXTRACTOR_MAP and 'vidhidepro.com' in _EXTRACTOR_MAP and 'bysejikuar.com' in _EXTRACTOR_MAP"

PREMISES
- `src/adapters/cuevana3.py` importa `resolve_with_mediaflow` (línea ~15)
- `src/services/mediaflow_bridge.py` tiene `_EXTRACTOR_MAP` con DoodStream, Voe, FileLions, StreamWish
- `curl_cffi` está instalado en el contenedor
- vimeos.net devuelve HTML con script `eval(function(p,a,c,k,e,d))` que contiene URLs m3u8 (VERIFICADO)
- waaw.to/f/{id} redirige a iframe /e/{id} con player de video
- vidhidepro.com usa JS packed pero con formato diferente
- bysejikuar.com aparece frecuentemente en el catálogo de Cuevana
- El contenedor corre en `/app` con Python 3.11
- El directorio `src/services/resolvers/` no existe aún
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
