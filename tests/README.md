# Ansible SimpleWeb Test Suite

## Overview

Tests cover unit-level components, feature workflows, and integration with a running cluster. Total: **~515 tests** across unit and feature suites.

## Running Tests

### All Unit & Feature Tests (no cluster required)

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

### Specific Test Module

```bash
python -m unittest tests.test_agent_dashboard_api -v
python -m unittest tests.test_inventory_sync -v
python -m unittest tests.test_cluster_integration -v
```

### Live System Validation (cluster must be running)

```bash
docker-compose up -d
python scripts/validate_system.py
```

## Test Categories

| Category | Files | Description |
|----------|-------|-------------|
| **Agent** | `test_agent_*.py` | Agent service health, dashboard API, log-review trigger, proposals |
| **Worker** | `test_worker*.py`, `test_local_worker.py` | Worker config, API client, content sync, executor, checkin |
| **Cluster** | `test_cluster_*.py`, `test_storage_cluster.py` | Cluster mode, job routing, storage, dashboard |
| **Content** | `test_content_repo.py`, `test_sync_api.py`, `test_inventory_sync.py` | Content repository, sync API, inventory propagation |
| **Jobs** | `test_job_*.py`, `test_job_completion.py` | Job submission, lifecycle, completion, CMDB, dispatch |
| **Logs** | `test_log_upload.py`, `test_batch_log_streaming.py` | Log streaming, upload, WebSocket broadcast |
| **Feature** | `test_feature_*.py` | End-to-end feature workflows (sync, worker checkin, job queue, etc.) |

## Integration Tests

These tests hit live services and are skipped if the cluster is not running:

- **`test_cluster_integration.py`** – Workers, content sync, job execution against `PRIMARY_URL` (default `http://localhost:3001`)
- **`test_inventory_sync.py`** – `TestInventorySyncIntegration` – manifest/reports from running primary

Set `PRIMARY_URL` if the primary runs elsewhere.

## Fixtures & Mocking

- **Agent API tests** (`test_agent_dashboard_api.py`, `test_agent_integration.py`): Mock `requests.get` / `requests.post` to avoid needing the agent service.
- **Web app tests**: Use `flask_socketio` mock and `app.test_client()` to avoid eventlet.
- **Storage tests**: Use `FlatFileStorage` with temp directories.
