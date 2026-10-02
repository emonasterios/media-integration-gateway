<!-- spec:396e294f8b9176b73d1bb6dfa788d103 -->
REGLAS OBLIGATORIAS:
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

## PASO 1: Implementar `get_by_source` en `src/services/cache.py`

Abrir y leer `src/services/cache.py`.
Localizar la clase `CatalogCache` y su método `get_media`.
Inmediatamente debajo del método `get_media` (sin modificar `get_media` ni el resto del archivo), añadir el siguiente método:

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

Guardar el archivo asegurando que no se modificó nada más.

## PASO 2: Añadir prueba unitaria para `get_by_source` en `tests/test_cache.py`

Abrir y leer `tests/test_cache.py`.
Al final del archivo, añadir una nueva función de prueba que valide `get_by_source`, siguiendo las convenciones y fixtures del archivo:

```python
def test_get_by_source(db_session):
    cache = CatalogCache(db_session)
    cache.save_media(
        {"title": "La primera vez", "media_type": "movie"},
        [{"provider": "cuevana3", "url": "la-primera-vez"}],
    )

    found = cache.get_by_source("cuevana3", "la-primera-vez")
    assert found is not None
    assert found.title == "La primera vez"

    not_found = cache.get_by_source("cuevana3", "otra")
    assert not_found is None
```

Guardar el archivo asegurando que compila y que las pruebas pasan.

## PASO 3: Conectar la búsqueda por fuente en `src/services/catalog.py`

Abrir y leer `src/services/catalog.py`.
Localizar el método `_get_from_cache(self, provider: str, media_id: str)`.
Mantener la comprobación inicial:
`if not _HAS_CACHE or self._cache is None: return None`
Sustituir TODO el bloque posterior dentro de dicho método para que quede exactamente así:

```python
    def _get_from_cache(self, provider: str, media_id: str):
        if not _HAS_CACHE or self._cache is None:
            return None
        db_media = self._cache.get_by_source(provider, media_id)
        if db_media:
            return self._convert_db_media_to_item(db_media, provider)
        return None
```

No tocar `_save_to_cache` ni ningún otro método. Guardar el archivo.

## PASO 4: Inyectar `CatalogCache` en la app real en `src/main.py`

Abrir y leer `src/main.py`.
Localizar la función `lifespan` y dentro de ella la rama `else` (donde se configura la app real con el adaptador).
Sustituir la línea:
`catalog = CatalogService(providers=[adapter])`
por:
```python
        from src.db.database import SessionLocal, init_db
        from src.services.cache import CatalogCache
        init_db()
        db = SessionLocal()
        catalog = CatalogService(providers=[adapter], cache=CatalogCache(db))
```
Y en el bloque de limpieza, inmediatamente después de `await adapter.close()`, añadir:
```python
        db.close()
```

Guardar el archivo asegurando que compila sin errores.

ACEPTACION
grep -q "def get_by_source" src/services/cache.py
grep -q "Source.url == provider_id" src/services/cache.py
grep -q "self._cache.get_by_source(provider, media_id)" src/services/catalog.py
grep -q "CatalogCache(db)" src/main.py
grep -q "db.close()" src/main.py
grep -q "test_get_by_source" tests/test_cache.py

PREMISES
- src/services/cache.py tiene CatalogCache con get_media, save_media e is_valid, e importa Media y Source
- src/services/catalog.py tiene _get_from_cache y _save_to_cache; _save_to_cache guarda Source.url = item.provider_id
- src/main.py crea CatalogService(providers=[adapter]) sin caché dentro de lifespan
- scripts/accept_cache.py hoy sale con RECHAZADO (2 fallos) y no se modifica
- 56 tests pasando actualmente
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
