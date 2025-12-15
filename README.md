# Ansible Simple Web Interface

A lightweight, Docker-based web interface for managing and executing Ansible playbooks. Run playbooks with a single click, monitor execution status in real-time, and view logs through a clean, modern web UI.

## Features

### Core Features
- 🚀 **One-Click Execution** - Run any playbook with a single button click
- 🎯 **Multi-Host Support** - Target individual hosts or groups via dropdown selection
- 📊 **Real-Time Status** - Live status updates (Ready/Running/Completed/Failed)
- 📝 **Log Management** - Automatic log capture with timestamped filenames
- 🔍 **Log Viewer** - Browse and view all execution logs in the browser
- 🎨 **Theming Support** - Multiple themes including dark mode, low contrast, and colorblind-friendly options
- 🔌 **REST API** - JSON endpoints for external integrations
- 🐳 **Fully Containerized** - Rocky Linux 9 with Ansible 8.7.0 pre-configured
- 🔒 **Localhost First** - Secure by default, ready for authentication later
- 💾 **Flexible Storage** - Choose between flat file (JSON) or MongoDB for data persistence
- 📦 **Inventory Management** - API for managing host inventory with full CRUD operations

### Batch Job Execution (NEW)
- 📦 **Batch Jobs** - Select multiple playbooks and hosts, run them sequentially as a named batch
- 🔄 **Playbook Ordering** - Drag-and-drop or up/down buttons to reorder playbook execution
- 👁️ **Live Batch Monitoring** - Watch batch progress with automatic log switching between playbooks
- 📤 **Export Configurations** - Export batch job configs as JSON for version control
- ⏰ **Batch Scheduling** - Schedule batch jobs with full recurrence options

### Schedule Management
- ⏱️ **Playbook Scheduling** - Schedule single playbooks or batch jobs with cron-like recurrence
- 📈 **Success Rate Tracking** - Track success/failure rates per schedule (e.g., "8/10 succeeded")
- 📋 **Execution History** - View detailed history of scheduled runs

### Host Configuration Wizard (NEW)
- 🧙 **Multi-Step Wizard** - Guided 4-step process for adding/editing hosts
- 🔑 **SSH Key Management** - Upload and manage SSH private keys securely
- 🔐 **Multiple Auth Methods** - Support for SSH keys, passwords, or SSH agent
- 🔍 **Connection Testing** - Test SSH connectivity before saving host configuration

## Quick Start

### Prerequisites
- Docker
- docker-compose
- SSH server on target hosts

### 1. Start the Container

```bash
# Clone or navigate to project directory
cd ansible-simpleweb

# Build and start
docker-compose up -d

# Verify it's running
docker-compose ps
```

### 2. Access the Web Interface

Open your browser to: **http://localhost:3001**

You'll see all available playbooks with run buttons and status indicators.

### 3. Run Your First Playbook

1. Select a target from the dropdown (e.g., "host_machine")
2. Click "Run Playbook"
3. Watch the status change to "Running"
4. Click "View Log" when complete

Done! 🎉

## Adding Playbooks

Simply drop a `.yml` file in the `playbooks/` directory:

```bash
# Create a new playbook
cat > playbooks/my-playbook.yml << 'EOF'
---
- name: My Custom Playbook
  hosts: all
  gather_facts: yes
  tasks:
    - name: Collect information
      debug:
        msg: "Running on {{ ansible_hostname }}"
EOF

# Refresh the web interface - it appears automatically!
```

**That's it!** No restart needed, no configuration required.

## Adding Hosts

Edit `inventory/hosts` to add new target machines:

```ini
[production]
prod1.example.com ansible_user=deploy
prod2.example.com ansible_user=deploy

[staging]
stage.example.com ansible_user=deploy
```

Refresh the page - new hosts appear in the dropdown automatically.

## Project Structure

