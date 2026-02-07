# Ansible SimpleWeb — Installation Guide

This guide covers **new installs**, **restore from backup**, and **disaster recovery**. All paths use the same Docker image; choice of single-container (demo/bootstrap) vs full stack depends on how you want to deploy.

**References:** [REBUILD.md](REBUILD.md) (rebuild/restart, single-container mode), [BACKUP_RESTORE_REBUILD_VALIDATION.md](BACKUP_RESTORE_REBUILD_VALIDATION.md) (validated backup/restore flow), [ARCHITECTURE.md](ARCHITECTURE.md) (components and config), [PHASE_SINGLE_CONTAINER_BOOTSTRAP.md](PHASE_SINGLE_CONTAINER_BOOTSTRAP.md) (bootstrap design).

---

## Prerequisites

- **Docker** and **Docker Compose** (v2) installed and running.
- **Git** (to clone the repo) or a copy of the project tree.
- For **bootstrap/expansion** (single primary then "Deploy now" to add DB/agent/workers): the primary container must have access to the **Docker socket** so it can run `docker run` (e.g. mount `/var/run/docker.sock`). The full-stack `docker-compose.yml` does not mount it by default; add it if you use single-container + Deploy now. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) § Deployment.

---

## 1. New Install

Two options: run the **full stack** (recommended for most users) or run the **single container** and expand later.

### 1.1 Full stack (recommended)

Use this when you want the primary, MongoDB, agent, and workers (or a subset) from the start. Config is read from `config/app_config.yaml` if present; otherwise defaults apply. The compose file defines all services.

1. **Clone and enter the project:**
   ```bash
   git clone <repo-url> ansible-simpleweb
   cd ansible-simpleweb
   ```

2. **Create config (optional).** To drive features from a file, create `config/app_config.yaml`. Example (Primary + DB + Agent + 2 workers):
   ```yaml
   storage:
     backend: mongodb
     mongodb:
       host: mongodb
       port: 27017
       database: ansible_simpleweb
   features:
     db_enabled: true
     agent_enabled: true
     workers_enabled: true
     worker_count: 2
   ```
   If you do not create this file, the stack still starts; the app uses defaults (see [CONFIGURATION.md](CONFIGURATION.md)) or environment variables set in `docker-compose.yml`.

3. **Build and start:**
   ```bash
   docker compose up -d --build
   ```

4. **Verify:** Open http://localhost:3001. Check health: `curl -s http://localhost:3001/api/status`. If agent is enabled: `curl -s http://localhost:5001/health`.

5. **Optional:** Use the **Config** page to change settings, then **Deploy now** if you added DB/agent/workers in config after starting (only needed if those services were not already defined in the compose file you used).

### 1.2 Single container then expand (demo or minimal first step)

Use this for a minimal first run (primary only, flatfile storage) or when you want to add DB/agent/workers later via the Config panel.

1. **Clone and enter the project** (same as above).

2. **Optional: initial config.** Create `config/app_config.yaml` with the features you want after expansion, e.g.:
   ```yaml
   features:
     db_enabled: true
     agent_enabled: true
     workers_enabled: false
   ```
   If you omit this, you can still add config later via the UI and then run Deploy now.

3. **Build and start only the primary:**
   ```bash
   docker build -t ansible-simpleweb:latest .
   docker compose -f docker-compose.single.yml up -d
   ```

4. **Validate:** `python3 scripts/validate_single_container.py` (or `--base-url http://localhost:3001`).

5. **Add config if needed:** Open http://localhost:3001, go to **Config**, set options (e.g. enable DB and Agent), save.

6. **Expand (Deploy now):** On the Config page click **Deploy now**, or call `POST http://localhost:3001/api/deployment/run`. This runs the deploy playbook and creates MongoDB, agent+ollama, and optionally worker containers.  
   **Requirement:** The primary container must be able to run `docker run` (Docker socket mounted). If you use `docker-compose.single.yml` as shipped, add this under the `ansible-web` service `volumes:` section so Deploy now can create containers:
   ```yaml
   - /var/run/docker.sock:/var/run/docker.sock
   ```
   Otherwise, use the full `docker-compose.yml` and rely on existing services.

7. **Verify:** `GET http://localhost:3001/api/deployment/status` shows desired vs current; after deploy, DB and agent (and workers if enabled) should be reachable. If you enabled DB or agent and the primary was already running, restart it so it picks up the new storage and agent URL: `docker compose -f docker-compose.single.yml restart ansible-web`.

