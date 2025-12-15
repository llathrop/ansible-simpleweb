# Ansible Cluster Architecture

This document describes the distributed cluster architecture for running Ansible jobs across multiple worker nodes.

## Overview

The system transforms the single-container Ansible web interface into a distributed cluster where:

- **Primary Server**: Manages job queue, worker registration, content sync, and coordination
- **Worker Nodes**: Register with primary, sync playbooks/inventory via git, execute jobs, report status via API
- **Standalone Mode**: Local Ansible executor acts as implicit lowest-priority worker

## Design Principles

1. **Extend, don't replace** - Worker and job data follows existing storage patterns
2. **Storage agnostic** - Works identically with flatfile or MongoDB backends
3. **Migration safe** - Same data structures in both backends
4. **Git for content sync** - Playbooks, inventory, library, callback_plugins synced via git
5. **API for state** - All worker/job state communicated via REST API (not git)
6. **Stateless workers** - All job state lives on primary; removing a worker only loses in-flight updates
7. **Standalone compatibility** - Local executor is implicit lowest-priority worker; remote workers automatically take precedence

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      PRIMARY SERVER                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Storage   │  │  Job Queue  │  │  Worker Registry    │  │
│  │ (flat/mongo)│  │   (API)     │  │      (API)          │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│         │               │                    │               │
│  ┌──────┴───────────────┴────────────────────┴────────┐     │
│  │                    REST API                         │     │
│  │  /api/workers/*    - Registration, status, checkin │     │
│  │  /api/jobs/*       - Submit, assign, complete      │     │
│  │  /api/sync/*       - Git repo access (HTTP)        │     │
│  └─────────────────────────────────────────────────────┘     │
│         │                                                    │
│  ┌──────┴──────┐                                            │
│  │ Local Exec  │  ← Implicit worker, LOWEST priority        │
│  │ (standalone)│                                            │
│  └─────────────┘                                            │
└─────────────────────────────────────────────────────────────┘
          │
          │ HTTP/API (all state)
          │ Git pull (content only)
          ▼
┌─────────────────────┐   ┌─────────────────────┐
│     WORKER 1        │   │     WORKER 2        │
│  ┌───────────────┐  │   │  ┌───────────────┐  │
│  │ Local Git     │  │   │  │ Local Git     │  │
│  │ (content only)│  │   │  │ (content only)│  │
│  └───────────────┘  │   │  └───────────────┘  │
│         │           │   │         │           │
│  ┌──────┴────────┐  │   │  ┌──────┴────────┐  │
│  │   Executor    │  │   │  │   Executor    │  │
│  │ (runs ansible)│  │   │  │ (runs ansible)│  │
│  └───────────────┘  │   │  └───────────────┘  │
│         │           │   │         │           │
│  Reports via API:   │   │  Reports via API:   │
│  - Job status       │   │  - Job status       │
│  - Logs             │   │  - Logs             │
│  - Checkins         │   │  - Checkins         │
└─────────────────────┘   └─────────────────────┘
```

## Communication Model

### Git (Content Sync Only)

Git is used exclusively for synchronizing Ansible content:
- `playbooks/` - Ansible playbooks
- `inventory/` - Host inventory files
- `library/` - Custom Ansible modules
- `callback_plugins/` - Ansible callback plugins
- `ansible.cfg` - Ansible configuration

Sync can be triggered:
- Periodically (configurable interval)
- On-demand via notification from primary
- On worker startup/registration

### REST API (All State)

All worker and job state is communicated via REST API:
- Worker registration and authentication
- Job submission and assignment
- Job status updates
- Completion reports with logs
- Periodic health check-ins
- System statistics

## Directory Structure

### Content Repository (Git-synced)

```
ansible-content/          # Git repository - synced to workers
├── playbooks/
│   ├── *.yml             # Ansible playbooks
│   └── README.md
├── inventory/
│   ├── hosts             # Inventory file(s)
│   └── README.md
├── library/
│   └── README.md
├── callback_plugins/
│   └── README.md
└── ansible.cfg
```

### Application Structure

```
/app/
├── web/                  # Flask app (primary server)
├── worker/               # Worker service
├── config/               # Storage data (schedules, workers, jobs, etc.)
├── logs/                 # Execution logs
├── ssh-keys/             # SSH keys
└── ansible-content/      # Git repo (mounted/cloned)
```

## Data Models

### Worker

```python
{
    "id": "uuid",
    "name": "worker-01",
    "tags": ["network-a", "gpu", "high-memory"],
    "priority_boost": 0,        # Manual priority adjustment
    "status": "online|offline|busy|stale",
    "is_local": false,          # True for standalone executor
    "registered_at": "ISO timestamp",
    "last_checkin": "ISO timestamp",
    "sync_revision": "git-sha", # Last synced content revision
    "current_jobs": ["job-id"], # Tracked by primary
    "stats": {
        "load_1m": 0.5,
        "memory_percent": 45,
        "jobs_completed": 150,
        "jobs_failed": 3,
        "avg_job_duration": 120
    }
}
```

### Job

```python
{
    "id": "uuid",
    "playbook": "hardware-inventory.yml",
    "target": "webservers",
    "required_tags": ["network-a"],    # Worker must have all these
    "preferred_tags": ["high-memory"], # Boost score if present
    "priority": 50,                    # 1-100, higher = more urgent
    "job_type": "normal|long_running",
    "status": "queued|assigned|running|completed|failed|cancelled",
    "assigned_worker": "worker-id|null|__local__",
    "submitted_by": "user|schedule:id",
    "submitted_at": "ISO timestamp",
    "assigned_at": "ISO timestamp|null",
    "started_at": "ISO timestamp|null",
    "completed_at": "ISO timestamp|null",
    "log_file": "path|null",
    "exit_code": "int|null",
    "error_message": "string|null"
}
```

## Priority System

Workers are scored for each job using these factors:

1. **Local executor penalty**: Always lowest priority (`-1000` boost)
2. **Required tags**: Must match all, or worker is ineligible
3. **Preferred tags**: `+10` per matching tag
4. **Current load**: `-20` per active job on worker
5. **Long-running job distribution**: `-25` per long-running job (spreads them out)
6. **Worker health**: `+15 * success_rate`
7. **Manual boost**: Configurable per-worker adjustment

```python
def calculate_worker_score(job, worker):
    if worker.is_local:
        return 1  # Minimum score

    score = 100  # Base for remote workers

    # Required tags must match
    if not all(t in worker.tags for t in job.required_tags):
        return -1  # Ineligible

    # Preferred tags bonus
    score += sum(10 for t in job.preferred_tags if t in worker.tags)

    # Load penalty
    score -= len(worker.current_jobs) * 20

    # Long-running distribution
    if job.job_type == "long_running":
        score -= count_long_running_jobs(worker) * 25

    # Health bonus
    if worker.stats.get('jobs_completed', 0) > 0:
        success_rate = 1 - (worker.stats.get('jobs_failed', 0) /
                           worker.stats['jobs_completed'])
        score += success_rate * 15

    score += worker.priority_boost
    return score
```

## Worker Check-in

Workers report status at configurable intervals (default: 10 minutes):

```python
POST /api/workers/<id>/checkin
{
    "sync_revision": "abc123",
    "active_jobs": [
        {"job_id": "uuid", "status": "running", "progress": 45}
    ],
    "system_stats": {
        "load_1m": 0.5,
        "memory_percent": 67,
        "disk_percent": 45
    }
}
```

Workers also check in on job completion (piggyback checkin data).

### Staleness Detection

Workers are marked `stale` if no checkin received within `2 * checkin_interval`. Assigned jobs on stale workers are requeued automatically.

## Configuration

### Primary Server

```bash
CLUSTER_MODE=standalone|primary    # Operating mode
REGISTRATION_TOKEN=secret-token    # Workers must provide this
CHECKIN_INTERVAL=600               # Expected checkin interval (seconds)
LOCAL_WORKER_TAGS=tag1,tag2        # Tags for local executor
```

### Worker Node

```bash
WORKER_NAME=worker-01              # Unique worker name
SERVER_URL=http://primary:3001     # Primary server URL
REGISTRATION_TOKEN=secret-token    # Must match primary
WORKER_TAGS=network-a,gpu          # Capabilities/tags
CHECKIN_INTERVAL=600               # Checkin frequency (seconds)
MAX_CONCURRENT_JOBS=2              # Max parallel jobs
SYNC_INTERVAL=300                  # Content sync check interval
```

## Feature Implementation Status

### Core Infrastructure
- [x] Feature 1: Worker & Job Queue Storage Models
- [x] Feature 2: Worker Registration API
- [ ] Feature 3: Content Repository Setup (Git)
- [ ] Feature 4: Content Sync API

### Worker Implementation
- [ ] Feature 5: Worker Client Service
- [ ] Feature 8: Worker Job Execution
- [ ] Feature 9: Worker Check-in System

### Job Management
- [ ] Feature 6: Job Submission & Queue API
- [ ] Feature 7: Job Priority & Assignment
- [ ] Feature 10: Job Completion & Results

### Integration
- [ ] Feature 11: Sync Notification System
- [ ] Feature 12: Local Executor as Lowest-Priority Worker
- [ ] Feature 13: Cluster UI Dashboard

## Feature Details

### Feature 1: Worker & Job Queue Storage Models

Extend storage backends (`base.py`, `flatfile.py`, `mongodb.py`) with:

**Worker methods:**
- `get_all_workers()` - List all registered workers
- `get_worker(worker_id)` - Get single worker
- `save_worker(worker)` - Create/update worker
- `delete_worker(worker_id)` - Remove worker
- `update_worker_status(worker_id, status, stats)` - Update status

**Job queue methods:**
- `get_all_jobs(filters)` - List jobs with filtering
- `get_job(job_id)` - Get single job
- `save_job(job)` - Create/update job
- `update_job(job_id, updates)` - Partial update
- `delete_job(job_id)` - Remove job
- `get_pending_jobs()` - Jobs awaiting assignment
- `get_worker_jobs(worker_id)` - Jobs for specific worker

### Feature 2: Worker Registration API

**Endpoints:**
- `POST /api/workers/register` - Worker self-registers with token
- `GET /api/workers` - List all workers
- `GET /api/workers/<id>` - Get worker details
- `DELETE /api/workers/<id>` - Unregister worker
- `POST /api/workers/<id>/checkin` - Worker status update

### Feature 3: Content Repository Setup (Git)

Initialize git repository for syncable content:
- Auto-init on primary startup if not exists
- Template files for empty directories
- Commit tracking for all changes
- Manifest generation for verification

### Feature 4: Content Sync API

**Endpoints:**
- `GET /api/sync/revision` - Current HEAD SHA
- `GET /api/sync/archive` - Tar.gz download
- `GET /api/sync/manifest` - File checksums
- Git smart HTTP for clone/pull

### Feature 5: Worker Client Service

Standalone service for worker containers:
- Configuration via environment variables
- Registration on startup
- Git clone/pull for content
- Job polling and execution
- Periodic check-ins
- Graceful shutdown

### Feature 6: Job Submission & Queue API

**Endpoints:**
- `POST /api/jobs` - Submit new job
- `GET /api/jobs` - List with filters
- `GET /api/jobs/<id>` - Job details
- `DELETE /api/jobs/<id>` - Cancel job
- `GET /api/jobs/<id>/log` - Job output

### Feature 7: Job Priority & Assignment

Automatic job routing based on:
- Tag requirements and preferences
- Worker current load
- Job type (normal vs long-running)
- Worker health statistics
- Manual priority adjustments

### Feature 8: Worker Job Execution

Worker-side job handling:
- Poll for assigned jobs
- Execute via ansible-playbook
- Capture logs and exit codes
- Report completion to primary

### Feature 9: Worker Check-in System

Regular health reporting:
- Configurable interval (default 10 min)
- Active job status
- System statistics
- Sync revision verification

### Feature 10: Job Completion & Results

Completion handling:
- Status and exit code
- Full log storage
- CMDB facts extraction
- Worker statistics update
- Piggyback checkin processing

### Feature 11: Sync Notification System

Change propagation:
- WebSocket notification on commit
- Stored revision for polling
- Worker sync on notification

### Feature 12: Local Executor Integration

Standalone mode compatibility:
- Implicit `__local__` worker
- Lowest priority scoring
- Uses existing execution code
- Seamless with remote workers

### Feature 13: Cluster UI Dashboard

Web interface additions:
- `/cluster` - Dashboard page
- Worker status cards
- Job queue visualization
- Sync status display
- Real-time WebSocket updates
