# Sincronización incremental del catálogo y checkpoints

## Arquitectura de carga incremental

La sincronización del catálogo se realiza página por página con **upsert atómico
por página**. Cada página se procesa como una unidad aislada: primero se
obtienen los ítems, luego se persisten sus películas y fuentes, y finalmente se
avanza el checkpoint de esa página. Si una ejecución se interrumpe, las páginas
ya confirmadas permanecen registradas y la reanudación continúa desde el último
punto seguro.

Este diseño evita mezclar descubrimiento, persistencia y reconciliación global en
la misma decisión. La lectura puede detenerse y reanudarse sin volver a recorrer
páginas ya confirmadas, y sin dejar la base en un estado ambiguo entre “avance
parcial” y “avance final”.

## Heurísticas de parada deterministas

El crawler no depende solo del enlace `next`. Para evitar bucles o rastreos
infinitos, la terminación se decide con heurísticas explícitas:

- `repeated_page`: la página actual ya fue visitada en la ejecución.
- `no_new_items`: la página no aporta ítems nuevos respecto del checkpoint o del
  estado ya confirmado.
- `max_pages`: se alcanzó el límite configurado de páginas para la ejecución.
- `natural_end`: el enlace `next` ya no existe y el rastreo terminó de forma
  natural.

Estas señales se usan para distinguir un cierre real de un stop artificial o de
una caída a mitad de rastreo. La diferencia es crítica: solo `natural_end`
indica que el snapshot quedó completo.

## Política de protección contra bajas involuntarias

La reconciliación con eliminación de huérfanos solo se permite cuando el
checkpoint termina con `natural_end`. Esa restricción existe para evitar que un
snapshot parcial borre o desactive películas y fuentes que simplemente no fueron
incluidas todavía en un lote incompleto.

En particular:

- `repeated_page`, `no_new_items` y `max_pages` significan que la ejecución no
  terminó como un snapshot completo.
- Un checkpoint que registre cualquiera de esas paradas no debe usarse para
  calcular bajas.
- Si la sincronización se corta antes del cierre natural, solo se conservan los
  upserts ya confirmados; no se ejecuta la limpieza de huérfanos.

En otras palabras: **solo `natural_end` autoriza la reconciliación destructiva**.
Todo lo demás se trata como incompleto y se protege contra eliminaciones
accidentales.

## Comandos de CLI

Consultar el estado del checkpoint sin abrir la base de datos:

```bash
python scripts/sync_catalog.py \
  --checkpoint-path /ruta/segura/cuevana3-checkpoint.json \
  --status
```

Ejecutar solo el descubrimiento incremental:

```bash
python scripts/sync_catalog.py \
  --checkpoint-path /ruta/segura/cuevana3-checkpoint.json \
  --discover-only
```

Reconciliar desde un checkpoint completo:

```bash
python scripts/sync_catalog.py \
  --checkpoint-path /ruta/segura/cuevana3-checkpoint.json \
  --from-checkpoint
```

Para validar sin aplicar cambios:

```bash
python scripts/sync_catalog.py \
  --checkpoint-path /ruta/segura/cuevana3-checkpoint.json \
  --from-checkpoint --dry-run
```

## Reanudación transparente desde checkpoints v1 y v2

La reanudación debe ser transparente para checkpoints previos, incluso si fueron
escritos con formatos distintos:

- **v1**: conserva proveedor, categoría, página inicial, siguiente página,
  páginas completadas, ítems y estado.
- **v2**: mantiene el mismo contrato lógico y añade la distinción estricta entre
  terminación natural e interrupción artificial.

Al reanudar:

1. Se carga el checkpoint existente desde la ruta configurada.
2. Se valida proveedor y categoría antes de abrir la base.
3. Se continúa desde `next_page` sin repetir páginas ya confirmadas.
4. Si el checkpoint fue cerrado con `natural_end`, se permite la reconciliación.
5. Si el checkpoint quedó incompleto o sin cierre natural, solo se reanuda el
   descubrimiento; no se borran huérfanos.

Esto permite retomar un rastreo interrumpido sin perder progreso ni confundir un
snapshot parcial con un catálogo completo.
