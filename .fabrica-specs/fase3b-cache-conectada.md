# Fase 3b: la caché acierta y la app real la usa

Hoy la caché guarda por título ("La primera vez") y busca por slug ("la-primera-vez"): nunca
acierta. Y `src/main.py` crea `CatalogService` sin caché. Son tres ediciones pequeñas en
`src/services/cache.py`, `src/services/catalog.py` y `src/main.py`, más una prueba.

## Qué cambiar

1. `src/services/cache.py`: añadir a `CatalogCache`, debajo de `get_media`, este método (no
   tocar `get_media`):
   ```python
   def get_by_source(self, provider: str, provider_id: str) -> Optional[Media]:
       """Busca por la fuente (proveedor + id del proveedor), que es lo que conoce quien consulta."""
       media = (
           self.db.query(Media)
           .join(Source, Source.media_id == Media.id)
           .filter(Source.provider == provider, Source.url == provider_id)
           .first()
       )
       if media is None or not self.is_valid(media):
           return None
       _ = media.sources
       return media
   ```

2. `src/services/catalog.py`, en `_get_from_cache`: sustituir TODO el cuerpo que va después de
   `if not _HAS_CACHE or self._cache is None: return None` por:
   ```python
   db_media = self._cache.get_by_source(provider, media_id)
   if db_media:
       return self._convert_db_media_to_item(db_media, provider)
   return None
   ```

3. `src/main.py`, en `lifespan`, rama `else`: sustituir
   `catalog = CatalogService(providers=[adapter])` por:
   ```python
   from src.db.database import SessionLocal, init_db
   from src.services.cache import CatalogCache
   init_db()
   db = SessionLocal()
   catalog = CatalogService(providers=[adapter], cache=CatalogCache(db))
   ```
   y, después de `await adapter.close()`, añadir `db.close()`.

4. Prueba en `tests/test_cache.py` (añadir al final, con el estilo de las existentes):
   guardar con `save_media({"title": "La primera vez", "media_type": "movie"},
   [{"provider": "cuevana3", "url": "la-primera-vez"}])` y comprobar que
   `get_by_source("cuevana3", "la-primera-vez")` lo devuelve y que
   `get_by_source("cuevana3", "otra")` devuelve None.

## ACEPTACION
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -q
cd /home/emon/media-integration-gateway && . .venv/bin/activate && python scripts/accept_cache.py

## PREMISES
- src/services/cache.py tiene CatalogCache con get_media, save_media e is_valid, e importa Media y Source
- src/services/catalog.py tiene _get_from_cache y _save_to_cache; _save_to_cache guarda Source.url = item.provider_id
- src/main.py crea CatalogService(providers=[adapter]) sin caché dentro de lifespan
- scripts/accept_cache.py hoy sale con RECHAZADO (2 fallos) y no se modifica
- 56 tests pasando actualmente
