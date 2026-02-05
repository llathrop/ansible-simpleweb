# Ansible SimpleWeb Test Suite

## Overview

Tests cover unit-level components, feature workflows, and integration with a running cluster. Total: **~515 tests** across unit and feature suites.

## Running Tests

Tests are **real** (no mocks of the system under test): real Flask app, real storage with temp dirs, real config. Per memory.md §8, do not skip tests—run the full suite using a virtualenv or container when dependencies (e.g. Flask) are required.

### Recommended: full suite via script (creates venv if needed)

```bash
./scripts/run_tests.sh
```

This creates a venv at `.venv` (or `$VENV_DIR`), installs `requirements.txt` and pytest, and runs the full test suite. Use this to confirm all tests pass, including config API, data backup/restore, and deployment API.

### Full suite with existing venv

```bash
# From project root, with venv already active or using .venv:
.venv/bin/python -m pytest tests/ -v
# Or with unittest:
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

### Without venv (subset only)

If you run without installing Flask and other app dependencies, only tests that do not import `web.app` will run (e.g. `test_config_manager.py`, `test_deployment_helper.py`, `test_deployment_single.py`). **Do not rely on this for phase sign-off**; use `./scripts/run_tests.sh` to run the full suite.

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
| **Config** | `test_config_manager.py`, `test_config_api.py` | App config (app_config.yaml) load/save/validate, config API and backup/restore |
| **Data backup/restore** | `test_data_backup_restore.py` | Data backup (zip) and restore API for both flatfile and MongoDB; MongoDB export/import via panel. Requires Flask/venv to run. |
| **Deployment** | `test_deployment_single.py`, `test_deployment_helper.py`, `test_deployment_api.py`, **`test_deployment_matrix.py`** | Single-container compose; deployment delta and run_bootstrap; API tests. **Stage 6 (T1–T9)**: `test_deployment_matrix.py` — integration tests for test matrix (single, Primary+DB, +Agent, +DB+Agent, +Workers, deployment API for bootstrap/expand). Run with primary reachable: `PRIMARY_URL=http://localhost:3001 pytest tests/test_deployment_matrix.py -v`. |

**Validation requirements (memory.md §7, TEST_COVERAGE_AUDIT.md):** Tests must (1) verify **outcomes** where feasible (e.g. after PUT config, GET returns persisted values; after data restore, storage reflects data), not only status codes; (2) include **API-level** validation for new endpoints; (3) include **edge cases and invalid data** (malformed input, empty body, wrong types); (4) plan for **basic web validation** (e.g. Config page returns 200, deployment section present) where appropriate.

## Integration Tests

These tests hit live services and are skipped if the cluster is not running:

- **`test_cluster_integration.py`** – Workers, content sync, job execution against `PRIMARY_URL` (default `http://localhost:3001`)
- **`test_inventory_sync.py`** – `TestInventorySyncIntegration` – manifest/reports from running primary

Set `PRIMARY_URL` if the primary runs elsewhere.

## Test policy (memory.md §8)

- **Real tests, no mocks**: Tests exercise real code paths and real dependencies (real app, real storage with temp dirs, real config). No mocks of the system under test; only minimal harness shims (e.g. flask_socketio for test client) where needed.
- **Do not skip**: If tests need a venv or container, use `./scripts/run_tests.sh` (or a container) and run the full suite; document steps in this README.

## Fixtures and environment

- **Web app tests**: Real Flask app and test client; `CONFIG_DIR` and storage use temp dirs. SocketIO is stubbed so the test client can run without eventlet.
- **Storage**: API tests initialize real `FlatFileStorage` via `get_storage_backend()` with a temp `CONFIG_DIR`.
- **Agent/worker integration**: Some tests mock external HTTP to the agent service when a live cluster is not required; integration tests that need a running cluster are skipped when the cluster is down.
