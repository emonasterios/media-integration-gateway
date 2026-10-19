<!-- spec:e76d6a63b4b254e61821e58ebee01cae -->
REGLAS OBLIGATORIAS:
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

## PASO 1: Crear script de despliegue ejecutable
- **Archivo**: `scripts/deploy.sh`
- **Acción**:
  1. Crear el archivo `scripts/deploy.sh` con el siguiente contenido exacto:
```bash
#!/usr/bin/env bash
set -euo pipefail

VM_HOST="${VM_HOST:-192.168.122.120}"
VM_PATH="/opt/media-integration-gateway"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TAR_FILE="/tmp/media-gateway-deploy-$(date +%s).tar.gz"

echo "=== Media Gateway Deploy ==="
echo "Repo: $REPO_DIR"
echo "VM:   $VM_HOST:$VM_PATH"

# Crear tar del código
echo "[1/4] Empaquetando código..."
tar czf "$TAR_FILE" \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='.ruff_cache' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache' \
  --exclude='encargo-*.md' \
  --exclude='*.plan.md' \
  -C "$REPO_DIR" .

# Subir a vm-infra
echo "[2/4] Subiendo a vm-infra..."
scp "$TAR_FILE" root@"$VM_HOST":/tmp/media-gateway.tar.gz

# Extraer y rebuild en vm-infra
echo "[3/4] Rebuild en vm-infra..."
ssh root@"$VM_HOST" bash -s <<'REMOTE'
  set -euo pipefail
  cd /opt/media-integration-gateway
  echo "  -> Extrayendo código..."
  tar xzf /tmp/media-gateway.tar.gz -C .
  rm -f /tmp/media-gateway.tar.gz
  echo "  -> Docker compose build..."
  docker compose build --no-cache
  echo "  -> Docker compose up -d..."
  docker compose up -d
  rm -f /tmp/media-gateway.tar.gz
REMOTE

# Verificar health
echo "[4/4] Verificando health..."
sleep 5
HEALTH=$(ssh root@"$VM_HOST" "docker inspect --format='{{.State.Health.Status}}' media-integration-gateway 2>/dev/null || echo 'unknown'")
echo "Health: $HEALTH"

if [ "$HEALTH" = "healthy" ]; then
  echo "✅ Deploy exitoso"
else
  echo "⚠️  Health: $HEALTH — verificar logs con: ssh root@$VM_HOST 'docker logs media-integration-gateway --tail 20'"
fi

# Limpiar
rm -f "$TAR_FILE"
```
  2. Asignar permisos de ejecución al script mediante `chmod +x scripts/deploy.sh`.

## PASO 2: Documentar despliegue e integración mediaflow en README.md
- **Archivo**: `README.md`
- **Acción**:
  1. Leer el archivo `README.md`.
  2. Agregar al final del archivo (después de la sección de desarrollo existente), sin reescribir ni alterar el contenido previo, la sección de Despliegue documentando la arquitectura con mediaflow-proxy y los procedimientos de despliegue:
```markdown
## Despliegue

El gateway corre en vm-infra (192.168.122.120) vía Docker Compose, integrado con mediaflow (mediaflow-proxy) para la resolución de streams protegidos.

### Deploy automático

```bash
./scripts/deploy.sh
```

### Deploy manual

```bash
# Subir código a vm-infra
tar czf /tmp/gateway.tar.gz --exclude='.git' --exclude='.venv' --exclude='__pycache__' .
scp /tmp/gateway.tar.gz root@192.168.122.120:/opt/media-integration-gateway/

# En vm-infra
ssh root@192.168.122.120
cd /opt/media-integration-gateway
tar xzf /tmp/gateway.tar.gz -C .
docker compose build --no-cache
docker compose up -d
```

### Verificar

```bash
# Health check
ssh root@192.168.122.120 "docker inspect --format='{{.State.Health.Status}}' media-integration-gateway"

# Logs
ssh root@192.168.122.120 "docker logs media-integration-gateway --tail 50"

# Probar catálogo
curl -s 'http://192.168.122.120:9193/player_api.php?username=test&password=test&action=get_vod_categories'
```

### Acceso desde IPTV

- **Server URL**: `http://100.78.94.51:9193` (vía Tailscale)
- **Username**: `test`
- **Password**: `test`
```

## PASO 3: Registrar versión 0.4.0 en CHANGELOG.md
- **Archivo**: `CHANGELOG.md`
- **Acción**:
  1. Leer el archivo `CHANGELOG.md`.
  2. Insertar al inicio del historial de cambios (justo debajo del título/encabezado principal del archivo, antes de las versiones anteriores), sin borrar el contenido existente:
```markdown
## [0.4.0] - 2026-10-19

### Fixed
- Deduplicación de catálogo por provider_id (evita películas repetidas en IPTV)
- Proxy de video MP4 con headers Referer/User-Agent (resuelve error 500 en reproducción)

### Added
- Integración mediaflow-proxy para bypass de Cloudflare (curl-cffi)
- Script de deploy automático a vm-infra (`scripts/deploy.sh`)
- Documentación de despliegue en README
```

ACEPTACION
test -x scripts/deploy.sh
grep -q "mediaflow" README.md
grep -q "## Despliegue" README.md
grep -q "## \[0.4.0\] - 2026-10-19" CHANGELOG.md

PREMISES
- `scripts/` directorio existe (tiene accept_cuevana3.py, accept_cache.py)
- `README.md` tiene 241 líneas, no menciona mediaflow ni deploy
- `CHANGELOG.md` existe, última entrada anterior a Fase 3
- vm-infra: 192.168.122.120, código en /opt/media-integration-gateway
- docker-compose.yml usa `build: context: .` (necesita código fuente en vm-infra)
- Tailscale: 100.78.94.51:9193
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
