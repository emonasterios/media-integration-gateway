<!-- spec:6293781b0671a79374ae88faabfd488b -->
# ENCARGO: Evitar errores de filas duplicadas en sync_catalog buscando por URL de Source

## REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- NO tocar `src/services/video_resolver.py`, `src/adapters/`, `src/api/xtream.py`, `src/models/`, `src/db/models.py` ni `tests/`.

---

## PASO 1: Actualizar la búsqueda de duplicados en src/services/cache.py

### Archivo a modificar
`src/services/cache.py`

### Qué hacer
1. **Importación:**
   En los imports al inicio de `src/services/cache.py`, asegurar que `Source` se importe desde `src.db.models`:
   ```python
   from src.db.models import Media, Source
   ```

2. **Búsqueda en `save_media`:**
   En el método `save_media(self, item_data: dict, sources_data: list[dict] = None) -> Media`, localizar el bloque donde se busca si la entrada ya existe (alrededor de las líneas 71-80):
   ```python
        if "genres" in item_data and isinstance(item_data["genres"], list):
            item_data["genres"] = json.dumps(item_data["genres"])

        stmt = select(Media).filter(Media.title == title)
        if media_type:
            stmt = stmt.filter(Media.media_type == media_type)
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()
   ```

   Sustituir la lógica de búsqueda para que use `source_url` (slug único en la tabla `sources`) como identificador principal en lugar de `title`, manteniendo la búsqueda por `title` solo como fallback:
   ```python
        if "genres" in item_data and isinstance(item_data["genres"], list):
            item_data["genres"] = json.dumps(item_data["genres"])

        # Usar el primer source URL como clave única
        source_url = sources_data[0].get("url") if sources_data else None
        if source_url:
            # JOIN con sources para buscar por URL única
            stmt = (
                select(Media)
                .join(Source, Media.id == Source.media_id)
                .where(Source.url == source_url)
            )
        else:
            # Fallback: buscar por title (comportamiento anterior)
            stmt = select(Media).filter(Media.title == title)
            if media_type:
                stmt = stmt.filter(Media.media_type == media_type)
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()
   ```

3. Verificar que el código quede limpio, sin sintaxis rota y pasando los tests.

---

ACEPTACION
grep -q "from src.db.models import.*Source" src/services/cache.py
grep -q "join(Source, Media.id == Source.media_id)" src/services/cache.py
grep -q "where(Source.url == source_url)" src/services/cache.py
python3 -m pytest tests/test_cache.py -q
python3 -m pytest tests/ -x -q

PREMISES
- src/services/cache.py:75-79 usa select(Media).filter(Media.title == title) con scalar_one_or_none()
- src/db/models.py:12-27 modelo Media NO tiene provider_id
- src/db/models.py:30-41 modelo Source tiene url (slug único), provider, quality, language
- sync_catalog.log muestra 2 errores: "Air" y "Una buena receta" — ambos "Multiple rows were found"
- sources_data es una lista de dicts con al menos {"provider", "url", "quality", "language"}
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
