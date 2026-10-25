# Recorrido 2: importar el inventario validado al catálogo operativo

## Objetivo

Transferir de forma segura, idempotente y verificable el inventario completo del
recorrido 1 al SQLite operativo del gateway, sin volver a rastrear la web, sin
abrir fichas individuales y sin borrar el único catálogo público existente.

## Diseño obligatorio

1. Añadir al CLI `scripts/sync_catalog.py` una acción explícita
   `--inventory-import`, con origen `--inventory-db` y destino obligatorio
   `--catalog-db`. No usar implícitamente la base configurada por el proceso.
2. Rechazar la importación si la corrida más reciente del inventario no está
   `complete`, si alguna categoría no está completa o si
   `confirmed_page != last_page`.
3. Importar cada fila de `movies` como `media_type='movie'`. Usar como identidad
   estable la fuente única `(provider, provider_id)`, representada en el catálogo
   por `sources(provider, url=provider_id)`; no fusionar por título ni por año.
4. Conservar `title`, `year`, `poster_url`, URL canónica de ficha en
   `sources.page_url`, y las categorías asociadas como JSON determinista en
   `media.genres`, usando el nombre visible de `categories`, no el slug.
5. Las fuentes importadas existen en el listado verificado: guardar
   `catalog_presence='present'`, `last_seen_at` con hora UTC, limpiar
   `missing_since` y poner `consecutive_misses=0`. No resolver reproducción.
6. Si la fuente ya existe, actualizar su `media` y metadatos sin crear otra fila.
   Si no existe, crear `media` y `source`. Una segunda ejecución debe producir
   cero inserciones y el mismo número de filas.
7. Toda la importación debe ser una transacción: ante cualquier error no puede
   quedar una carga parcial. `--dry-run` ejecuta las mismas validaciones y
   escrituras, informa el resumen y revierte todo.
8. No borrar ni marcar `missing` ninguna fila existente. No modificar favoritos,
   historial ni corridas de sincronización existentes.
9. Imprimir un resumen inequívoco: inventario leído, insertados, actualizados,
   sin cambios, relaciones de categorías leídas y estado `committed` o
   `dry-run/rolled-back`.
10. El importador debe funcionar sobre una copia aislada en pruebas. La fábrica
    no debe modificar `/home/emon/media-integration-gateway/media_gateway.db` ni
    ejecutar la importación real.

## Alcance de identidad

El recorrido 1 define unicidad técnica por `(provider, provider_id)`. Los 19
pares que comparten título y año tienen pósteres y combinaciones de categorías
distintos; no deben eliminarse automáticamente. Este recorrido importa las
19,282 identidades del proveedor y no afirma que sean 19,282 obras semánticas.

## ACEPTACION

```bash
cd /home/emon/media-integration-gateway-inventario-r2 && . /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_catalog_inventory_import.py tests/test_catalog_inventory.py
cd /home/emon/media-integration-gateway-inventario-r2 && . /home/emon/media-integration-gateway/.venv/bin/activate && python scripts/sync_catalog.py --help | grep -q -- '--inventory-import'
```

## PRUEBAS REQUERIDAS

- rechaza inventario incompleto y discrepancias de páginas;
- importa película, URL canónica y categorías visibles;
- conserva una película presente en varias categorías sin duplicarla;
- preserva filas preexistentes ajenas;
- actualiza una fuente existente sin duplicarla;
- segunda ejecución idempotente;
- `--dry-run` deja el destino byte/lógicamente sin cambios;
- un fallo intermedio revierte la transacción completa;
- no llama red, detalles ni resolvers.

PREMISES

I El inventario dedicado usa `movies` con clave primaria `(provider, provider_id)` y `movie_categories` con la misma identidad más `category_slug` — src/services/catalog_inventory.py:44-67
I El recorrido 1 exige deduplicar por `(provider, provider_id)` y no modificar el catálogo público — specs/recorrido-1-inventario-categorias.md:24-31,52-53
I El catálogo operativo representa la identidad de proveedor mediante la restricción única `(provider, url)` en `sources` — src/db/models.py:30-38
I El catálogo operativo almacena géneros como texto JSON dentro de `media.genres` — src/db/models.py:12-24
I Las lecturas públicas solo publican fuentes `catalog_presence='present'` — src/api/xtream.py:33-39
I La SQLite real validada el 2026-10-25 contiene 18/18 categorías completas, 44,271 relaciones y 19,282 filas únicas por provider_id/URL — data/cuevana3_inventory.sqlite (validación operativa externa; no versionar la base)
