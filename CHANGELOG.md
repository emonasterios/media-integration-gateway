# Changelog

Todos los cambios notables en este proyecto.

## [0.1.0] — 2026-10-03

### Adapters
- **Cuevana3** (`cuevana3i.cc`): ~1300 películas con paginación, resolución Voe.sx/Doodstream/Playmogo
- **CuevanNet** (`cuevan.net`): ~240 películas + ~210 series, con paginación y resolución Streamtape/Morencius

### VideoResolver
- **voe.sx**: extracción HLS/MP4 directo vía FlareSolverr
- **doodstream.com**: extracción HLS/MP4 directo vía FlareSolverr
- **streamtape.com**: extracción HLS/MP4 directo vía FlareSolverr
- **morencius.com**: deobfuscación Dean Edwards Packer → HLS (m3u8)

### Endpoints
- **Xtream Codes API**: `player_api.php`, `/movie/`, `/series/`
- **REST API**: `/api/v1/movies`, `/api/v1/series`, `/api/v1/search`
- **M3U/XMLTV**: `/iptv/playlist.m3u`, `/iptv/xmltv.xml`
- **Health**: `/healthz`

### Infraestructura
- Docker Compose con FlareSolverr + Redis
- Redirect a CDN directo (no proxy) para byte-range nativo en TV
- Catálogo combinado multi-provider con fusión automática
