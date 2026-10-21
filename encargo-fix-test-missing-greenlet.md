# Fix: test_save_media_updates_existing_record falla con MissingGreenlet

## Problema
`tests/test_cache.py` línea 428: `await db_session.refresh(media)` después de `await db_session.commit()` dispara lazy-load síncrono en AsyncSession → `sqlalchemy.exc.MissingGreenlet`.

El error NO está en `src/services/cache.py` (ese código está correcto con selectinload). El bug está SOLO en el setup del test.

## Archivo a modificar
`tests/test_cache.py` — SOLO el método `test_save_media_updates_existing_record` (líneas ~422-450)

## Qué hacer
Reemplazar el patrón `commit() + refresh()` por `flush()` para obtener el ID sin expirar el objeto:

**ANTES (líneas ~426-433):**
```python
        media = Media(title="Existing", media_type="movie", year=2020, synopsis="Old", updated_at=old_time)
        db_session.add(media)
        await db_session.commit()
        await db_session.refresh(media)

        old_source = Source(media_id=media.id, provider="old_provider", url="old", quality="720p", language="en")
        db_session.add(old_source)
        await db_session.commit()
```

**DESPUÉS:**
```python
        media = Media(title="Existing", media_type="movie", year=2020, synopsis="Old", updated_at=old_time)
        db_session.add(media)
        await db_session.flush()  # Asigna media.id sin expirar (evita MissingGreenlet)

        old_source = Source(media_id=media.id, provider="old_provider", url="old", quality="720p", language="en")
        db_session.add(old_source)
        await db_session.flush()
```

## Verificación
```bash
cd /home/emon/media-integration-gateway && . .venv/bin/activate && python3 -m pytest tests/test_cache.py::TestCatalogCacheDirect::test_save_media_updates_existing_record -v
cd /home/emon/media-integration-gateway && . .venv/bin/activate && python3 -m pytest tests/ -x -q
```

## NO tocar
- `src/services/cache.py` — ya está correcto
- Ningún otro archivo de src/
- Ningún otro test

PREMISES
- tests/test_cache.py:428 usa await db_session.refresh(media) tras commit → MissingGreenlet
- El error real: SELECT media.id WHERE media.id = ? falla por lazy-load fuera de greenlet
- flush() asigna IDs sin expirar atributos, evitando la necesidad de refresh()
- 94 tests pasan, solo este falla
