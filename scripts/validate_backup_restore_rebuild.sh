#!/usr/bin/env bash
# Validation: backup config (manual + API), remove containers, rebuild to current state, verify.
# Run from project root. Requires: primary container up for backup phase; docker compose for down/up.
# Usage: ./scripts/validate_backup_restore_rebuild.sh [--skip-down] [--primary-url URL]

set -e
PRIMARY_URL="${PRIMARY_URL:-http://localhost:3001}"
SKIP_DOWN=false
for arg in "$@"; do
  case "$arg" in
    --skip-down) SKIP_DOWN=true ;;
    --primary-url=*) PRIMARY_URL="${arg#*=}" ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
STAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="validation_backup_${STAMP}"
MANUAL_DIR="$BACKUP_DIR/manual"
mkdir -p "$MANUAL_DIR"

echo "=== 1. Manual backup (copy relevant config files) ==="
# Relevant files: app_config.yaml (main config); optional: schedules.json, inventory.json for data context
cp -a config/app_config.yaml "$MANUAL_DIR/app_config.yaml"
if [ -f config/schedules.json ]; then cp -a config/schedules.json "$MANUAL_DIR/"; fi
if [ -f config/inventory.json ]; then cp -a config/inventory.json "$MANUAL_DIR/"; fi
echo "  -> $MANUAL_DIR/app_config.yaml (and optional data files)"
ls -la "$MANUAL_DIR"

echo ""
echo "=== 2. API backup (GET /api/config/backup) ==="
API_BACKUP="$BACKUP_DIR/api_config_backup.yaml"
if curl -sf -o "$API_BACKUP" "$PRIMARY_URL/api/config/backup"; then
  echo "  -> $API_BACKUP"
  head -20 "$API_BACKUP"
else
  echo "  FAIL: Primary not reachable at $PRIMARY_URL (is the stack up?)"
  exit 1
fi

echo ""
echo "=== 3. Remove all relevant containers (docker compose down) ==="
if [ "$SKIP_DOWN" = true ]; then
  echo "  SKIPPED (--skip-down)"
else
  docker compose down
  echo "  -> Containers removed (volumes kept)."
fi

echo ""
echo "=== 4. Rebuild to current state (docker compose up -d) ==="
if [ "$SKIP_DOWN" = true ]; then
  echo "  SKIPPED (no down was run)."
else
  docker compose up -d
  echo "  -> Waiting for primary to respond..."
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if curl -sf -o /dev/null "$PRIMARY_URL/api/status"; then break; fi
    sleep 2
  done
  if ! curl -sf -o /dev/null "$PRIMARY_URL/api/status"; then
    echo "  WARN: Primary not yet responding; check: docker compose logs ansible-web"
  fi
fi

echo ""
echo "=== 5. Verify config (GET /api/config vs backup) ==="
# Config is on host volume so after up it should be unchanged; compare to API backup
CURRENT_CFG="$BACKUP_DIR/current_config.json"
if curl -sf -o "$CURRENT_CFG" "$PRIMARY_URL/api/config"; then
  echo "  GET /api/config -> $CURRENT_CFG"
  # Optional: diff key sections (YAML vs JSON so rough check)
  if [ -f "$API_BACKUP" ]; then
    echo "  Manual diff: app_config (backup) vs live config (JSON) - check features/storage match."
    grep -E "backend:|db_enabled|agent_enabled|workers_enabled|worker_count" "$MANUAL_DIR/app_config.yaml" 2>/dev/null || true
    python3 -c "
import json, sys
with open('$CURRENT_CFG') as f:
    d = json.load(f)
c = d.get('config') or {}
f = c.get('features') or {}
print('  Live config features:', {k: f.get(k) for k in ('db_enabled','agent_enabled','workers_enabled','worker_count')})
" 2>/dev/null || true
  fi
else
  echo "  WARN: GET /api/config failed (primary may still be starting)."
fi

echo ""
echo "=== Summary ==="
echo "  Backup dir: $BACKUP_DIR"
echo "  Manual:     $MANUAL_DIR/app_config.yaml"
echo "  API:        $API_BACKUP"
echo "  Containers: down then up (current state restored from compose + host config volume)."
echo "  Next: Use this flow for install doc (new install, restore install, etc.)."