```
ansible-simpleweb/
├── playbooks/          # Add your Ansible playbooks here
├── inventory/          # Configure target hosts here
│   └── hosts          # Main inventory file (Ansible INI format)
├── logs/              # Playbook execution logs (auto-generated)
├── ssh-keys/          # Uploaded SSH private keys (writable)
├── .ssh/              # System SSH keys (read-only mount)
├── config/            # Configuration files
│   ├── themes/        # Theme JSON files (customizable)
│   ├── schedules.json # Schedule definitions (flatfile backend)
│   ├── schedule_history.json # Execution history (flatfile backend)
│   ├── inventory.json # Managed inventory (flatfile backend)
│   └── batch_jobs.json # Batch job records (flatfile backend)
├── web/               # Flask web application
│   ├── app.py         # Main Flask application (~2000 lines)
│   ├── scheduler.py   # APScheduler integration (batch + single schedules)
│   ├── storage/       # Storage backend abstraction
│   │   ├── __init__.py    # Factory function
│   │   ├── base.py        # Abstract interface (inventory, schedules, batch jobs, CMDB)
│   │   ├── flatfile.py    # JSON file storage
│   │   └── mongodb.py     # MongoDB storage
│   ├── migrate_storage.py # Migration script between backends
│   ├── templates/
│   │   ├── index.html         # Batch execution page (main)
│   │   ├── playbooks.html     # Individual playbook cards
│   │   ├── schedules.html     # Schedule management
│   │   ├── schedule_form.html # Create/edit schedules (batch mode support)
│   │   ├── inventory.html     # CMDB with host wizard
│   │   └── batch_live_log.html # Live batch job monitoring
│   └── static/
└── docker-compose.yml # Includes MongoDB container + ssh-keys volume
```

## Documentation

- **[Usage Guide](docs/USAGE.md)** - Detailed interface walkthrough
- **[Adding Playbooks](docs/ADDING_PLAYBOOKS.md)** - Complete guide to creating playbooks
- **[Configuration](docs/CONFIGURATION.md)** - Inventory setup and SSH configuration
- **[API Reference](docs/API.md)** - REST API endpoints
- **[Troubleshooting](docs/TROUBLESHOOTING.md)** - Common issues and solutions

## Current Playbooks

This project includes 5 example playbooks:

- **hardware-inventory** - CPU, memory, disks, GPU detection
- **software-inventory** - Installed packages with versions
- **system-health** - Uptime, load, memory, disk usage, errors
- **service-status** - System services and their status
- **network-config** - Network interfaces, routing, DNS

## Development Status

✅ **Step 1:** Docker container with Ansible + Flask
✅ **Step 2:** 5 working playbooks tested on real hardware
✅ **Step 3:** Full web interface with real-time updates
✅ **Step 4:** Multi-host target selection
✅ **Step 5:** Theming system with dark mode and accessibility themes
✅ **Step 6:** Pluggable storage backend (flat file / MongoDB)
✅ **Step 7:** Batch job execution with live monitoring
✅ **Step 8:** Schedule management with batch support and success tracking
✅ **Step 9:** Host configuration wizard with SSH key management
✅ **Step 10:** Cluster mode with distributed workers (13 features implemented)
  - Worker registration and authentication
  - Content repository with revision tracking
  - Sync API for playbook/inventory distribution
  - Worker service with health reporting
  - Job queue with priority support
  - Smart job routing with tag-based targeting
  - Worker execution with log capture
  - Worker check-in and heartbeat monitoring
  - Job completion reporting with log upload
  - Sync notification via WebSocket
  - Local executor fallback
  - Cluster dashboard with real-time stats

**Status:** Cluster mode functional, pending bug fixes (see TODO list)

## Common Commands

```bash
# Start the service
docker-compose up -d

# View logs
docker-compose logs -f

# Restart after changes
docker-compose restart

# Stop the service
docker-compose down

# Run playbook manually (from host)
docker-compose exec -T ansible-web ansible-playbook playbooks/your-playbook.yml -l target
```

## Requirements

- Docker Engine 20.10+
- docker-compose 1.29+
- 2GB RAM minimum
- Network access to target hosts

## Security Notes

- Currently **localhost only** (no external access)
- No authentication required (add before exposing externally)
- SSH keys mounted read-only from `~/.ssh`
- Service account recommended for target hosts (see [Configuration](docs/CONFIGURATION.md))

## Cluster Mode (NEW)

Distribute Ansible workloads across multiple worker nodes for scalability and fault tolerance.

