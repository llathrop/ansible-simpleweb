# Agentic Overview & Automation

**For the single architecture doc (whole environment, components, workflows, logs and debugging), see [ARCHITECTURE.md](ARCHITECTURE.md).** This document focuses on agent objectives, phased plan, and security.

## 1. Project Objectives
The goal is to integrate an autonomous AI agent into the **Ansible SimpleWeb** cluster. This agent will act as an intelligent operator, monitoring the system, reviewing outputs, and assisting with playbook development.

### Core Responsibilities
1.  **Log Review & Verification**: Analyze execution logs to verify expected states and identify anomalies that standard exit codes might miss.
2.  **Playbook Assistant**: Generate and review playbooks based on user instructions, offering enhancement suggestions and security improvements.
3.  **System Monitoring**: Validate that scheduled jobs ran successfully and monitor the overall health of the cluster.
4.  **Insight Generation**: Review configuration outputs (e.g., RouterOS configs, server facts) to flag security risks, update needs, or resource constraints.
5.  **Continuous Improvement**: Maintain a prioritized list of suggested enhancements for the codebase.

## 2. Architecture

### New Component: `agent-service`
A new containerized service will be added to the Docker Compose stack.

*   **Runtime**: Python-based service using `ChromaDB` for local vector storage.
*   **Access**:
    *   **API**: Communicates with `ansible-web` via REST API.
    *   **Storage**: Read-only access to `logs/` and `playbooks/` volumes.
    *   **Model**: Access to a local LLM inference endpoint via OpenAI-compatible API.

### Integration Strategy
1.  **Interface**: A new "Agent Proposals" section will be added to the `ansible-web` UI to review and approve agent-generated playbooks.
2.  **Communication**: 
    - The agent speaks to `ansible-web` via HTTP.
    - New endpoints `/api/agent/proposals` and `/api/agent/alerts` will be added to `ansible-web`.
3.  **Triggering**:
    - **Event-Driven (Priority)**: `ansible-web` will notify the agent immediately when a job completes.
    - **Polling (Fallback)**: The agent will periodically check for missed logs or scheduled tasks.

### LLM & RAG Strategy
*   **Model Selection**: We recommend **Qwen2.5-Coder-7B-Instruct** or **Llama-3-8B-Instruct**. These models offer a strong balance of coding capability, reasoning, and efficiency for local deployment.
*   **Inference**: All services run in Docker; there are **no local/host LLM processes**. The stack uses the **`ollama` container** (OpenAI-compatible API). Do not run Ollama on the host; the agent connects to `http://ollama:11434/v1`.
*   **RAG (Retrieval-Augmented Generation)**:
    *   The agent will maintain a vector index of:
        *   Existing Playbooks
        *   Documentation (`docs/*.md`)
        *   System Context (`memory.md`)
    *   This allows the agent to write code that adheres to project conventions and understands the specific environment.

## 3. Phased Implementation Plan

Each phase must include:
1.  **Implementation**: Core code and logic.
2.  **Testing**: Unit and validation tests in `tests/` (verifying functionality without excessive mocking).
3.  **Validation**: Manual or automated verification of the running feature.

### Phase 1: Foundation & Infrastructure
*   [x] Create `agent-service` container in `docker-compose.yml`.
*   [x] Set up the LLM inference backend.
*   [x] Implement basic `AgentClient`.
*   [x] Establish the RAG pipeline (Infrastructure ready).
*   [x] **Backfill Tests**: Verify agent service health and API connectivity.

### Phase 2: Log Reviewer (Active)
*   [x] Implement a log monitoring loop (Event-driven implemented).
*   [x] Add event hooks in `ansible-web` to trigger the agent.
*   [x] Create `prompts.yaml`.
*   [x] Implement LLM client (`agent/llm_client.py`).
*   [x] Implement Log Review logic.
*   [x] Store reviews in `agent_data`.
*   [x] **Backfill Tests**: Verify log review trigger, LLM interaction, and result storage.

### Phase 3: Playbook Assistant (Active)
*   [x] **Infrastructure**: Install `chromadb` and create `agent/rag.py` for vector store management.
*   [x] **Ingestion**: Implement `POST /rag/ingest` to index playbooks and docs.
*   [x] **Generation**: Implement `POST /agent/generate` to create playbooks using RAG + LLM.
*   [x] **Prompts**: Add `playbook_generation` prompt to `agent/prompts.yaml`.
*   [x] **Testing**: Add unit tests for generation and RAG integration.

### Phase 4: Security & Guardrails (Completed)
*   [x] **System Prompting**: Define strict system prompts in `agent/prompts.yaml`.
*   [x] **Policy Engine**: Created `agent/security.py` and `agent/security_policy.yaml`.
*   [x] **Allowlist Strategy**: Refactored guardrails to use a strict allowlist of verbs/actions.
*   [x] **Validation**: Verified container read-only mounts in `docker-compose.yml`.
*   [x] **Constraint Testing**: Updated unit tests to verify the allowlist logic.

