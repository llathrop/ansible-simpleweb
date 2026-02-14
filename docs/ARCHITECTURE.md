# Ansible SimpleWeb — Architecture

This document is the **single architecture reference** for the whole environment: web server, workers, agent, storage, and how they interact. For deeper detail on cluster or agentic features, see [CLUSTER.md](CLUSTER.md) and [AGENTIC_OVERVIEW.md](AGENTIC_OVERVIEW.md).

## 1. Overview

- **Primary (ansible-web)**: Flask app that serves the UI, REST API, job queue, worker registry, content sync, and scheduler. It triggers the agent when jobs complete and proxies agent APIs to the UI.
- **Workers (ansible-worker-*)**: Register with the primary, sync playbooks/inventory via the primary’s sync API, run Ansible playbooks, and report results and logs back via API.
- **Agent (agent-service)**: AI service for log review, proposals, config analysis. On job completion the primary triggers it; it fetches the log, analyzes it with an LLM, and writes a review (or failure). It notifies the primary when done. **LLM**: Ollama runs as a container (`ollama` service). Agent uses `LLM_API_URL=http://ollama:11434/v1`. Default model is **lightweight** (`qwen2.5-coder:1.5b`); set `LLM_MODEL` in the agent environment to change it (e.g. `qwen2.5-coder:7b`). On first run, pull the model: `docker compose exec ollama ollama run qwen2.5-coder:1.5b`.
- **Storage**: MongoDB (or flatfile) for jobs, workers, schedules, and app state. Log files live on the host under `./logs/` (and in the container at `/app/logs` for web and agent).

## 2. Components

| Component        | Container / process | Role |
|-----------------|--------------------|------|
| Web             | `ansible-web`      | UI, API, job queue, worker registry, sync, scheduler, agent trigger and proxy |
| Workers         | `ansible-worker-1` etc. | Run Ansible, report to primary |
| Agent           | `agent-service`    | Log review, proposals, config analysis (LLM + RAG) |
| Ollama          | `ansible-ollama`   | LLM inference (OpenAI-compatible API); required for agent log review |
| MongoDB         | `ansible-simpleweb-mongodb` | Persistent storage (when `STORAGE_BACKEND=mongodb`) |

## 3. Cluster (summary)

- Primary holds job queue and worker registry. Workers pull content (playbooks, inventory, `ansible.cfg`) from the primary via sync API; all job state is over the REST API.
- Local executor on the primary acts as a lowest-priority worker when no remote workers are used.
- Full description: [CLUSTER.md](CLUSTER.md).

## 4. Agent (summary)

- Event-driven: primary POSTs to agent `/trigger/log-review` when a job completes. Agent runs analysis in a background thread, then POSTs to primary `/api/agent/review-ready` so the UI can update.
- UI can poll `GET /api/agent/review-status/<job_id>` (pending | running | completed | error) and fetch the full review when done, or rely on the push event.
- Phased plan, security, and responsibilities: [AGENTIC_OVERVIEW.md](AGENTIC_OVERVIEW.md). Workflows are also summarized in §6 below.

## 5. Workflows (summary)

- **Job completion**: Worker POSTs completion to primary → primary updates storage and log → primary triggers agent (fire-and-forget) → primary emits `job_completed` (and later `agent_review_ready` when agent finishes).
- **Agent log review**: Trigger → agent fetches job + log from primary → agent calls LLM → agent writes review (or failure) → agent notifies primary → UI gets push or polls review-status then fetches review.
- **Content sync**: Workers ask primary for current revision; if behind, they pull updated content (playbooks, inventory, ansible.cfg) and run jobs with that content.

## 6. Logs and debugging

Where to look when something goes wrong, and how to debug **agent analysis** in particular.

### 6.1 Where logs live

- **Web (ansible-web)**  
  - Flask and trigger logic log to **process stdout/stderr**, i.e. **container logs**.  
  - **View**: `docker compose logs ansible-web` or `docker compose logs -f ansible-web`.  
  - Agent trigger messages (e.g. “Agent review triggered for job …” or “Failed to trigger agent review …”) appear here.

- **Workers**  
  - **View**: `docker compose logs ansible-worker-1` (or worker-2, worker-3).  
  - Playbook output is streamed to the primary and stored under `./logs/` on the host.

