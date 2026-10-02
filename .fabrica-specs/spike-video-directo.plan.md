<!-- spec:0fc3f99c9ec4ee56b9185a67b1c060c2 -->
# ENCARGO: Spike de Extracción de Video Directo de Servidores de Streaming

## REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- NO modificar ningún archivo dentro de `src/` ni `tests/`.
- NO agregar dependencias en `pyproject.toml`.

---

## PASO 1: Implementar el script de diagnóstico en `scripts/spike_video_extract.py`

**Fallo de fondo a evitar:**
Si el script realiza peticiones HTTP directas sin cabeceras (`User-Agent`) o no captura errores de red/timeout/bloqueo de Cloudflare, la ejecución fallará con excepciones no controladas (`RequestException`, `ConnectionError`, `HTTPError`) y romperá la prueba de aceptación. El script DEBE capturar cualquier excepción de red o bloqueo y terminar siempre con código de salida 0 informando el resultado en pantalla.

**Archivo a modificar:**
`scripts/spike_video_extract.py`

**Qué debe quedar en `scripts/spike_video_extract.py`:**
1. Aceptar la URL como primer argumento de línea de comandos (`sys.argv[1]`), usando por defecto `https://cuevana3i.cc/pelicula/signal-one/` si no se pasa ningún argumento.
2. Usar `requests` con cabeceras de navegador estándar (`User-Agent: Mozilla/5.0 ...`) y `timeout=10` en todas las llamadas.
3. Seguir la cadena de extracción:
   - Descargar la página de la película y localizar enlaces de servidores o URLs con formato `play_movie.php?u=...`.
   - Decodificar los parámetros en base64 de las redirecciones cuando existan.
   - Seguir redirecciones o consultar el destino (incluyendo `playmogo.com` o servidores como doodstream, voe, vidhide, streamwish).
   - Analizar el HTML final buscando patrones de video directo (`.m3u8`, `.mp4`, etiquetas `<video>`, fuentes JavaScript) o detectar si la página está bloqueada por CAPTCHA / Cloudflare Turnstile (`Just a moment...`, `cf-chl`, `playmogo.com`).
4. Imprimir por consola un reporte estructurado y claro:
   - URL analizada.
   - Servidores encontrados en la página.
   - Cadena de redirección seguida paso a paso.
   - Diagnóstico final de extracción: indicar si se obtuvo enlace directo o si se confirmó el bloqueo por Cloudflare/CAPTCHA en el intermediario (`playmogo.com`).
5. Manejar cualquier error de conexión con `try/except` imprimiendo el diagnóstico sin arrojar excepciones no controladas, retornando código de salida 0.

---

## PASO 2: Documentar hallazgos y alternativas en `docs/spike-video-extract.md`

**Archivo a crear:**
`docs/spike-video-extract.md` (crear el directorio `docs/` si no existe).

**Qué debe quedar en `docs/spike-video-extract.md`:**
Un informe técnico detallado en Markdown que contenga las siguientes secciones:
1. **Objetivo**: Evaluar la viabilidad de extraer URLs directas de video (.m3u8 / .mp4) para su consumo en reproductores IPTV a partir de Cuevana3 y sus servidores asociados.
2. **Cadena de Redirección Analizada**:
   - Detalle del flujo: Cuevana3 -> `play_movie.php?u=BASE64` -> `playmogo.com` -> Hosts externos (doodstream, voe, vidhide, streamwish).
3. **Comportamiento por Servidor**:
   - `doodstream`: estado, presencia de tokens dinámicos y protecciones.
   - `voe`, `vidhide`, `streamwish`: comportamiento ante peticiones automatizadas.
4. **Protecciones Identificadas**:
   - Bloqueo de Cloudflare CAPTCHA / Turnstile en la pasarela intermedia `playmogo.com`.
   - Ofuscación de reproductores web vs URLs estáticas directas.
5. **Conclusión y Alternativas**:
   - Conclusión explícita de viabilidad para IPTV estándar (inviable mediante simple HTTP scraping sin resolver CAPTCHA).
   - Alternativas viables: uso de solvers headless (FlareSolverr, Puppeteer/Playwright Stealth), proxies de bypass de CAPTCHA, o servir la URL embebida en clientes compatibles con Webview.

---

ACEPTACION
python3 scripts/spike_video_extract.py https://cuevana3i.cc/pelicula/signal-one/
test -f docs/spike-video-extract.md
grep -qi "doodstream" docs/spike-video-extract.md
grep -qi "cloudflare" docs/spike-video-extract.md
grep -qi "playmogo" docs/spike-video-extract.md

PREMISES
- src/adapters/cuevana3.py ya extrae servidores disponibles
- El adapter devuelve nombres como "doodstream", "voe", "vidhide"
- 57 tests pasando en main
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
