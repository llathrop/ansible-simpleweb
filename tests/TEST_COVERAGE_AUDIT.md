# Test Coverage Audit (Phase: Single-Container Bootstrap)

This document answers whether testing covers: (1) unit tests for all new code, (2) validation via API, (3) plan including basic web validation, (4) outcome verification (did the action actually do what it should), (5) edge cases and invalid data.

## 1. Unit test of all code added to date

| Component | Unit tests | Gaps |
|-----------|------------|------|
| **config_manager** | test_config_manager.py: load, validate, save, get_effective_*, config_file_exists | get_config_path untested; load with malformed YAML / wrong types (edge) not all covered |
| **Config API** (app.py) | test_config_api.py: GET, PUT, backup, restore | Deployment API (GET/POST /api/deployment/*) had no tests; PUT/restore don't verify outcome |
| **Data backup/restore API** | test_data_backup_restore.py: status codes, zip content-type | No verification that backup zip contains expected entries; no verification that restore writes files; no invalid zip |
| **deployment.py** | test_deployment_helper.py: delta logic, run_bootstrap empty/missing playbook | get_desired_services, get_current_services not tested in isolation; no API tests; edge cases (None storage, missing keys) partial |
| **Playbook expand.yml** | None | Playbook not unit tested (Ansible playbook; could add molecule or run with mock) |

**Answer:** No. Some new code (get_config_path, deployment API, outcome checks, edge/invalid) was not fully covered. This audit drives the added tests below.

## 2. Validation testing via API

- **Config API:** test_config_api.py exercises GET/PUT /api/config, backup, restore (status and basic shape). No deployment API tests.
- **Data API:** test_data_backup_restore.py exercises GET/POST data backup/restore (status, content-type). No assertion on response body content or side effects.
- **Deployment API:** No tests for GET /api/deployment/status or POST /api/deployment/run.

**Answer:** Partially. Config and data APIs have API-level tests; deployment API did not. Validation should also assert on outcomes (see 4).

## 3. Plan for validation including basic web functions

- memory.md §7: "Tests must verify the feature works" and "unit and validation tests" per stage.
- PHASE_SINGLE_CONTAINER_BOOTSTRAP.md: Each stage mentions "Tests" but does not explicitly require "outcome verification" or "basic validation of web functions" (e.g. Config page loads, deployment section shows status).

**Answer:** The plan required tests per stage but did not explicitly require (a) outcome verification or (b) basic web UI validation. We add that to the plan and tests/README below.

## 4. Reviewing results to ensure actions did what they were supposed to do

- **Config:** test_put_config_accepts_valid_partial only checks status and data.ok; it does not GET config again and assert the stored value. test_config_restore_accepts_yaml_body does not verify the file was written or content.
- **Data backup:** We assert zip is returned but do not assert the zip contains e.g. schedules.json or expected keys.
- **Data restore:** We do not test that after restore the storage actually contains the restored data (e.g. file on disk or MongoDB doc).
- **Deployment:** run_bootstrap is tested for empty delta and missing playbook; we don't verify playbook execution outcome when playbook exists (that would be integration).

**Answer:** No. Several tests only check that an action was "reported" correct (200, ok) without verifying the actual outcome. Added tests below add outcome verification where feasible in unit/API tests.

## 5. Edge cases and invalid data

- **config_manager:** We test invalid backend, invalid cluster mode. Missing: non-dict input to validate_config, malformed YAML in file, port as string, empty config file.
- **Config API:** We test invalid backend (400), empty restore (400). Missing: PUT with non-JSON, non-dict body; restore with invalid YAML.
- **Data API:** Missing: restore with non-zip file, zip with path traversal attempt, empty zip.
- **Deployment:** Missing: get_deployment_delta with None storage_backend; desired with missing keys; get_current_services when requests fails.

**Answer:** Partially. Some invalid/edge cases are covered; many are not. Added tests below add a set of edge and invalid-data cases.

---

## Actions taken (after this audit)

- **Plan/README:** Require that validation tests verify outcomes (not just status) and include edge cases and invalid data; include at least API-level (and where appropriate basic web) validation. Updated `tests/README.md` and `docs/PHASE_SINGLE_CONTAINER_BOOTSTRAP.md`.
- **Config manager:** Added tests for get_config_path; validate non-dict and mongodb port not int; load with malformed YAML returns defaults; save then load round-trip (outcome).
- **Config API:** Added PUT then GET persisted (outcome); restore then GET reflects content (outcome); PUT with non-dict returns 400. Added basic web: GET /config returns 200.
- **Data backup/restore:** Added flatfile backup zip contains expected filenames (outcome); flatfile restore writes files (outcome); invalid zip returns 400/500.
- **Deployment:** Added unit tests for get_desired_services structure, get_current_services with None storage (mocked socket/requests), delta with missing keys. Added `test_deployment_api.py`: GET/POST deployment status and run, exception returns 500.
- **get_desired_services with real config file:** Covered indirectly by config_manager load/merge tests and deployment API tests (mocked delta). Helper test verifies return structure and defaults.
