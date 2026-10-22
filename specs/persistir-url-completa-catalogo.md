# Persistir la URL completa de la página de cada película

## Objetivo

Añadir a `sources` un único campo nullable `page_url` que conserve la URL
completa de la página de catálogo que el crawler ya descubre, y rellenarlo en
los flujos actuales de sincronización. Este cambio prepara futuros proveedores
sin rediseñar ahora la identidad ni la política de disponibilidad o retiro.

## Encargo

1. Añadir `Source.page_url` como `String`, nullable, sin cambiar el significado
   actual de `Source.url`: `url` continúa conteniendo el `provider_id`/slug.
2. Crear una migración Alembic posterior a la revisión actual que añada la
   columna nullable. La migración debe funcionar sobre una SQLite existente y
   tener downgrade seguro que elimine únicamente esa columna.
3. En `persist_page_batch`, guardar `item["url"]` en `page_url` al crear una
   fuente y actualizarlo en fuentes ya existentes. La ausencia de `item["url"]`
   no debe borrar un valor válido ya guardado.
4. Aplicar el mismo comportamiento al flujo `sync_from_checkpoint`.
5. Añadir pruebas que demuestren creación, actualización y conservación del
   valor previo cuando el ítem entrante no trae URL.
6. Ampliar la prueba de migración para demostrar que una base existente llega a
   `head`, conserva sus filas y obtiene `sources.page_url` nullable.
7. Mantener compatibilidad con checkpoints antiguos que no contengan `url`.

## Límites

- No renombrar ni reinterpretar `Source.url`.
- No añadir `provider_id`, estados de disponibilidad ni tablas adicionales.
- No modificar la política de bajas, el crawler, los resolvers ni la
  reproducción.
- No borrar películas o fuentes, ni tocar bases/checkpoints de producción.
- No implementar todavía el ejecutor asíncrono ni avisos Telegram.
- No tocar los cambios HLS ni los archivos sueltos del árbol principal.

## ACEPTACION

. /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_catalog_sync.py tests/test_migrations.py
. /home/emon/media-integration-gateway/.venv/bin/activate && python -c "from src.db.models import Source; assert Source.__table__.columns['page_url'].nullable is True; assert Source.__table_args__[0].columns.keys() == ['provider', 'url']"

PREMISES

I `Source` solo tiene `provider` y `url`; no existe un campo para la URL completa — src/db/models.py:30-44
I La identidad única vigente sigue siendo `(provider, url)` — src/db/models.py:33-35
I El crawler ya incluye la URL completa en cada ítem descubierto — src/adapters/cuevana3.py:445-455
I `persist_page_batch` guarda únicamente `provider_id` dentro de `Source.url` — scripts/sync_catalog.py:95-134
I `sync_from_checkpoint` también guarda únicamente `provider_id` dentro de `Source.url` — scripts/sync_catalog.py:222-250
I La revisión Alembic actual de integridad es posterior a la migración de géneros — alembic/versions/c5d9e2f3a4b5_sources_integrity.py:14-15
I Las migraciones se prueban sobre SQLite preexistente hasta `head` — tests/test_migrations.py:16-27
