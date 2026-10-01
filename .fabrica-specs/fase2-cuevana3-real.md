# Fase 2: Adapter Cuevana3 funcional con selectores reales

## Contexto
El adapter `src/adapters/cuevana3.py` tiene selectores CSS genéricos (`.item`, `.poster`, `article`) que NO coinciden con la estructura real de cuevana3i.cc.

## Estructura REAL del sitio (verificada 2026-10-01)

### Catálogo (homepage /peliculas/)
- Items: `div.TPost a` con href a `/pelicula/{slug}/` o `/serie/{slug}/`
- Título: dentro del link, texto del año + nombre
- Imagen: `figure.Objf img` con `src` (a veces placeholder SVG data:image)
- Rating/año: texto dentro del mismo bloque

### Página de película (`/pelicula/{slug}/`)
- Título: `h1` dentro de `article`
- Sinopsis: primer `p` del article
- Año/duración: `sectionfooter` con texto "1h 52m", "2026", "HD"
- Género: links con texto "Ciencia ficción", "Misterio", etc.
- **Servidores de video**: lista `ul` con `li` que contienen:
  - `div._3CT5n_0` con `data-mdl` o estructura similar
  - Servidores reales: Doodstream, Voe, Vidhide (iframes de terceros)
  - El iframe se carga DINÁMICAMENTE al hacer clic — NO está en el HTML inicial
  - `img` con bandera (en.svg, es.svg) para idioma

### Página de serie (`/serie/{slug}/`)
- Similar a película pero con lista de temporadas/capítulos
- Capítulos: links con patrón `/serie/{slug}/temporada-{N}-capitulo-{M}/`

## Qué hacer

### 1. Reescribir `src/adapters/cuevana3.py` con selectores reales

**search() y get_catalog():**
```python
# Selector correcto para items del catálogo
for post in soup.select("div.TPost"):
    link = post.find("a", href=True)
    img = post.find("img")
    # Extraer título, año, poster_url
```

**get_details():**
```python
# Título: article h1 o h2
# Sinopsis: article > p (primer párrafo)
# Año: buscar patrón \b(19|20)\d{2}\b en sectionfooter
# Género: article a links después de "Genero:"
# Poster: article figure img o meta og:image
```

**resolve_playback():**
- El video NO está en el HTML inicial
- Los servidores (Doodstream, Voe, Vidhide) cargan iframes dinámicamente
- Estrategia: extraer URLs de servidores del HTML (pueden estar en `data-url`, `onclick`, o scripts inline)
- Si no se encuentran en HTML estático, usar browser para hacer clic y obtener el iframe src
- Fallback: devolver URL del primer servidor externo encontrado

### 2. Agregar tests de integración con pytest-httpx

Crear `tests/test_cuevana3.py` con HTML mock de:
- Página de catálogo con estructura `.TPost` real
- Página de película con `article`, `h1`, `sectionfooter`, servidores
- Verificar que el adapter extrae correctamente título, año, sinopsis, servidores

### 3. Manejo de errores
- Timeout de httpx → log warning, retornar lista vacía
- HTML sin selectores esperados → log debug con estructura encontrada
- Sitio caído o bloqueado → excepción clara, no crash silencioso

## Límites
- NO modificar `src/adapters/base.py` (interfaz estable)
- NO modificar `src/models/catalog.py` (modelos estables)
- NO modificar `src/main.py` ni `src/api/routes.py`
- NO tocar tests existentes en `tests/test_smoke.py`
- SOLO modificar `src/adapters/cuevana3.py` y agregar `tests/test_cuevana3.py`

## ACEPTACION
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v
cd /home/emon/media-integration-gateway && . .venv/bin/activate && python -c "
from src.adapters.cuevana3 import Cuevana3Adapter
import asyncio
async def test():
    a = Cuevana3Adapter()
    r = await a.search('Signal')
    print(f'Search: {len(r.items)} items')
    assert len(r.items) > 0, 'No se encontraron resultados'
    await a.close()
asyncio.run(test())
"

## PREMISES
- src/adapters/cuevana3.py:1 — adapter actual con selectores incorrectos (.item, .poster, article)
- src/adapters/base.py:1 — interfaz MediaProvider con 6 métodos abstractos
- src/models/catalog.py:1 — modelos MediaItem, SearchResult, PlaybackDescriptor, etc.
- tests/test_smoke.py:1 — 9 tests pasando con FakeProvider
- pyproject.toml:1 — dependencias: httpx, beautifulsoup4, lxml, fastapi, pydantic
- Verificación real del sitio 2026-10-01: selectores son div.TPost, article h1, sectionfooter, servidores en li con data-mdl
