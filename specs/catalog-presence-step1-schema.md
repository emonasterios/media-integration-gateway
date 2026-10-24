# ENCARGO: Estado persistente de presencia de fuentes — unidad 1 (esquema)

## Objetivo acotado

Introducir únicamente el modelo persistente necesario para observar que una fuente estuvo
presente o ausente en sincronizaciones sucesivas. Esta unidad NO cambia todavía el flujo de
sincronización, NO marca ausencias y NO borra, desactiva ni retira fuentes o películas.

La decisión de producto es separar tres dimensiones: presencia en catálogo, disponibilidad de
la fuente y salud del resolver. Los campos de esta unidad representan solo presencia en catálogo.

## Reglas obligatorias

- Leer cada archivo antes de editarlo y tocar solo lo necesario.
- No modificar `scripts/sync_catalog.py`, adapters, resolvers, rutas API ni lógica de reproducción.
- No introducir borrado físico ni política automática de retiro.
- La migración debe preservar todas las filas existentes de `media` y `sources`.
- SQLite existente debe poder subir a `head`, bajar una revisión y volver a subir.

## PASO 1: Ampliar el modelo Source

Modificar `src/db/models.py` para añadir a `Source`:

- `catalog_presence`: `String(16)`, no nulo, default Python `"present"`.
- `last_seen_at`: `DateTime(timezone=True)`, nullable.
- `last_seen_run_id`: `String(36)`, nullable. No crear foreign key: el historial de presencia no
  debe invalidarse si se purgan corridas antiguas.
- `missing_since`: `DateTime(timezone=True)`, nullable.
- `consecutive_misses`: `Integer`, no nulo, default Python `0`.

Contrato inicial: `catalog_presence` admite conceptualmente `present`, `missing` y `retired`,
pero esta unidad no implementa transiciones. Los registros existentes deben quedar como
`present`, con cero ausencias y timestamps/run id nulos.

No añadir estos campos a `Media`: la presencia pertenece a cada fuente y una película puede
tener varias fuentes.

## PASO 2: Migración Alembic reversible

Crear `alembic/versions/a9b4c3d2e5f6_source_catalog_presence.py`, encadenada estrictamente a
`f8a3b2c1d4e5`.

En `upgrade()`, usar `op.batch_alter_table("sources")` y añadir:

- `catalog_presence`, `sa.String(length=16)`, `nullable=False`, `server_default="present"`.
- `last_seen_at`, `sa.DateTime(timezone=True)`, nullable.
- `last_seen_run_id`, `sa.String(length=36)`, nullable.
- `missing_since`, `sa.DateTime(timezone=True)`, nullable.
- `consecutive_misses`, `sa.Integer()`, `nullable=False`, `server_default="0"`.

En `downgrade()`, eliminar exclusivamente esas cinco columnas mediante batch alter. No tocar
filas ni otras tablas.

## PASO 3: Pruebas de migración

Ampliar `tests/test_migrations.py` con pruebas que usen SQLite temporal y demuestren:

1. Una base en `f8a3b2c1d4e5` con filas de `media` y `sources` conserva exactamente sus datos al
   subir a `head`; los nuevos valores son `present`, `0` y `NULL` según corresponda.
2. Una fuente nueva puede persistir valores explícitos `missing`, timestamps, run id y contador.
3. El downgrade a `f8a3b2c1d4e5` elimina solo las cinco columnas nuevas y conserva las filas.
4. Tras el downgrade, volver a `head` funciona y restablece defaults compatibles.

No usar red ni la base `data/gateway.db`.

## Fuera de alcance

- Cambiar reconciliación o reemplazar borrados actuales.
- Marcar fuentes ausentes durante una corrida.
- La regla de dos sincronizaciones.
- Exponer presencia por API.
- Registrar disponibilidad o fallos del resolver.
- Despliegue o sincronización real.

## ACEPTACION

```bash
grep -q 'catalog_presence' src/db/models.py
grep -q 'consecutive_misses' src/db/models.py
test -f alembic/versions/a9b4c3d2e5f6_source_catalog_presence.py
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_migrations.py
. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q
test ! -e data/gateway.db
git diff --exit-code origin/main -- scripts/sync_catalog.py src/adapters src/api src/services/video_resolver.py src/services/mediaflow_bridge.py
```

## PREMISES

- `Source` vive en `src/db/models.py` y actualmente no representa presencia o ausencia en el catálogo.
- La cabeza Alembic actual es `f8a3b2c1d4e5_sync_progress_redesign.py` con revisión `f8a3b2c1d4e5`.
- `tests/test_migrations.py` ya prueba upgrade/downgrade sobre SQLite temporal mediante `DATABASE_URL`.
- La sincronización actual aún puede reconciliar con borrado; esta unidad no toca ese comportamiento.
- `origin/main` apunta a `0f832de` y la suite verificada tiene 172 pruebas en verde.
