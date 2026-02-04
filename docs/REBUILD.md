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

**Target:** Worker Nodes
- **Files:** `worker/*.py`
- **Reason:** The worker service (`python3 -m worker`) loads code once at startup.
- **Command:**
  ```bash
  docker-compose restart worker-1 worker-2 worker-3
  # OR
  ./rebuild.sh --workers
  ```

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