### Phase 5: System Monitor & Insights (Completed)
*   [x] **Schedule Monitor**: Implemented `/agent/schedule-monitor` to verify scheduled job execution.
*   [x] **Config Analyzer**: Implemented `/agent/analyze-config` for security analysis of device configurations.
*   [x] **Testing**: Added unit tests in `tests/test_phase5_monitoring.py`.
*   [x] **Validation**: Verified with `scripts/validate_system.py`.

### Phase 6: GUI Integration (Completed)
*   [x] **Dashboard**: Created `web/templates/agent.html` displaying agent health, recent reviews, reports, and pending proposals.
*   [x] **Navigation**: Updated all main templates (`index.html`, `playbooks.html`, `logs.html`, `schedules.html`, `inventory.html`, `storage.html`, `cmdb.html`) to include the "Agent" link.
*   [x] **API Proxy**: Added routes in `web/app.py` to proxy requests to `agent-service` and aggregate data.
*   [x] **Proposals UI**: Implemented "Ask Agent" modal and proposal list in the dashboard.
*   [x] **Persistence**: Updated `agent/service.py` to save generated proposals to disk for retrieval.

### Phase 7: Resilience & UX Fixes (Current)
This phase addresses critical feedback regarding inventory sync, UI loading states, and missing agent visibility.

*   [x] **7.1: Inventory Sync & Auth Verification**
    *   **Goal**: Ensure `inventory/routers` updates propagate correctly to workers and persist.
    *   **Done**: Created `tests/test_inventory_sync.py`—verifies manifest and archive include inventory/routers and inventory/group_vars/routers.yml; integration test for running cluster.
*   [x] **7.2: Agent API & Dashboard Repair**
    *   **Goal**: Fix "Loading..." hangs on the dashboard and ensure robust error handling for API timeouts.
    *   **Done**: Added `fetchWithTimeout` (10s), AbortController timeout, error handling in all catch blocks; created `tests/test_agent_dashboard_api.py` for response formats and unreachable-agent behavior.
*   [x] **7.3: Log View & Job Status Integration**
    *   **Goal**: Ensure the "Agent Analysis" section is visible in `log_view.html` and add agent status indicators to the Job Status page.
    *   **Done**: Parsed agent review JSON for better display—Summary, Status, Issues (with level badges), Suggestions rendered as formatted HTML. `web/static/js/agent-review.js` used by both log_view and job_status.

### Phase 8: Documentation & Site Review
*   [x] **Documentation**: Updated `API.md` (Agent API section), `USAGE.md` (Agent Analysis section), `README.md` (Agent features, current playbooks including RouterOS, model 3b).
*   [x] **Site Review**: Verified web (localhost:3001) and agent (localhost:5001) respond 200. Documentation aligned with current features.

### Phase 9: Final Validation & Testing
*   [x] **Test Consolidation**: Created `tests/README.md` documenting test categories, run commands, and integration test prerequisites.
*   [x] **Full Validation**: Ran full suite—515 tests pass (1 skipped when cluster not running).

### Phase 10: Enhancement Review
*   [x] **Review**: Assessed the system for potential enhancements and next steps. Findings below.

#### Near-Term Enhancements
| Item | Description |
|------|-------------|
| **Documentation** | Add RouterOS playbooks (collect_stats_routeros, get_config_routeros, mikrotik-router-check, change-user-password) to README "Current Playbooks" section. |
| **Test Coverage** | Add/verify tests for network playbooks (RouterOS, network-config) in `tests/`. |
| **Site Review** | Complete manual "Site review: Verify system requirements" in memory.md. |
| **Agent analysis UX** | Re-run analysis button when analysis fails; surface failure reason (e.g. no connection, timeout, server error) so the user knows why it failed. See memory.md § Known Technical Debt. |

#### Medium-Term Enhancements
| Item | Description |
|------|-------------|
| **Agent Stats / Schema** | See "Planned: Agent Stats & Schema Extraction" below. |
| **Testing** | Aggressive failure-mode tests (service stopped, network down), input/output validation, security testing; organize tests by type and purpose (see `tests/README.md`). |
| **Config Panel** | Central config UI for storage backend, agent trigger, model selection, cluster options; backup/restore for config and data. |

#### Long-Term Enhancements (from product vision)
| Item | Description |
|------|-------------|
| **Single-Container Bootstrap** | Base image runs Ansible to deploy DB, agent, workers on demand; config panel controls which services run. |
| **Authentication** | Users/groups, SSL (auto local certs or user-provided), ACLs (admin, monitor, servers_only, network_device_only). |
| **GUI Modernization** | Shared layout with left nav, top tabs; modular page loading; support for custom/user pages. |
| **Distributed Deployment** | Config to deploy agent (GPU host), DB (high-memory), workers (near resources) on remote hosts. |

