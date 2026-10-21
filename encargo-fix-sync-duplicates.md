# Fix: sync_catalog falla con "Multiple rows found" por duplicados de título

## Problema
`src/services/cache.py` línea 75-79 busca películas existentes por `title` con `scalar_one_or_none()`. Cuando el adapter devuelve la misma película dos veces (aparece en múltiples páginas de género), SQLAlchemy lanza "Multiple rows were found when one or none was required".

El modelo Media NO tiene campo `provider_id`. El identificador único vive en `sources.url` (el slug como "una-buena-receta").

## Solución

### src/services/cache.py — save_media: buscar por source URL en vez de title

Cambiar las líneas 71-79:

```python
# ANTES:
        # Buscar existente
        if "genres" in item_data and isinstance(item_data["genres"], list):
            item_data["genres"] = json.dumps(item_data["genres"])

        stmt = select(Media).filter(Media.title == title)
        if media_type:
            stmt = stmt.filter(Media.media_type == media_type)
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()

# DESPUÉS:
        # Buscar existente por source URL (único) en vez de title (puede tener duplicados)
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

### Importar Source en cache.py

Agregar el import si no existe (línea ~10):

```python
from src.db.models import Media, Source
```

## NO tocar
- video_resolver.py
- adapters/
- api/xtream.py
- models/
- db/models.py (no agregar campos)
- tests (no necesitan cambio, el comportamiento es el mismo sin duplicados)

## ACEPTACION
```bash
cd /home/emon/media-integration-gateway && python -m pytest tests/ -x -q
```

## PREMISES
- src/services/cache.py:75-79 usa select(Media).filter(Media.title == title) con scalar_one_or_none()
- src/db/models.py:12-27 modelo Media NO tiene provider_id
- src/db/models.py:30-41 modelo Source tiene url (slug único), provider, quality, language
- sync_catalog.log muestra 2 errores: "Air" y "Una buena receta" — ambos "Multiple rows were found"
- sources_data es una lista de dicts con al menos {"provider", "url", "quality", "language"}
