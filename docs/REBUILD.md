# Rebuild & Restart Guide

This document outlines when and how to rebuild or restart the Ansible SimpleWeb services.

## Quick Reference

| Change Type | Action Required | Command |
|---|---|---|
| **Playbooks / Inventory** | None (Immediate) | N/A |
| **Web Code (`web/*.py`)** | None (Auto-reload) | N/A |
| **Web Templates/Static** | None (Immediate) | N/A |
| **Worker Code (`worker/*.py`)** | Service Restart | `./rebuild.sh --workers` |
| **Dependencies (`requirements.txt`)** | Full Rebuild | `./rebuild.sh --all` |
| **Dockerfiles / System Pkgs** | Full Rebuild | `./rebuild.sh --all` |

## Detailed Processes

### 1. No Action Required
The following files are mounted into the containers and changes are reflected immediately or automatically detected:
- **Playbooks** (`playbooks/*.yml`): Read by Ansible at execution time.
- **Inventory** (`inventory/`): Parsed by the web app and Ansible on demand.
- **Web Frontend** (`web/templates/`, `web/static/`): Served by Flask, reflected on page refresh.
- **Web Backend** (`web/*.py`): The Flask development server (`FLASK_ENV=development`) detects changes and reloads automatically.

### 2. Service Restart
Required when modifying code in long-running processes that do not support auto-reload.

**Target:** Worker Nodes (code only; same image)
- **Files:** `worker/*.py`
- **Reason:** The worker service (`python3 -m worker`) loads code once at startup.
- **Command:**
  ```bash
  docker-compose restart worker-1 worker-2 worker-3
  # OR
  ./rebuild.sh --workers
  ```
- **Note:** This does *not* rebuild the worker image. For `Dockerfile.worker` or `ansible.cfg` changes (e.g. to fix CMDB Collector or ansible-pylibssh warnings), use a full rebuild (see below).

### 3. Container Rebuild
Required when changing system dependencies or build configurations.

**Target:** All Containers
- **Files:** `requirements.txt`, `Dockerfile`, `Dockerfile.worker`
- **Reason:** Python packages and system libraries are installed during the `docker build` phase.
- **Command:**
  ```bash
  docker-compose up -d --build
  # OR
  ./rebuild.sh --all
  ```

## Helper Script
A `rebuild.sh` script is provided in the root directory for convenience:

```bash
./rebuild.sh --help
Usage: ./rebuild.sh [OPTION]

Options:
  --workers    Restart worker nodes (for worker code changes)
  --web        Restart web node (usually not needed due to auto-reload)
  --all        Rebuild and restart all containers (for dependencies/Dockerfiles)
  --help       Show this help message
```

## Single-container (demo) mode

To run only the primary container (no MongoDB, agent, or workers)—e.g. for demo or as the bootstrap entry point—use the single-container compose file:

```bash
docker compose -f docker-compose.single.yml up -d
# Optional: build image first
docker compose -f docker-compose.single.yml up -d --build
```

Validate that the single container is healthy:

```bash
python3 scripts/validate_single_container.py
# Or with custom URL:
python3 scripts/validate_single_container.py --base-url http://localhost:3001
```

The script checks: Web UI reachable, `/api/status`, `/api/config`, and `/api/storage` (expect flatfile by default). See `docs/PHASE_SINGLE_CONTAINER_BOOTSTRAP.md` for multi-container expansion and bootstrap flow.

**Bootstrap / expand:** If config has `features.db_enabled`, `features.agent_enabled`, or `features.workers_enabled` but those services are not yet running, the app runs a deploy playbook on startup (background). You can also run it from the Config panel ("Deploy now") or `POST /api/deployment/run`. The playbook is `playbooks/deploy/expand.yml`; from inside the primary container it requires the Docker socket mounted and (optionally) `DEPLOY_DOCKER_NETWORK` set to the compose network name.

---

## Building the distributable image (Stage 5)

The same image can run as a **single container** (demo or bootstrap entry point) or as the primary in a **multi-container** stack. Build from the repo root:

```bash
docker build -t ansible-simpleweb:latest .
```

To run only the primary (single-container mode):

```bash
docker compose -f docker-compose.single.yml up -d
# Optional: use the tag you built
docker compose -f docker-compose.single.yml up -d --build
```

**Smoke test (built image runs):** After starting the single container, run:

```bash
python3 scripts/validate_single_container.py
# Or: python3 scripts/validate_single_container.py --base-url http://localhost:3001
```

The script verifies: Web UI reachable, `/api/status`, `/api/config`, and storage type. See `docs/PHASE_SINGLE_CONTAINER_BOOTSTRAP.md` for the full test matrix (T1–T9) and bootstrap/expansion flows.

---

## Single-container and expansion workflow

1. **Build the image:** `docker build -t ansible-simpleweb:latest .`
2. **Run single container:** `docker compose -f docker-compose.single.yml up -d`
3. **Provide initial config (optional):** Mount a directory containing `app_config.yaml` into `CONFIG_DIR` (default `/app/config`), or after startup go to **Config** in the UI and set options. To request Primary + DB + Agent from first boot, set in config:
   - `features.db_enabled: true`
   - `features.agent_enabled: true`
   (and optionally `features.workers_enabled: true` and worker count)
4. **Bootstrap:** On startup, if config requests DB/Agent/Workers but they are not yet deployed, the app runs the deploy playbook in the background. You can also click **Deploy now** on the Config page or call `POST /api/deployment/run`.
5. **Add workers later:** Enable workers in Config (or set `features.workers_enabled: true` and `worker_count`), then use **Deploy now**. The playbook adds worker containers; they register with the primary.
6. **Backup / restore:** Use the Config page: **Backup config** / **Restore config** for `app_config.yaml`, and **Download data backup** / **Restore data** for schedules, inventory, and other data (flatfile or MongoDB). See `docs/CONFIGURATION.md` and `docs/API.md`.