### Cluster Features
- 🔗 **Worker Registration** - Workers auto-register with primary server using tokens
- 📊 **Worker Dashboard** - Real-time view of all workers with health stats
- ⚖️ **Smart Job Routing** - Automatic job assignment based on tags, load, and preferences
- 🔄 **Content Sync** - Playbooks/inventory sync from primary to workers with revision tracking
- 📡 **Real-time Updates** - WebSocket notifications for sync events
- 🏷️ **Tag-Based Targeting** - Route jobs to specific workers via required/preferred tags
- 💓 **Health Monitoring** - Worker check-ins with CPU, memory, and disk stats
- 🖥️ **Local Executor Fallback** - Built-in local worker as lowest-priority fallback

### Quick Cluster Setup

```bash
# Start cluster with 3 workers
docker-compose up -d

# Verify workers registered
curl http://localhost:3001/api/workers | python3 -m json.tool
```

### Cluster Architecture
```
                    ┌─────────────────┐
                    │  Primary Server │
                    │  (ansible-web)  │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│   Worker-1    │  │   Worker-2    │  │   Worker-3    │
│  zone-a       │  │  zone-b       │  │  zone-c       │
│  general      │  │  high-memory  │  │  network      │
└───────────────┘  └───────────────┘  └───────────────┘
```

---

## Current TODO List

### Critical Bugs
- [x] ~~**Playbook path missing `.yml` extension**~~ - Fixed: `_resolve_playbook_path()` now auto-detects .yml/.yaml extensions
- [x] ~~**Workers cannot reach external targets**~~ - Fixed: Added network configuration options (host mode, extra_hosts) and SSH key documentation in docker-compose.yml and docs/CLUSTER.md
- [ ] **Live view broken for cluster jobs** - Live log streaming (`/live/<run_id>`) doesn't work for jobs dispatched to remote workers; needs WebSocket relay from worker to primary

### Tests Needed

**Unit Tests**
- [ ] `test_job_dispatch.py` - Test web UI job submission routes to queue in cluster mode
- [ ] `test_playbook_path.py` - Test playbook path construction includes `.yml` extension
- [ ] `test_worker_ssh_access.py` - Test worker containers can SSH to inventory hosts
- [ ] `test_log_upload.py` - Test log files are uploaded from workers to primary

**Integration Tests**
- [ ] End-to-end job dispatch test (submit → route → execute → complete)
- [ ] Multi-worker load balancing test
- [ ] Worker failover test (job reassignment on worker failure)
- [ ] Content sync integrity test (playbooks match after sync)

**Existing Test Coverage**
- [x] Cluster storage (`test_storage_cluster.py`, `test_feature_cluster_storage.py`)
- [x] Worker registration (`test_worker_api.py`, `test_feature_worker_registration.py`)
- [x] Content repository (`test_content_repo.py`, `test_feature_content_repo.py`)
- [x] Sync API (`test_sync_api.py`, `test_feature_sync_api.py`)
- [x] Worker service (`test_worker.py`, `test_feature_worker.py`)
- [x] Job API (`test_job_api.py`, `test_feature_job_queue.py`)
- [x] Job routing (`test_feature_job_routing.py`)
- [x] Worker execution (`test_worker_executor.py`, `test_feature_worker_execution.py`)
- [x] Worker check-in (`test_worker_checkin.py`, `test_feature_worker_checkin.py`)
- [x] Job completion (`test_job_completion.py`, `test_feature_job_completion.py`)
- [x] Sync notification (`test_sync_notification.py`, `test_feature_sync_notification.py`)
- [x] Local worker (`test_local_worker.py`, `test_feature_local_worker.py`)
- [x] Job router (`test_job_router.py`)
- [x] Cluster dashboard (`test_cluster_dashboard.py`, `test_feature_cluster_dashboard.py`)

### Documentation Updates

**README Updates**
- [ ] Add cluster mode configuration section
- [ ] Document environment variables for workers
- [ ] Add troubleshooting guide for cluster issues
- [ ] Document tag-based job routing

**Code Comments**
- [ ] Document `run_playbook()` cluster mode logic in `app.py`
- [ ] Document `JobRouter` scoring algorithm
- [ ] Document worker sync process in `worker/sync.py`
- [ ] Add docstrings to `job_status.html` template JavaScript

**New Documentation Files**
- [ ] `docs/CLUSTER.md` - Comprehensive cluster setup and operation guide
- [ ] `docs/WORKER_SETUP.md` - Worker configuration and deployment
- [ ] `docs/JOB_ROUTING.md` - Tag-based routing and priority system
- [ ] `docs/API_CLUSTER.md` - Cluster-related API endpoints

