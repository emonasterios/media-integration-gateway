# Sincronización del catálogo — 2026-10-21

## Estado final: BLOQUEADO

La sincronización real no se ejecutó. El dry-run no completó el rastreo y, por
lo tanto, no produjo un snapshot ni llegó al marcador `SIMULACIÓN (rollback)`.
El único registro de `/app/data/sync-dry-run.log` fue:

```text
Fallo en catálogo página 860 (intento 1/3):
```

Al no existir un snapshot completo, no fue posible calcular de forma fiable
altas, actualizaciones ni bajas. Conforme a la compuerta de seguridad, no se
ejecutó `python scripts/sync_catalog.py` en modo real.

## Estado observado sin modificar producción

- Contenedor: `healthy` y `running`.
- Base SQLite `/app/data/gateway.db`: 903 registros en `media` y 1710 en
  `sources`.
- Fuentes Cuevana3: 1710.
- Grupos duplicados por `(provider, url)` para Cuevana3: 797.
- Fuentes huérfanas: 807.
- Xtream `get_vod_streams`: HTTP 200, JSON válido de tipo lista con 903
  elementos.

Los duplicados y huérfanos son observaciones del estado ya desplegado; durante
esta validación no se alteró la base. Estos resultados también impiden declarar
apta la operación.

## Comandos ejecutados

```bash
ssh root@192.168.122.120 "docker exec media-integration-gateway cat /app/data/sync-dry-run.log"
ssh root@192.168.122.120 "docker inspect --format='health={{.State.Health.Status}} status={{.State.Status}} started={{.State.StartedAt}}' media-integration-gateway"
ssh root@192.168.122.120 "docker exec media-integration-gateway sh -lc 'wc -l -c /app/data/sync-dry-run.log; sed -n \"1,20p\" /app/data/sync-dry-run.log'"
ssh root@192.168.122.120 "docker exec media-integration-gateway python -c '<consultas SQLite de conteos, duplicados y huérfanos>'"
ssh root@192.168.122.120 "curl contra /player_api.php?action=get_vod_streams y validación JSON"
```

No se ejecutaron despliegues, reinicios, cambios de configuración ni comandos
de escritura sobre la base de datos.

## Descubrimiento reanudable mediante checkpoint

El descubrimiento y la reconciliación están separados. El checkpoint es JSON
versión 1 y contiene `provider`, `category`, `initial_path`, `next_page`,
`pages_completed`, `items` y `status`. Se escribe de forma atómica mediante un
temporal adyacente y reemplazo, por lo que un fallo conserva el último archivo
válido. La ruta es configurable con `--checkpoint-path`; el valor por defecto
es `data/cuevana3_checkpoint.json`.

Consultar el progreso sin rastrear ni abrir la base de datos:

```bash
python scripts/sync_catalog.py \
  --checkpoint-path /ruta/segura/cuevana3-checkpoint.json \
  --status
```

Iniciar o reanudar únicamente el descubrimiento:

```bash
python scripts/sync_catalog.py \
  --checkpoint-path /ruta/segura/cuevana3-checkpoint.json \
  --discover-only
```

Si el proceso falla, se vuelve a ejecutar el mismo comando con la misma ruta.
Las páginas incluidas en `pages_completed` no se solicitan nuevamente y el
rastreo continúa desde `next_page`. No se debe borrar ni editar manualmente el
checkpoint durante la recuperación.

Cuando `--status` indique `complete`, validar la reconciliación con rollback:

```bash
python scripts/sync_catalog.py \
  --checkpoint-path /ruta/segura/cuevana3-checkpoint.json \
  --from-checkpoint --dry-run
```

Para checkpoints de una categoría concreta, se debe repetir la misma categoría
en cada operación, por ejemplo `--category accion`. El proveedor y la categoría
se validan antes de abrir la base de datos.

Un checkpoint `incomplete`, corrupto, de versión incompatible, de otro proveedor
o de otra categoría está prohibido para reconciliación. La herramienta aborta
antes de abrir la sesión de base de datos; nunca se debe usar un snapshot parcial
para inferir bajas.