### Planned: Agent Stats & Schema Extraction
*   [ ] **Goal**: Enable the model to review all prior output from the same playbook/host and calculate stats.
*   [ ] **Approach**:
    1. **First run** (new playbook/host): Separate LLM call parses the log and returns (a) a schema of extractable fields (e.g. `{ uptime: number, memory_used_mb: number }`) and (b) initial values. Schema + result stored in MongoDB.
    2. **Subsequent runs**: Schema accompanies the log; the model fills in the schema. Values appended to MongoDB per playbook/host/time.
    3. **Stats**: Aggregate and display per playbook/host over time (trends, anomalies).
*   **Scope**: In addition to the existing log-review result; implemented as a separate interaction.

## 4. Operational Guidelines & Security
*   **Human-in-the-loop**: All agent-generated code must be approved by a user before execution. The agent cannot self-deploy changes.
*   **Advisory Role**: The agent is an advisor, not an executor. It proposes changes, it does not act on them.
*   **Data Safety**: The agent cannot delete data. It has read-only access to source code and logs.
*   **Fallback**: The system must remain fully functional if the agent service is down.
*   **Safety**: The agent is read-only on production infrastructure unless executing a specific, approved change workflow via the `ansible-web` API (which enforces auth).

## 5. Workflows (Detailed)

This section documents the main data flows so that implementation and debugging stay consistent. **The same workflows and a full "Logs and debugging" section (including agent analysis failure) are in [ARCHITECTURE.md](ARCHITECTURE.md)**; keep both updated when changing how components interact (see also `memory.md`).

### 5.1 Agentic Log-Review Flow
1. **Trigger**: When a job completes (worker POSTs to `ansible-web` job-completion API), the web server triggers the agent by POSTing to `agent-service` `/trigger/log-review` with `{ job_id, exit_code }`. The web does not wait for the result.
2. **Agent work**: The agent runs `process_log_review(job_id, exit_code)` in a background thread. It writes a status file (`review_status/<job_id>.status` = `running`) so the **review-status** API can report progress. It fetches job details and log content from the web, calls the LLM to analyze the log, then writes the review to `reviews/<job_id>.json` (or a failure review with `status: 'failure'` and `error` message). On success or failure it removes the status file and calls **notify**.
3. **Notify**: The agent POSTs to `ansible-web` `/api/agent/review-ready` with `{ job_id, status: 'completed'|'error' }`. The web emits a Socket.IO event `agent_review_ready` to the room `job_<job_id>`.
4. **UI**: Log view and Job Status pages that care about this job either join the room `job_<job_id>` (Socket.IO) or poll. They **prefer push**: when they receive `agent_review_ready`, they fetch the full review once via `GET /api/agent/reviews/<job_id>` and update the UI. They may **poll** only the lightweight `GET /api/agent/review-status/<job_id>` (returns `pending` | `running` | `completed` | `error`) to show “in progress” or “will update when ready” until the push arrives or status is `completed`/`error`, then fetch the full review. This avoids polling the full review body and allows the UI to wait for the agent or show a clear “will be updated” state.

### 5.2 Job Completion Flow (Cluster)
1. Worker finishes the playbook and POSTs to `ansible-web` job-completion endpoint with log content (or log file reference), status, exit code.
2. Web updates storage (job status, log file path), stores the log under `logs/`, optionally runs CMDB callback handling, emits `job_completed` to the `jobs` room and triggers the agent (see 5.1).
3. Clients (e.g. Job Status page) that joined `job_<job_id>` receive live log updates during the run and `job_completed` at the end; they can then load the final log and start agent-review handling (push or poll).

### 5.3 Content Sync Flow (Primary → Workers)
1. Workers periodically (or on demand) request the current revision from the primary (e.g. sync API).
2. Primary reports current git revision (or content hash). If the worker’s revision is older, the worker pulls updated playbooks, inventory, and `ansible.cfg` (and other synced paths) from the primary.
3. Playbook runs on the worker use this synced content so that inventory and config changes are reflected without rebuilding the worker image (unless the image itself changed, e.g. `Dockerfile.worker`).

### 5.4 Other Flows
*   **Scheduled runs**: Scheduler on the primary enqueues jobs or invokes the run API; jobs are routed to workers like any other job; completion and agent flow are as in 5.1–5.2.
*   **Proposals / config analysis**: User-initiated from the UI; the web proxies requests to the agent; the agent returns results synchronously (or stores and returns a reference). No push flow is required for these.