### Infrastructure Improvements

**Worker Configuration**
- [ ] Mount inventory file to workers for target host access
- [ ] Configure SSH agent forwarding for workers
- [ ] Add health check endpoint to worker Dockerfile
- [ ] Support custom ansible.cfg per worker

**Networking**
- [ ] Document network requirements for workers to reach targets
- [ ] Add DNS configuration for service discovery
- [ ] Support external workers (not in Docker network)

**Security**
- [ ] Rotate registration tokens periodically
- [ ] Add TLS between workers and primary
- [ ] Implement job result signing/verification
- [ ] Add worker authentication beyond token

### Feature Enhancements

**Job Management**
- [ ] Job cancellation (kill running playbook on worker)
- [ ] Job retry with configurable attempts
- [ ] Job timeout handling
- [ ] Job priority queuing (high/normal/low)

**Worker Management**
- [ ] Manual worker enable/disable from dashboard
- [ ] Worker maintenance mode (drain jobs before shutdown)
- [ ] Worker auto-scaling based on queue depth
- [ ] Worker groups/pools for isolation

**Monitoring**
- [ ] Prometheus metrics endpoint
- [ ] Grafana dashboard templates
- [ ] Alert rules for worker failures
- [ ] Job queue depth monitoring

### Original Planned Features (Pre-Cluster)

**Authentication & Security**
- [ ] Add authentication system (JWT, OAuth, or basic auth)
- [ ] User management and role-based access control
- [ ] API key authentication for programmatic access
- [ ] Session management and timeouts

**External Access**
- [ ] Configure for external network access (beyond localhost)
- [ ] HTTPS/TLS support with SSL certificates
- [ ] Reverse proxy configuration guide (nginx/Apache)
- [ ] CORS configuration for API access

**Log Management**
- [ ] Automatic log rotation system
  - Archive to `last-week/` on Sundays before midnight
  - Archive to `last-month/` at month end
  - Archive to `last-year/` at year end
- [ ] Log retention policies (configurable)
- [ ] Log compression for archived logs
- [ ] Log search/filter functionality in web interface

**User Experience**
- [x] ~~Playbook scheduling (cron-like interface)~~ Full schedule management with recurrence options
- [ ] Email notifications on playbook completion
- [ ] Slack/Teams/Discord webhook integrations
- [x] ~~Real-time log streaming (WebSocket)~~ Live batch job monitoring with auto-switching
- [x] ~~Dark mode toggle~~ Theming system with multiple themes (dark, low-contrast, colorblind)
- [ ] Mobile app or PWA support

**Advanced Features**
- [ ] Playbook templates library
- [ ] Variable substitution in playbooks via UI
- [x] ~~Playbook chaining (run multiple in sequence)~~ Batch jobs with ordered playbook execution
- [ ] Conditional execution based on previous results
- [x] ~~Inventory management UI (add/edit hosts via web)~~ Full CMDB with multi-step wizard
- [x] ~~SSH key management interface~~ Upload/select SSH keys in host wizard
- [ ] Ansible Vault integration
- [x] ~~Multi-user playbook execution queue~~ Cluster job queue with worker dispatch

**Monitoring & Reporting**
- [x] ~~Execution history dashboard~~ Schedule history with per-schedule tracking
- [x] ~~Success/failure rate statistics~~ Success rate per schedule (e.g., "8/10 succeeded")
- [ ] Host health monitoring
- [ ] Performance metrics (execution time trends)
- [x] ~~Export reports (PDF, CSV)~~ Export batch job configs as JSON

**Documentation**
- [ ] Video walkthrough/tutorial
- [ ] Interactive demo environment
- [ ] Community playbook repository
- [ ] Best practices guide for playbook authors

### Contribution Ideas

Have an idea for improvement? Consider:
1. Adding new example playbooks to `playbooks/`
2. Improving documentation with real-world examples
3. Creating integration guides for popular tools
4. Submitting bug reports or feature requests

## License

Internal use only.

## Contributing

This project uses git for version control. Each significant change is committed with descriptive messages.

## Support

For issues or questions:
1. Check [Troubleshooting Guide](docs/TROUBLESHOOTING.md)
2. Review [Usage Documentation](docs/USAGE.md)
3. Check application logs: `docker-compose logs`

---

**Built with Claude Code** | Generated with Claude Sonnet 4.5
