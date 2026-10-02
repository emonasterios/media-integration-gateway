<!-- spec:a9055cb20a8e84ddeecf7cc438e359c4 -->
# ENCARGO: Adaptar Cuevana3 a la estructura HTML real y añadir tests con fixtures

## REGLAS OBLIGATORIAS:
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

---

## PASO 1: Ajustar selectores de reproducción, sinopsis y año en src/adapters/cuevana3.py

**Archivo a modificar:**
- `src/adapters/cuevana3.py`

**Instrucciones:**
1. Leer `src/adapters/cuevana3.py` para ubicar `resolve_playback`, `_extract_overview`, `search` y `get_catalog`.
2. Verificar que `import re` esté presente en las importaciones. Si no está, importarlo.
3. En `resolve_playback(self, slug_or_id: str)`:
   - Al inicio de la sección donde se buscan servidores de reproducción en el HTML (antes de la llamada a `_extract_server_from_list`), incorporar la extracción desde etiquetas `li` con el atributo `data-server`:
     ```python
     li = soup.select_one("li[data-server]")
     if li and li.get("data-server"):
         return PlaybackDescriptor(protocol="embed", url=li["data-server"],
                                   headers={"Referer": self._base})
     ```
   - Mantener el resto del flujo de resolución como respaldo para compatibilidad.
4. En `_extract_overview(self, soup)`:
   - ANTES de la búsqueda genérica en etiquetas `article` o `p`, buscar la sinopsis en `div.Description p`:
     ```python
     desc = soup.select_one("div.Description p")
     if desc:
         return " ".join(desc.get_text(" ", strip=True).split())
     ```
5. En los bucles de extracción de películas en `search` y `get_catalog`:
   - Al extraer la información de cada elemento post/tarjeta, si `year` resulta `None`, buscar en `span.Year`:
     ```python
     year_el = post.select_one("span.Year")
     if year is None and year_el:
         m = re.search(r"\b(19|20)\d{2}\b", year_el.get_text())
         year = int(m.group(0)) if m else None
     ```

---

## PASO 2: Crear suite de pruebas con fixtures reales en tests/test_cuevana3_real.py

**Archivo a crear:**
- `tests/test_cuevana3_real.py`

**Instrucciones:**
1. Leer `tests/test_cuevana3.py` para replicar el estilo de mocking del cliente httpx (`unittest.mock.patch`, `AsyncMock`).
2. Leer las fixtures reales disponibles en:
   - `tests/fixtures/cuevana3_catalogo_peliculas.html`
   - `tests/fixtures/cuevana3_pelicula_signal-one.html`
3. Crear `tests/test_cuevana3_real.py` conteniendo pruebas asíncronas para el adapter `Cuevana3Adapter`:
   - **Prueba de catálogo (`cuevana3_catalogo_peliculas.html`):**
     - Mockear la respuesta HTTP devolviendo el HTML de `tests/fixtures/cuevana3_catalogo_peliculas.html`.
     - Invocar `get_catalog()`.
     - Comprobar que en la lista resultante se encuentra la película con identificador o slug `signal-one` y que su campo `year` es `2026`.
   - **Prueba de detalles (`cuevana3_pelicula_signal-one.html`):**
     - Mockear la respuesta HTTP devolviendo el HTML de `tests/fixtures/cuevana3_pelicula_signal-one.html`.
     - Invocar `get_details("signal-one")`.
     - Comprobar que `overview` comienza con `"Entre las producciones más comentadas"` y que `year` es `2026`.
   - **Prueba de reproducción (`cuevana3_pelicula_signal-one.html`):**
     - Mockear la respuesta HTTP devolviendo el HTML de `tests/fixtures/cuevana3_pelicula_signal-one.html`.
     - Invocar `resolve_playback("signal-one")`.
     - Comprobar que el descriptor devuelto tiene `protocol == "embed"` y `url == "https://doodstream.com/e/jtri5tfbukk6"`.
4. Ejecutar las pruebas para asegurar que pasen tanto las nuevas como las preexistentes.

---

ACEPTACION
grep -q 'li\[data-server\]' src/adapters/cuevana3.py
grep -q 'div.Description p' src/adapters/cuevana3.py
grep -q 'span.Year' src/adapters/cuevana3.py
test -f tests/test_cuevana3_real.py
pytest tests/test_cuevana3_real.py
pytest tests/test_cuevana3.py
pytest tests/ -v
python3 scripts/accept_cuevana3.py

PREMISES
- src/adapters/cuevana3.py:298 — resolve_playback busca data-mdl/data-url y falla en vivo
- src/adapters/cuevana3.py:392 — _extract_overview toma el primer p de article (el pie)
- tests/fixtures/cuevana3_pelicula_signal-one.html:1 — HTML real con li[data-server] y div.Description
- tests/fixtures/cuevana3_catalogo_peliculas.html:1 — HTML real del catálogo con span.Year
- scripts/accept_cuevana3.py:1 — compuerta en vivo; hoy da 5 fallos
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
