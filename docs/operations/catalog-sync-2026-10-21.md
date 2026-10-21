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
