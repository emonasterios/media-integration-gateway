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
