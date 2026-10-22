# Encargo: carga incremental segura y terminación fiable del catálogo

## Objetivo

Modificar exclusivamente el flujo de descubrimiento y actualización del catálogo de Cuevana3 para que cada página confirmada haga `upsert` de sus películas en SQLite, sin esperar el final del rastreo, y para que el crawler termine de forma segura cuando el sitio mantenga una paginación artificialmente infinita.

## Alcance permitido

- `src/adapters/cuevana3.py`, únicamente el descubrimiento de catálogo.
- Servicios de checkpoint/persistencia de catálogo bajo `src/services/`.
- `scripts/sync_catalog.py`.
- Pruebas focalizadas del catálogo/checkpoint/sincronización.
- Documentación operativa del catálogo.
- Si hace falta, una migración o restricción de BD limitada a garantizar idempotencia de `(provider, provider_id)`, siempre con migración compatible y pruebas. Preferir resolverlo sin migración si la identidad existente basta.

## Fuera de alcance

- No modificar reproducción, resolvers, extractores de hosts, `mediaflow_bridge`, M3U, Xtream, autenticación ni rutas públicas.
- No acceder a la VM, Docker, red real, proveedor real ni base de producción.
- No ejecutar despliegues ni sincronizaciones reales.
- No editar ni borrar archivos bajo `data/`.
- No limpiar los 797 grupos de fuentes duplicadas ni las 10 fuentes huérfanas ya observadas; ese saneamiento es otra unidad.
- No cargar series: este flujo incremental mantiene el comportamiento actual de sincronización, limitado a `media_type == "movie"`.
- No inferir bajas desde un checkpoint incompleto.

## Comportamiento requerido

1. Después de parsear y validar una página, realizar upsert idempotente de las películas nuevas o modificadas usando `(provider, provider_id)` como identidad estable.
2. Confirmar cada lote por página en una transacción acotada. Una interrupción posterior no debe perder lo ya confirmado.
3. Guardar el checkpoint de forma coherente con la transacción. Diseñar explícitamente el orden y la recuperación para que repetir una página tras una caída sea seguro y no cree duplicados.
4. Durante `status == incomplete`, permitir exclusivamente altas y actualizaciones. Debe ser imposible borrar, retirar, desactivar o limpiar fuentes huérfanas como efecto colateral.
5. Normalizar títulos del listado: si el texto comienza con el mismo año parseado (`2018Aquaman`), persistir `Aquaman`, sin degradar títulos existentes.
6. Detectar terminación artificial mediante una combinación determinista y configurable:
   - huella o conjunto de identidades repetido;
   - páginas consecutivas sin identidades nuevas;
   - límite máximo de páginas como fusible.
7. Una terminación por heurística o fusible NO debe declarar un snapshot apto para bajas. Introducir un estado/razón explícita compatible con checkpoints existentes, o conservar `incomplete` con una razón persistida. Solo un final natural confiable puede habilitar reconciliación de bajas.
8. Reanudar checkpoints existentes versión 1 sin perder elementos ni páginas. Si se cambia el esquema, proporcionar compatibilidad o migración automática probada.
9. Mantener la barrera actual: la reconciliación con bajas exige snapshot completo, proveedor y categoría compatibles.
10. Exponer en CLI y `--status` el progreso incremental, cantidad cargada y razón de detención, sin abrir la BD para una consulta de estado puramente documental salvo que sea imprescindible y esté probado.

## Pruebas obligatorias

- Dos páginas con elementos nuevos producen upserts visibles página por página.
- Repetir una página o reanudar tras una caída no duplica `Media` ni `Source`.
- Un fallo entre persistencia y avance del checkpoint se recupera de forma idempotente.
- Checkpoint incompleto jamás ejecuta bajas ni limpieza de huérfanos.
- Página repetida, varias páginas sin novedades y límite máximo detienen el crawler con razón correcta sin marcar un final natural falso.
- Un enlace siguiente ausente marca final natural y conserva la reconciliación estricta existente.
- Se puede cargar y reanudar un checkpoint v1 previo.
- Los títulos con prefijo de año se normalizan; un año que no coincide no se recorta.
- Las pruebas no crean `data/gateway.db`, checkpoints ni otros artefactos persistentes en el repositorio.
- Toda la suite existente continúa verde.

## ACEPTACION

. .venv/bin/activate && pytest -q tests/test_catalog_checkpoint.py tests/test_catalog_sync.py
. .venv/bin/activate && pytest -q
test ! -e data/gateway.db
git diff --exit-code -- src/api src/services/video_resolver.py src/services/mediaflow_bridge.py

## PREMISES

- `src/adapters/cuevana3.py:251-268` define el descubrimiento reanudable y checkpoint por página.
- `src/adapters/cuevana3.py:325-345` controla el bucle, límite y páginas visitadas solo dentro de una ejecución.
- `src/adapters/cuevana3.py:418-445` deduplica, avanza el checkpoint y confía en el enlace `next` para terminar.
- `scripts/sync_catalog.py:68-109` exige checkpoint completo para reconciliar y deshabilita bajas solo cuando hay `--limit`.
- `scripts/sync_catalog.py:113-189` mezcla upserts, bajas y limpieza de huérfanos en una sola transacción.
- `src/services/catalog_checkpoint.py:45-66` conserva proveedor, categoría, páginas, ítems y estado del checkpoint.
- `src/services/catalog_checkpoint.py:149-175` prohíbe reconciliar snapshots incompletos y valida proveedor/categoría.
- `src/services/catalog_checkpoint.py:179-196` deduplica por `(provider, provider_id)`.
