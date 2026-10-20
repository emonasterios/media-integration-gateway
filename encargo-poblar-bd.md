# Encargo: Poblar BD con catálogo y verificar géneros

## Contexto
La BD está vacía (0 items). El catálogo funciona: `get_catalog()` devuelve 1500 items (1300 pelis, 200 series). La migración de géneros ya está aplicada. Hay un cambio pendiente en `config.py` (DATABASE_URL -> sqlite+aiosqlite:///) que no se ha commiteado.

## QUÉ HACER

### Paso 1: Commitear cambio pendiente de config.py
```bash
cd /home/emon/media-integration-gateway
git add src/core/config.py
git commit -m "fix: DATABASE_URL usa sqlite+aiosqlite para async engine"
```

### Paso 2: Ejecutar populate_catalog.py con límite de 50 items
```bash
cd /home/emon/media-integration-gateway
. .venv/bin/activate
python scripts/populate_catalog.py --limit 50 --delay 1.0
```

### Paso 3: Verificar que la BD tiene items con géneros
```bash
cd /home/emon/media-integration-gateway
. .venv/bin/activate
python -c "
import asyncio, sys
sys.path.insert(0, '.')
from src.db.models import Media
from src.db.database import AsyncSessionLocal
from sqlalchemy import select, func
async def main():
    async with AsyncSessionLocal() as s:
        total = (await s.execute(select(func.count(Media.id)))).scalar()
        movies = (await s.execute(select(func.count(Media.id)).where(Media.media_type == 'movie'))).scalar()
        series = (await s.execute(select(func.count(Media.id)).where(Media.media_type == 'series'))).scalar()
        with_genres = (await s.execute(select(func.count(Media.id)).where(Media.genres.is_not(None)))).scalar()
        print(f'Total: {total}, Peliculas: {movies}, Series: {series}')
        print(f'Con generos: {with_genres}')
        # Mostrar algunos ejemplos
        result = await s.execute(select(Media).limit(5))
        for m in result.scalars().all():
            print(f'  {m.title} | genres={m.genres}')
asyncio.run(main())
"
```

### Paso 4: Ejecutar tests para verificar que nada se rompió
```bash
cd /home/emon/media-integration-gateway
. .venv/bin/activate
pytest tests/ -v --tb=short
```

## QUÉ NO TOCAR
- No modificar adapters, models, ni scripts existentes
- No cambiar la estructura de la BD
- No tocar tests existentes

## ACEPTACION
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v
cd /home/emon/media-integration-gateway && . .venv/bin/activate && python scripts/accept_cuevana3.py
cd /home/emon/media-integration-gateway && . .venv/bin/activate && python scripts/accept_cache.py

## PREMISES
- src/core/config.py línea 20: DATABASE_URL = "sqlite+aiosqlite:///./media_gateway.db" (cambio no commiteado)
- alembic/versions/b4c8d1e2f3a4_add_genres_to_media.py: migración de géneros ya aplicada
- scripts/populate_catalog.py: existe y funciona (extrae géneros desde adapter.get_details)
- scripts/enrich_genres.py: existe para enriquecer géneros de items sin géneros
- BD actual: 0 items (vacía)
- Catálogo: 1500 items (1300 pelis, 200 series) con géneros vacíos []
- tests: 94 passing
