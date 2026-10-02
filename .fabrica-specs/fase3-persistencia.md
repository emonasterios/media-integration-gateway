# Fase 3: Persistencia SQLite + caché de catálogo

## Qué hacer
1. Crear `src/db/models.py` — modelos SQLAlchemy (Media, Source, Favorite, History)
2. Crear `src/db/database.py` — engine, session, init_db
3. Crear `src/services/cache.py` — caché de catálogo con TTL configurable
4. Integrar caché en `src/services/catalog.py` — consultar DB antes de scrapear
5. Agregar `alembic` para migraciones
6. Tests en `tests/test_cache.py` y `tests/test_db.py`

## Límites
- NO modificar `src/adapters/` (ya funcionan)
- NO modificar `tests/test_smoke.py` ni `tests/test_cuevana3*.py`
- Mantener compatibilidad con los 30 tests existentes

## ACEPTACION
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v

## PREMISES
- src/services/catalog.py usa CatalogService con adapters
- src/models/catalog.py tiene MediaItem, Movie, Series, etc.
- 30 tests pasando actualmente
- pyproject.toml tiene dependencias básicas
