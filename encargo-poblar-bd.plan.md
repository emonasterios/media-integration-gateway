<!-- spec:08e26267cc390e8b50fcfc89fb590491 -->
# ENCARGO: Poblar base de datos con catálogo y verificar géneros

## REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- Cada paso debe dejar el proyecto funcionando y compilando.

---

## PASO 1: Asegurar y commitear la configuración de base de datos asíncrona
- **Archivo involucrado**: `src/core/config.py`
- **Objetivo**: Asegurar que `DATABASE_URL` use el driver `sqlite+aiosqlite:///./media_gateway.db` para que el engine asíncrono no falle en tiempo de ejecución.
- **Acción**:
  1. Leer `src/core/config.py` y verificar que la línea de `DATABASE_URL` contiene:
     ```python
     DATABASE_URL: str = "sqlite+aiosqlite:///./media_gateway.db"
     ```
  2. Si falta o difiere, editar únicamente esa línea manteniendo el resto del archivo intacto.
  3. Ejecutar en terminal:
     ```bash
     git add src/core/config.py
     git commit -m "fix: DATABASE_URL usa sqlite+aiosqlite para async engine"
     ```

---

## PASO 2: Ejecutar el poblado del catálogo con extracción de géneros
- **Archivo involucrado**: `scripts/populate_catalog.py`
- **Objetivo**: Poblar la base de datos `media_gateway.db` con al menos 50 elementos extrayendo sus detalles y géneros.
- **Acción**:
  1. Ejecutar el script existente sin modificar su código:
     ```bash
     python3 scripts/populate_catalog.py --limit 50 --delay 1.0
     ```
  2. Verificar en la salida que los items procesados reporten géneros asignados y que no ocurran excepciones de base de datos.

---

## PASO 3: Validar el contenido persistido y géneros en la base de datos
- **Archivos involucrados**: `src/db/models.py`, `src/db/database.py`
- **Objetivo**: Comprobar mediante consulta a los modelos que los registros fueron persistidos con sus géneros.
- **Acción**:
  1. Ejecutar la siguiente comprobación:
     ```bash
     python3 -c "
     import asyncio
     from src.db.models import Media
     from src.db.database import AsyncSessionLocal
     from sqlalchemy import select, func

     async def check():
         async with AsyncSessionLocal() as s:
             total = (await s.execute(select(func.count(Media.id)))).scalar()
             with_genres = (await s.execute(select(func.count(Media.id)).where(Media.genres.is_not(None)))).scalar()
             print(f'Total: {total}, Con generos: {with_genres}')
             assert total >= 50, f'Esperados al menos 50 items, encontrados {total}'
             assert with_genres > 0, 'No hay items con generos'

     asyncio.run(check())
     "
     ```

---

## PASO 4: Ejecutar tests de regresión y scripts de aceptación
- **Archivos involucrados**: `tests/test_db.py`, `scripts/accept_cuevana3.py`, `scripts/accept_cache.py`
- **Objetivo**: Garantizar que el poblado no rompió la suite de tests ni los scripts de aceptación del sistema.
- **Acción**:
  1. Ejecutar la suite completa de tests:
     ```bash
     pytest tests/ -v --tb=short
     ```
  2. Ejecutar los scripts de aceptación:
     ```bash
     python3 scripts/accept_cuevana3.py
     python3 scripts/accept_cache.py
     ```

---

ACEPTACION
git diff --quiet src/core/config.py
grep -q "sqlite+aiosqlite" src/core/config.py
test -f media_gateway.db
python3 -c "import sqlite3; con = sqlite3.connect('media_gateway.db'); count = con.execute('SELECT count(*) FROM media').fetchone()[0]; exit(0 if count >= 50 else 1)"
python3 -c "import sqlite3; con = sqlite3.connect('media_gateway.db'); count = con.execute('SELECT count(*) FROM media WHERE genres IS NOT NULL AND genres != \"[]\"').fetchone()[0]; exit(0 if count > 0 else 1)"
pytest tests/ -q
python3 scripts/accept_cuevana3.py
python3 scripts/accept_cache.py

PREMISES
- src/core/config.py línea 20: DATABASE_URL = "sqlite+aiosqlite:///./media_gateway.db" (cambio no commiteado)
- alembic/versions/b4c8d1e2f3a4_add_genres_to_media.py: migración de géneros ya aplicada
- scripts/populate_catalog.py: existe y funciona (extrae géneros desde adapter.get_details)
- scripts/enrich_genres.py: existe para enriquecer géneros de items sin géneros
- BD actual: 0 items (vacía)
- Catálogo: 1500 items (1300 pelis, 200 series) con géneros vacíos []
- tests: 94 passing
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
