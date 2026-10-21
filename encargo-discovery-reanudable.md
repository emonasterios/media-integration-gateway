# Encargo: descubrimiento de catálogo reanudable y seguro

## Objetivo

Evitar que un fallo tardío del sitio obligue a reiniciar desde la página 1. El descubrimiento
de Cuevana3 debe guardar progreso durable por página y poder continuar desde la siguiente
página pendiente, sin confundir jamás un checkpoint parcial con un snapshot completo apto
para reconciliación.

## Alcance funcional

1. Crear una fase explícita de descubrimiento durable, invocable desde CLI, que escriba un
   checkpoint dentro de `data/` (ruta configurable para pruebas y operación).
2. Después de cada página válida, persistir atómicamente:
   - versión del formato;
   - proveedor y categoría/ruta inicial;
   - URL o ruta de la próxima página;
   - páginas completadas;
   - elementos descubiertos deduplicados por `(provider, provider_id)` con metadatos del
     listado;
   - estado `incomplete` mientras exista una página pendiente.
3. Si el proceso termina, es interrumpido o agota reintentos, conservar el último checkpoint
   válido. Una nueva ejecución compatible debe reanudar desde `next_page`, sin solicitar de
   nuevo las páginas ya completadas.
4. Cuando desaparezca `next`, escribir atómicamente el estado `complete`. Solo un artefacto
   `complete` puede alimentar reconciliación. Un checkpoint `incomplete`, corrupto,
   incompatible o perteneciente a otra categoría/proveedor debe ser rechazado con error
   explícito y sin escrituras en la BD.
5. Integrar `scripts/sync_catalog.py` con esta fase sin romper su uso actual. Debe existir una
   forma clara de:
   - ejecutar solo descubrimiento/reanudación;
   - mostrar estado del checkpoint;
   - hacer dry-run/reconciliación únicamente desde snapshot completo.
   La interfaz exacta puede ser subcomandos (`discover`, `status`, `reconcile`) o scripts
   separados, pero debe ser inequívoca y estar documentada.
6. Las escrituras del checkpoint deben usar archivo temporal + reemplazo atómico (o SQLite
   transaccional). Nunca sobrescribir el último checkpoint bueno con contenido truncado.
7. Conservar los reintentos y rate limiting existentes. Añadir opciones configurables y
   prudentes si son necesarias para reanudar; no eliminar las protecciones actuales de
   `--limit`, `--dry-run` ni bajas masivas.
8. No implementar aún enriquecimiento por lotes ni la política de dos rastreos `missing`;
   esos serán encargos posteriores.

## Pruebas obligatorias

- Más de 20 páginas: completa el snapshot y queda marcado `complete`.
- Fallo intermedio: queda `incomplete`, conserva exactamente las páginas confirmadas y no
  habilita reconciliación.
- Reanudación: empieza en la página pendiente y no vuelve a pedir páginas anteriores.
- Segundo fallo tras reanudar: el checkpoint anterior sigue legible y consistente.
- Escritura interrumpida/corrupta simulada: no destruye el último checkpoint válido.
- Deduplicación estable por `(provider, provider_id)` a través de varias páginas y de una
  reanudación.
- Checkpoint de otra categoría/proveedor o versión incompatible: rechazo explícito.
- Snapshot incompleto pasado a reconciliación: cero escrituras en BD.
- Compatibilidad: las pruebas existentes de catálogo, Xtream y API siguen pasando.

## Restricciones

- No acceder a producción, no desplegar y no ejecutar el crawler real contra las cientos de
  páginas como parte de la fábrica.
- No guardar HTML completo ni secretos en el checkpoint.
- No usar el título como identidad.
- No permitir que `--force` o una opción equivalente salte la condición `complete`.
- Documentar recuperación operativa, formato/ruta del checkpoint y comandos de ejemplo.

## ACEPTACION

cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest -q tests/test_cuevana3.py
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest -q tests -k 'checkpoint or resume or resumable or discovery'
cd /home/emon/media-integration-gateway && . .venv/bin/activate && python scripts/sync_catalog.py --help

## PREMISES

- I1 interface — `Cuevana3Adapter.get_catalog(category: Optional[str] = None) -> list[MediaItem]` — `src/adapters/cuevana3.py:135`.
- L1 literal — la ruta inicial es `/peliculas/` sin categoría o `/genero/{category}/` con categoría — `src/adapters/cuevana3.py:137`.
- P1 precedent — el rastreo actual acumula elementos en memoria, deduplica por `provider_id` y avanza mediante `a.next.page-numbers[href]`; es el comportamiento que la fase durable debe preservar página a página — `src/adapters/cuevana3.py:138`, `src/adapters/cuevana3.py:205`, `src/adapters/cuevana3.py:227`.
- P2 precedent — cada página conserva tres intentos HTTP y pausa creciente entre reintentos; al agotarlos lanza `CatalogCrawlError` antes de devolver catálogo — `src/adapters/cuevana3.py:152`, `src/adapters/cuevana3.py:170`.
- P3 precedent — la sincronización llama primero a `get_catalog()`, construye el snapshot y solo después abre `AsyncSessionLocal`; separar descubrimiento de reconciliación debe conservar esa barrera — `scripts/sync_catalog.py:35`, `scripts/sync_catalog.py:38`, `scripts/sync_catalog.py:53`.
- L2 literal — la identidad usada por sincronización es `PROVIDER = "cuevana3"` junto con `item.provider_id`, y las fuentes persistidas guardan ese proveedor y el `provider_id` en `url` — `scripts/sync_catalog.py:24`, `scripts/sync_catalog.py:39`, `scripts/sync_catalog.py:97`.
- P4 precedent — `--limit` deshabilita borrados, `--dry-run` hace rollback y la protección de bajas masivas rechaza una proporción superior a 25% salvo autorización explícita; estas protecciones deben mantenerse — `scripts/sync_catalog.py:46`, `scripts/sync_catalog.py:64`, `scripts/sync_catalog.py:147`.
- P5 precedent — el registro operativo constata fallo en página 860, ausencia de snapshot completo y ninguna ejecución real posterior — `docs/operations/catalog-sync-2026-10-21.md:5`, `docs/operations/catalog-sync-2026-10-21.md:10`, `docs/operations/catalog-sync-2026-10-21.md:13`.
- L3 literal — el estado observado documenta 903 registros en `media`; este encargo no autoriza modificar ese estado — `docs/operations/catalog-sync-2026-10-21.md:19`.
- L4 literal — la verificación del repo ejecuta `pytest tests/ -v` — `.fabrica-verify:1`.
- P6 precedent — la aceptación permanente comprueba que las lecturas Xtream con BD configurada salgan de SQLite — `.fabrica-aceptacion:3`.