---

## 2. Restore Install

Use this when you have a **config backup** (and optionally a **data backup**) from a previous install and want to restore on the same or a new host.

### 2.1 Restore on same host (containers were removed)

If you ran `docker compose down` and want to bring the stack back with the same config and data:

1. **Ensure backups are available.** You need at least a config backup (`app_config.yaml` or the YAML from `GET /api/config/backup`). For schedules and inventory state, use a data backup (Config page **Download data backup** or `GET /api/data/backup`) if you had MongoDB or flatfile data you care about.

2. **Restore config on disk (if needed):** Copy your saved `app_config.yaml` into the project directory as `config/app_config.yaml`.

3. **Start the stack:**
   ```bash
   docker compose up -d
   ```
   The primary reads `config/app_config.yaml` at startup. No API restore is needed if the file is already in place.

4. **Restore data (if needed):** If you use MongoDB and have an application-level data backup (zip), open the Config page and use **Restore data**, or use `POST /api/data/restore` with the backup zip. For flatfile, restoring the zip replaces JSON files in the config dir.

5. **Verify:** `GET /api/config` and `GET /api/status`; run a quick playbook or check schedules if you restored data.

### 2.2 Restore on a new host (or after clone)

When the project directory is fresh (e.g. new clone or copy) and you have only backup files:

1. **Clone or copy the project** to the new host and `cd` into it.

2. **Restore config:**
   - **Option A (file):** Copy your config backup file to `config/app_config.yaml`.
   - **Option B (after starting primary):** Start the primary only: `docker compose -f docker-compose.single.yml up -d`. Then upload or paste the backup YAML on the Config page (**Restore config**), or call `POST /api/config/restore` with `Content-Type: application/x-yaml` and body = your backup YAML.

3. **Start the rest of the stack:**
   - **Full stack:** If you restored config that requests DB/agent/workers, stop the single-container if it is running (`docker compose -f docker-compose.single.yml down`), then run `docker compose up -d` so all services start. Config on disk is already set.
   - **Single then expand:** If you keep the single-container running, click **Deploy now** (or `POST /api/deployment/run`) so the deploy playbook creates the missing services. Ensure Docker socket is mounted (see §1.2 step 6) so Deploy now can succeed.

4. **Restore data (optional):** Use Config page **Restore data** or `POST /api/data/restore` with your data backup zip.

5. **Verify:** Same as 2.1.

---

## 3. Disaster Recovery

### 3.1 Backup strategy

- **Config:** Regularly back up `app_config.yaml` (manual copy or `GET /api/config/backup`). Store copies off the host.
- **Data:** Use **Download data backup** on the Config page (or `GET /api/data/backup`) for schedules, inventory, and related state. With MongoDB, you can also use `mongodump`; see [CONFIGURATION.md](CONFIGURATION.md).
- **Reproducibility:** Keep playbooks, inventory, and config in version control where possible. Backups and validation output dirs are gitignored (`validation_backup*/`, `*_backup_*.yaml`).

### 3.2 Recover after loss

1. **Obtain the codebase** (clone or copy from backup).
2. **Restore config** to `config/app_config.yaml` (or via API after starting primary).
3. **Start stack:** `docker compose up -d` (or single-container then **Deploy now** if you use that model).
4. **Restore data** from your application data backup (zip) via Config page or `POST /api/data/restore` if needed.
5. **Verify** health and run a smoke test (e.g. run a playbook, check schedules).

---

## 4. Verification and Troubleshooting

- **Primary health:** `curl -s http://localhost:3001/api/status`
- **Config:** `curl -s http://localhost:3001/api/config` (check `config` and `config_file_exists`)
- **Deployment status:** `curl -s http://localhost:3001/api/deployment/status` (desired vs current, deploy_db/deploy_agent/deploy_workers)
- **Agent (when enabled):** `curl -s http://localhost:5001/health`
- **Validation script (full backup/restore/rebuild):** `./scripts/validate_backup_restore_rebuild.sh` (from project root; primary must be up for backup steps). Optional: `--skip-down`, `--primary-url=URL`.

If **Deploy now** fails, ensure the primary can run Docker (socket mounted) and that the deploy playbook exists at `playbooks/deploy/expand.yml`. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) § Deployment. For agent and log review issues, see [ARCHITECTURE.md](ARCHITECTURE.md) § Logs and debugging.
