# Encargo: cerrar pruebas y documentación del descubrimiento reanudable

## Objetivo

Completar y validar la implementación local ya existente de checkpoints de catálogo. Esta
unidad solo puede usar respuestas HTTP simuladas, rutas temporales y bases SQLite temporales.
No debe ejecutar el crawler real ni escribir en `data/`.

## Alcance

1. Crear `tests/test_catalog_checkpoint.py` con pruebas de guardado/carga atómicos,
   preservación del último checkpoint ante fallo de escritura, deduplicación estable,
   versiones incompatibles, proveedor/categoría incompatibles y bloqueo de snapshots
   `incomplete`.
2. Añadir a `tests/test_cuevana3.py` pruebas con HTTP completamente simulado para:
   - más de 20 páginas y estado final `complete`;
   - fallo intermedio tras tres intentos y checkpoint `incomplete` exacto;
   - reanudación desde `next_page` sin pedir páginas confirmadas;
   - segundo fallo tras reanudar sin corromper el checkpoint anterior;
   - deduplicación a través de páginas y reanudaciones.
3. Probar `sync_from_checkpoint` con un checkpoint incompleto, corrupto o incompatible y
   demostrar que `AsyncSessionLocal` no llega a abrirse. Probar también que la categoría
   esperada se valida al reconciliar un checkpoint categorizado.
4. Corregir defectos mínimos de la implementación que revelen esas pruebas. No rediseñar
   módulos ni tocar reproducción, API pública o despliegue.
5. Actualizar `docs/operations/catalog-sync-2026-10-21.md` con formato, ruta configurable,
   comandos `--status`, `--discover-only`, `--from-checkpoint --dry-run`, recuperación tras
   fallo y prohibición de reconciliar `incomplete`.

## Restricciones

- Prohibido ejecutar `--discover-only`, `discover_resumable` o cualquier crawler contra red
  real. Los tests deben inyectar/mocking todas las respuestas HTTP.
- Prohibido crear `data/gateway.db` o `data/cuevana3_checkpoint.json` durante pruebas.
- No acceder a vm-infra, no desplegar y no ejecutar sincronización real.
- No aceptar `pytest -k ...` sin pruebas seleccionadas: debe haber pruebas reales con nombres
  que contengan `checkpoint`, `resume`, `resumable` o `discovery`.
- Mantener el arreglo de aislamiento de `test_panel_api`, que fija `xtream_module.DB_PATH` a
  `temp_db_path` y lo restaura en `finally`.

## ACEPTACION

cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest -q tests/test_catalog_checkpoint.py tests/test_cuevana3.py
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest -q tests -k 'checkpoint or resume or resumable or discovery'
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest -q tests
cd /home/emon/media-integration-gateway && . .venv/bin/activate && python scripts/sync_catalog.py --help
test ! -e /home/emon/media-integration-gateway/data/gateway.db
test ! -e /home/emon/media-integration-gateway/data/cuevana3_checkpoint.json

## PREMISES

- I1 interface — `save_checkpoint`, `load_checkpoint`, `validate_for_reconciliation` y `add_items_deduplicated` existen en el módulo nuevo — `src/services/catalog_checkpoint.py:69`, `src/services/catalog_checkpoint.py:111`, `src/services/catalog_checkpoint.py:149`, `src/services/catalog_checkpoint.py:179`.
- I2 interface — `Cuevana3Adapter.discover_resumable(checkpoint_path, category=None, page_limit=None)` existe y usa el cliente HTTP inyectable del adaptador — `src/adapters/cuevana3.py:250`, `src/adapters/cuevana3.py:339`.
- P1 precedent — el método guarda el checkpoint después de procesar cada página y antes de continuar a la siguiente — `src/adapters/cuevana3.py:405`, `src/adapters/cuevana3.py:417`, `src/adapters/cuevana3.py:429`.
- P2 precedent — `sync_from_checkpoint` carga y valida antes de abrir `AsyncSessionLocal` — `scripts/sync_catalog.py:83`, `scripts/sync_catalog.py:102`.
- L1 literal — la versión actual del formato es `CHECKPOINT_VERSION = 1` — `src/services/catalog_checkpoint.py:24`.
- P3 precedent — el test de panel ahora aísla `DB_PATH` con `temp_db_path` y restauración en `finally` — `tests/test_xtream.py:558`, `tests/test_xtream.py:577`.
- L2 literal — la suite completa local, sin los artefactos ignorados dejados por la corrida anterior, termina con 112 pruebas aprobadas — `.fabrica-verify:1`.
