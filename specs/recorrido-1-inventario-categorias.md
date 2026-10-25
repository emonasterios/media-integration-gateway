# Recorrido 1: inventario completo de películas por categorías

## Objetivo

Construir una lista reanudable, deduplicada y verificablemente completa de las
películas publicadas por Cuevana, recorriendo una por una las categorías que el
sitio anuncia en su menú y sin abrir todavía las fichas individuales.

Esta es únicamente la primera mitad del diseño acordado. El enriquecimiento de
las fichas será otro encargo y no debe implementarse aquí.

## Diseño obligatorio

1. Añadir un flujo explícito de inventario por categorías al CLI de
   `scripts/sync_catalog.py`. Debe poder iniciarse, reanudarse y consultar su
   estado. No cambiar silenciosamente el significado de las opciones heredadas.
2. Obtener las categorías desde enlaces canónicos `/genero/<slug>/` del menú de
   `/peliculas/`. Normalizar y deduplicar por `slug`; conservar nombre y URL.
3. Al comenzar cada categoría, leer su primera página y extraer la última página
   numérica anunciada en la navegación (`a.page-link`). Fijar ese número como el
   límite de esa categoría para la corrida.
4. Recorrer de manera determinista solo las páginas `1..last_page`. No obedecer
   `a.next` más allá del límite anunciado. Nunca solicitar `last_page + 1`.
5. Extraer exclusivamente datos de listado: `provider`, `provider_id`, URL
   canónica de la ficha, título, año y póster. Excluir entradas de series. No
   llamar `get_details`, resolvers de reproducción ni páginas individuales.
6. Deduplicar películas globalmente por `(provider, provider_id)`. Si una
   película aparece en varias categorías, conservar una sola película y todas
   sus categorías mediante una relación muchos-a-muchos.
7. Guardar el inventario y el progreso en un SQLite dedicado y compacto, no en
   un JSON que reescriba miles de películas por cada página. Usar transacciones
   por página. El esquema debe representar al menos:
   - identidad y estado de la corrida;
   - categorías con `slug`, nombre, URL, `last_page`, página siguiente/actual,
     estado y error;
   - películas únicas con los metadatos mínimos del listado;
   - relación película-categoría.
8. Una categoría solo queda `complete` después de confirmar todas las páginas
   `1..last_page`. La corrida solo queda `complete` cuando todas las categorías
   descubiertas están completas. Un error HTTP, una página vacía antes del
   límite o datos inválidos deja la categoría y la corrida `incomplete` y
   reanudables, sin borrar el progreso confirmado.
9. Si una reanudación encuentra una categoría completa, no debe volver a
   descargarla. Si quedó a mitad, debe continuar desde la primera página no
   confirmada.
10. El estado visible debe informar como mínimo: categoría actual, página
    confirmada/última, categorías completas/total, películas únicas y último
    error. Debe obtenerse del SQLite sin acceder a la red.
11. Este recorrido no reconcilia ausencias ni modifica el catálogo público. No
    marca películas/fuentes como `missing`, no borra nada y no lanza el segundo
    recorrido.
12. Mantener funcionando el descubrimiento/checkpoint heredado y sus pruebas.
    Reutilizar parsers pequeños cuando sea razonable, pero no conservar el
    defecto de depender de `a.next` como condición de finalización.

## Interfaz esperada

La nomenclatura exacta puede ajustarse al estilo existente, pero deben existir
equivalentes claros de:

```bash
python scripts/sync_catalog.py --inventory-discover \
  --inventory-db data/cuevana3_inventory.sqlite
python scripts/sync_catalog.py --inventory-status \
  --inventory-db data/cuevana3_inventory.sqlite
```

`--inventory-discover` debe reanudar por defecto si el archivo ya existe. La
salida exitosa solo significa lista completa cuando el estado persistido de la
corrida es `complete`.

## Límites

- No ejecutar el rastreo completo contra el sitio real desde la fábrica.
- No desplegar, reiniciar contenedores ni modificar bases/checkpoints de
  producción.
- No implementar enriquecimiento de detalles, resolvers ni playback.
- No tocar credenciales ni configuración de infraestructura.
- No incorporar ni reformatear cambios ajenos al alcance.
- Añadir pruebas deterministas con HTML simulado; una prueba de parser puede
  usar una fixture real ya versionada, pero la suite no debe depender de red.

## ACEPTACION

```bash
cd /home/emon/media-integration-gateway-inventario-r1 && . /home/emon/media-integration-gateway/.venv/bin/activate && pytest -q tests/test_catalog_inventory.py tests/test_catalog_sync.py tests/test_catalog_checkpoint.py tests/test_cuevana3.py
cd /home/emon/media-integration-gateway-inventario-r1 && . /home/emon/media-integration-gateway/.venv/bin/activate && python scripts/sync_catalog.py --help | grep -q -- '--inventory-discover'
cd /home/emon/media-integration-gateway-inventario-r1 && . /home/emon/media-integration-gateway/.venv/bin/activate && python scripts/sync_catalog.py --help | grep -q -- '--inventory-status'
```

## PRUEBAS REQUERIDAS

Las pruebas nuevas deben demostrar explícitamente que el flujo:

- descubre y deduplica categorías desde el menú;
- fija el máximo anunciado y jamás solicita la página siguiente;
- reanuda una categoría incompleta sin repetir páginas confirmadas;
- omite categorías ya completas;
- deduplica una película repetida y conserva todos sus géneros;
- excluye series;
- mantiene la corrida incompleta ante fallo o página vacía prematura;
- marca `complete` únicamente cuando todas las categorías terminan;
- consulta el estado sin red;
- no llama fichas, enriquecimiento ni reconciliación destructiva.

PREMISES

I El flujo actual inicia en `/peliculas/` o una sola categoría y depende de la paginación de esa ruta — src/adapters/cuevana3.py:287-326
I El flujo actual selecciona `a.next.page-numbers[href]` para decidir la página siguiente — src/adapters/cuevana3.py:499-519
I El parser actual ya distingue series por la URL y películas por defecto — src/adapters/cuevana3.py:472-486
I El checkpoint actual contiene la lista completa de ítems en JSON y se reemplaza atómicamente — src/services/catalog_checkpoint.py:54-102
I El CLI actual ofrece una sola categoría mediante `--category` y un modo `--discover-only` — scripts/sync_catalog.py:469-526
I El HTML vivo verificado el 2026-10-25 anunció 18 enlaces únicos `/genero/` en `/peliculas/`, página final 434 para películas y página final 125 para Acción — https://cuevana3i.cc/peliculas/ y https://cuevana3i.cc/genero/accion/
