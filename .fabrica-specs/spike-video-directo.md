# Spike: Extracción de video directo de servidores de streaming

## Objetivo
Determinar si es posible extraer URLs de video directo (m3u8/mp4) de los servidores que usa Cuevana3 (doodstream, voe, vidhide, streamwish).

## Hallazgos previos
- Cuevana usa `play_movie.php?u=BASE64` que redirige a hosts externos
- Al hacer clic en "Reproducir", redirige a `playmogo.com` con protección Cloudflare CAPTCHA
- Los reproductores IPTV necesitan URLs directas (m3u8/mp4), no páginas web

## Qué hacer
1. Probar con UN solo servidor (empezar por doodstream o el más accesible)
2. Usar requests + BeautifulSoup para seguir la cadena de redirecciones
3. Buscar en el HTML final URLs de video (.m3u8, .mp4, fuentes de video.js)
4. Si hay Cloudflare CAPTCHA, documentar el bloqueo y alternativas

## Resultado esperado
- Script en `scripts/spike_video_extract.py` que dado un URL de Cuevana, intente extraer el video directo
- Documento `docs/spike-video-extract.md` con: qué servidores funcionan, cuáles bloquean, alternativas

## Límites
- NO modificar código del proyecto
- NO agregar dependencias permanentes
- Solo investigación y documentación

## ACEPTACION
cd /home/emon/media-integration-gateway && . .venv/bin/activate && python scripts/spike_video_extract.py https://cuevana3i.cc/pelicula/signal-one/
test -f docs/spike-video-extract.md

## PREMISES
- src/adapters/cuevana3.py ya extrae servidores disponibles
- El adapter devuelve nombres como "doodstream", "voe", "vidhide"
- 57 tests pasando en main
