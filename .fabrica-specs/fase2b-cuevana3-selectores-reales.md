# Fase 2b: el adapter Cuevana3 lee lo que de verdad trae la página

El spec anterior describía mal el sitio (decía data-mdl e iframe dinámico). El HTML REAL está
guardado en tests/fixtures/ y es la única referencia válida. Solo se toca
`src/adapters/cuevana3.py` y se añade `tests/test_cuevana3_real.py`.

## Qué cambiar en src/adapters/cuevana3.py

1. Reproducción. Al principio de la parte que busca servidores en `resolve_playback`, antes de
   `_extract_server_from_list`, usar los `li` con atributo `data-server` (en la página real son
   Doodstream, Voe, Vidhide, Streamwish, en ese orden):
   ```python
   li = soup.select_one("li[data-server]")
   if li and li.get("data-server"):
       return PlaybackDescriptor(protocol="embed", url=li["data-server"],
                                 headers={"Referer": self._base})
   ```

2. Sinopsis. En `_extract_overview`, ANTES de buscar en `article`, usar `div.Description p`:
   ```python
   desc = soup.select_one("div.Description p")
   if desc:
       return " ".join(desc.get_text(" ", strip=True).split())
   ```
   Hoy devuelve el pie ("1h 52m2026HD") porque el primer `p` de `article` es `p.meta`.

3. Año en catálogo y búsqueda. Cada película del listado trae `<span class=Year> 2026 </span>`
   dentro del enlace. En los bucles de `search` y `get_catalog`, si el año sale None:
   ```python
   year_el = post.select_one("span.Year")
   if year is None and year_el:
       m = re.search(r"\b(19|20)\d{2}\b", year_el.get_text())
       year = int(m.group(0)) if m else None
   ```

## Pruebas: tests/test_cuevana3_real.py (archivo NUEVO)

Con el MISMO estilo de mock que tests/test_cuevana3.py (unittest.mock patch/AsyncMock del
cliente httpx), pero sirviendo los archivos reales de tests/fixtures/:
- catálogo (`cuevana3_catalogo_peliculas.html`): la película `signal-one` sale con year 2026.
- película (`cuevana3_pelicula_signal-one.html`): `get_details("signal-one")` da overview que
  empieza por "Entre las producciones más comentadas" y year 2026.
- `resolve_playback("signal-one")` devuelve url "https://doodstream.com/e/jtri5tfbukk6".

## Límites
- NO tocar scripts/accept_cuevana3.py, .fabrica-aceptacion, tests/fixtures/, base.py, catalog.py,
  pyproject.toml, tests/test_smoke.py. La compuerta no se edita: se cumple.

## ACEPTACION
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v
cd /home/emon/media-integration-gateway && . .venv/bin/activate && python scripts/accept_cuevana3.py
grep -q 'li\[data-server\]' src/adapters/cuevana3.py
grep -q 'div.Description p' src/adapters/cuevana3.py
test -f tests/test_cuevana3_real.py

## PREMISES
- src/adapters/cuevana3.py:298 — resolve_playback busca data-mdl/data-url y falla en vivo
- src/adapters/cuevana3.py:392 — _extract_overview toma el primer p de article (el pie)
- tests/fixtures/cuevana3_pelicula_signal-one.html:1 — HTML real con li[data-server] y div.Description
- tests/fixtures/cuevana3_catalogo_peliculas.html:1 — HTML real del catálogo con span.Year
- scripts/accept_cuevana3.py:1 — compuerta en vivo; hoy da 5 fallos
