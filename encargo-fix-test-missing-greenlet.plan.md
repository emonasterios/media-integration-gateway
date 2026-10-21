<!-- spec:f366e6d28879e545ee0992bebd0fdc56 -->
# ENCARGO: Corrección de MissingGreenlet en test_save_media_updates_existing_record

## REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

---

## PASO 1: Reemplazar `commit() + refresh()` por `flush()` en `tests/test_cache.py`

### Archivo afectado
- `tests/test_cache.py`

### Contexto del fallo
En `tests/test_cache.py`, dentro del método de test `test_save_media_updates_existing_record` (alrededor de las líneas 422-450), se ejecuta `await db_session.commit()` seguido de `await db_session.refresh(media)`. En SQLAlchemy con `AsyncSession`, esto expira los atributos del objeto y dispara una carga perezosa (lazy-load) síncrona fuera de un greenlet, provocando `sqlalchemy.exc.MissingGreenlet`. El servicio bajo prueba ya utiliza `selectinload` correctamente; el error reside exclusivamente en la preparación de datos dentro del test.

### Modificación requerida
Localizar en `tests/test_cache.py` el bloque de inicialización dentro de `test_save_media_updates_existing_record`:

```python
        media = Media(title="Existing", media_type="movie", year=2020, synopsis="Old", updated_at=old_time)
        db_session.add(media)
        await db_session.commit()
        await db_session.refresh(media)

        old_source = Source(media_id=media.id, provider="old_provider", url="old", quality="720p", language="en")
        db_session.add(old_source)
        await db_session.commit()
```

Sustituirlo exactamente por:

```python
        media = Media(title="Existing", media_type="movie", year=2020, synopsis="Old", updated_at=old_time)
        db_session.add(media)
        await db_session.flush()

        old_source = Source(media_id=media.id, provider="old_provider", url="old", quality="720p", language="en")
        db_session.add(old_source)
        await db_session.flush()
```

### Resultado esperado
`flush()` envía las inserciones pendientes a la base de datos y puebla `media.id` de forma inmediata sin expirar los atributos del modelo en memoria, eliminando la necesidad de `refresh()` y previniendo el error `MissingGreenlet`. No tocar ningún otro método del archivo ni ningún archivo en `src/`.

---

ACEPTACION
! grep -q "await db_session.refresh(media)" tests/test_cache.py
pytest tests/test_cache.py -k test_save_media_updates_existing_record -q

PREMISES
- tests/test_cache.py:428 usa await db_session.refresh(media) tras commit → MissingGreenlet
- El error real: SELECT media.id WHERE media.id = ? falla por lazy-load fuera de greenlet
- flush() asigna IDs sin expirar atributos, evitando la necesidad de refresh()
- 94 tests pasan, solo este falla
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
