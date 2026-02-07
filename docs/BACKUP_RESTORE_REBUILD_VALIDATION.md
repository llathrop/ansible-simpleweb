# Backup, Restore, and Rebuild Process (Validated)

This document summarizes the **validated** process for backing up config, removing containers, and rebuilding to current state. It is the basis for install and restore guides (new install, restore install, etc.).

References: `docs/ARCHITECTURE.md` §7, `docs/PHASE_SINGLE_CONTAINER_BOOTSTRAP.md`, `memory.md` § Single-container bootstrap.

## Validated Flow (Summary)

1. **Backup config** (two methods: manual file copy and API).
2. **Remove all relevant containers** (`docker compose down`; volumes kept).
3. **Rebuild to current state** (`docker compose up -d`; config and data on host volumes persist).
4. **Verify** (GET `/api/config` matches backup; deployment status as expected).

Validation script: `scripts/validate_backup_restore_rebuild.sh`. Run from project root with the stack up; it performs all steps and writes backups to `validation_backup_<timestamp>/`.

---

## 1. What Gets Backed Up

### Config (app_config.yaml)

- **Location:** `config/app_config.yaml` (host path; in container at `/app/config`).
- **Contents:** `storage`, `agent`, `cluster`, `features` (db_enabled, agent_enabled, workers_enabled, worker_count), `deployment`.
- **Manual backup:** Copy `config/app_config.yaml` (and optionally `config/schedules.json`, `config/inventory.json` for data context) to a safe directory.
- **API backup:** `GET /api/config/backup` returns a YAML file (current merged config). Save the response body as e.g. `app_config_backup_<timestamp>.yaml`.

### Data (separate from config)

- **Schedules, inventory state, etc.:** Stored in MongoDB (when `storage.backend: mongodb`) or in flatfile under the config dir. Use the Config page **Download data backup** / **Restore data** or the data backup/restore API for schedules and inventory; see `docs/API.md` and `docs/CONFIGURATION.md`.

---

## 2. Backup Steps (Detailed)

### 2.1 Manual backup

```bash
# From project root
BACKUP_DIR=my_backup_$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"
cp config/app_config.yaml "$BACKUP_DIR/"
# Optional: data files
cp config/schedules.json config/inventory.json "$BACKUP_DIR/" 2>/dev/null || true
```

### 2.2 API backup

Primary must be running (e.g. `docker compose up -d`).

```bash
curl -o app_config_backup.yaml "http://localhost:3001/api/config/backup"
```

Or use the Config page: **Backup config** to download the YAML file.

---

## 3. Remove Containers and Rebuild

### 3.1 Remove all relevant containers

```bash
docker compose down
```

- Stops and removes: ansible-web, mongodb, agent-service, ollama, worker-1, worker-2, worker-3 (and network).
- **Volumes are kept** by default (mongodb_data, agent_data, ollama_data).
- **Host-mounted paths** (config, logs, playbooks, inventory) are unchanged.

### 3.2 Rebuild to current state (full stack)

```bash
docker compose up -d
```

- Recreates the same services; config at `./config` is read again by the primary.
- No need to restore config if you did not delete or change `config/app_config.yaml` on the host.

### 3.3 Alternative: Single-container then expand

If you want to simulate a fresh install and then restore:

1. Start only the primary (single-container):  
   `docker compose -f docker-compose.single.yml up -d`
2. Restore config via API:  
   `POST /api/config/restore` with body = YAML content of your backup (or use Config page **Restore config**).
3. Trigger deployment for missing services: Config page **Deploy now** or `POST /api/deployment/run`.  
   The deploy playbook (`playbooks/deploy/expand.yml`) will add DB, agent+ollama, and workers as per config.

---

## 4. Restore Config (When Needed)

If config was lost or you are restoring on a new host:

- **Via API:**  
  `POST /api/config/restore` with `Content-Type: application/x-yaml` and body = full YAML (or multipart file upload).
- **Via UI:** Config page, **Restore config**, choose the backup YAML file.
- **Via file:** Copy the backup file to `config/app_config.yaml` on the host, then restart the primary if it was already running so it reloads config.

---

## 5. Verification

- **Config:** `GET /api/config` and compare `config` (especially `features`, `storage`) to your backup.
- **Deployment status:** `GET /api/deployment/status` shows desired vs current (DB, agent, workers) and whether anything needs to be deployed.
- **Health:** `GET /api/status`; agent: `GET http://localhost:5001/health` (when agent is up).

---

## 6. Use for Install Documents

This process can be used to define:

- **New install:** Start from single container (or full compose), set or restore config, run deploy if needed, verify. See `docs/REBUILD.md` § Single-container and expansion workflow.
- **Restore install:** Restore config (and optionally data) from backup, then `docker compose up -d` or single-container + restore + Deploy now; verify.
- **Disaster recovery:** Backup config (and data) regularly; to recover, re-clone or copy repo, restore config (and data), run `docker compose up -d` or bootstrap flow, verify.

Validation script: `./scripts/validate_backup_restore_rebuild.sh` (optional `--skip-down` to skip down/up, `--primary-url=URL`). Ensures primary is up for backup steps; then performs down, up, and verification.