- **Agent (agent-service)**  
  - All agent logic (trigger received, job fetch, LLM call, review saved, notify) logs via Python `logging` to **stderr**. There is **no separate log file** inside the container; the only place to see agent interaction is **container logs**.  
  - **View**:  
    `docker compose logs agent-service`  
    or follow:  
    `docker compose logs -f agent-service`  
  - Look for: `Received trigger for job …`, `Starting review for job …`, `Failure review saved …`, `Notified web …`, `Review saved to …`, or exceptions (e.g. LLM unreachable, job fetch failed).

- **Ollama (LLM)**  
  - Ollama is **part of this project**; its status and logs are the project’s responsibility. It runs only in the `ollama` container (no host process).  
  - **Logs**: All Ollama daemon output goes to **container stdout/stderr**.  
  - **View**: `docker compose logs ollama` or `docker compose logs -f ollama`.  
  - **Health**: The service has a Docker healthcheck (`ollama list`). Check status with `docker compose ps ollama` (healthy/unhealthy).  
  - **Verify with a simple query**: From the project root, run `./scripts/verify-ollama.sh` (or `curl -s http://localhost:11434/api/tags` when the container is up).

- **Playbook / job logs**  
  - Stored under project `./logs/` (e.g. `job-<id>.log`). Visible in the UI (Logs, Job status) and readable by the agent from its mounted `/app/logs`.

### 6.2 Debugging agent analysis failure

If “Agent analysis” in the UI shows an error or never completes:

1. **Confirm the trigger ran (web)**  
   `docker compose logs ansible-web 2>&1 | grep -i agent`  
   - You should see “Agent review triggered for job &lt;id&gt;” after a job completes.  
   - If you see “Failed to trigger agent review …”, the web cannot reach the agent (network, URL, or agent down).

2. **Inspect agent behavior (agent)**  
   `docker compose logs agent-service 2>&1` (or `-f` for follow)  
   - After a job completes, look for:  
     - `Received trigger for job <id>`  
     - `Starting review for job <id>`  
     - Then either success (“Review saved to …”, “Notified web …”) or errors:  
       - “Failed to fetch job details” → agent cannot reach primary or job missing.  
       - “Log file not found” → log not yet written or path mismatch.  
       - “LLM Server Unreachable” / “APIConnectionError” → LLM (e.g. Ollama) not running or not reachable at `LLM_API_URL`.  
       - Any Python traceback → logic or config bug in agent.

3. **LLM reachability**  
   - Ollama runs **only in the `ollama` container** (no local/host Ollama). The agent uses `LLM_API_URL=http://ollama:11434/v1` (set in docker-compose). To confirm the Ollama container is responding from the host (port 11434 is published): `curl -s http://localhost:11434/api/tags`. If you have Ollama running on the host, stop it so only the container is used.

4. **Review and status APIs**  
   - From the host:  
     - `curl -s http://localhost:3001/api/agent/review-status/<job_id>` → pending | running | completed | error.  
     - `curl -s http://localhost:3001/api/agent/reviews/<job_id>` → full review or 404.  
   - If status stays `pending`/`running` and agent logs show “Review saved” and “Notified web”, check that the UI is either receiving the `agent_review_ready` event or polling review-status and then fetching the review.

Keeping this section in sync with the code (and any new log destinations) will help users debug agent and trigger issues. See also [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for general issues.

## 7. Single-container and multi-container expansion

- **Single-container (demo)**: The same image can run as one container (primary only, flatfile storage, local executor). Use `docker-compose.single.yml`; see [REBUILD.md](REBUILD.md) § Single-container mode. Validation: `scripts/validate_single_container.py`.
- **Config**: App config lives in `app_config.yaml` (CONFIG_DIR, default `/app/config`). The **Config** page in the UI lets you view/edit options (quick config and full YAML), backup/restore config, and backup/restore data (schedules, inventory, etc.). Storage init and feature flags (DB, agent, workers) are driven by this config.
- **GUI**: Shared layout with top tabs (Execution, Logs & Data, System) and left nav panel. Navigation is centralized in `web/nav.py`; see `docs/ADDING_PAGES.md` for adding custom pages.
- **Bootstrap and expansion**: On startup, if config requests DB/agent/workers but they are not yet deployed, the primary runs the deploy playbook (Ansible) in the background. The same flow can be triggered from the Config page (“Deploy now”) or `POST /api/deployment/run`. Desired vs current state and delta are exposed at `GET /api/deployment/status`. See [PHASE_SINGLE_CONTAINER_BOOTSTRAP.md](PHASE_SINGLE_CONTAINER_BOOTSTRAP.md).
