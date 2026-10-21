# Deploy a vm-infra

## PROBLEMA
El contenedor en vm-infra corre código viejo sin `_load_catalog_from_db`. El código nuevo está commiteado en `main` (`82f5b60`) pero no se desplegó.

## QUÉ HACER
Ejecutar `bash scripts/deploy.sh` desde el directorio del repo.

## PASOS
1. `cd /home/emon/media-integration-gateway`
2. `bash scripts/deploy.sh`
3. Verificar que el health check diga "healthy"
4. Verificar que `get_vod_streams` devuelva películas con `category_id` variados (no todos "1")

## ACEPTACIÓN
- `ssh root@192.168.122.120 "docker inspect --format='{{.State.Health.Status}}' media-integration-gateway"` → "healthy"
- `curl -s "http://100.78.94.51:9193/player_api.php?username=test&password=test&action=get_vod_streams"` → al menos 3 `category_id` distintos en los primeros 20 items
- `curl -s "http://100.78.94.51:9193/player_api.php?username=test&password=test&action=get_vod_categories"` → 19 categorías

## PREMISES
- scripts/deploy.sh:1 — existe y funciona (tar/scp + docker compose en vm-infra)
- VM_HOST=192.168.122.120 — accesible por SSH
- Contenedor: media-integration-gateway — corre en vm-infra
- Código en main: commit 82f5b60 — ya commiteado y pusheado
- BD en contenedor: /app/data/gateway.db — 903 películas con géneros
