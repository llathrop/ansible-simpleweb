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

### Batch Job Execution
- 📦 **Batch Jobs** - Select multiple playbooks and hosts, run them sequentially as a named batch
- 🔄 **Playbook Ordering** - Drag-and-drop or up/down buttons to reorder playbook execution
- 👁️ **Live Batch Monitoring** - Watch batch progress with automatic log switching between playbooks
- 📡 **Real-time Log Streaming** - Worker logs stream live to batch view with late-join catchup
- 📤 **Export Configurations** - Export batch job configs as JSON for version control
- ⏰ **Batch Scheduling** - Schedule batch jobs with full recurrence options

### Schedule Management
- ⏱️ **Playbook Scheduling** - Schedule single playbooks or batch jobs with cron-like recurrence
- 📈 **Success Rate Tracking** - Track success/failure rates per schedule (e.g., "8/10 succeeded")
- 📋 **Execution History** - View detailed history of scheduled runs

### Host Configuration Wizard
- 🧙 **Multi-Step Wizard** - Guided 4-step process for adding/editing hosts
- 🔑 **SSH Key Management** - Upload and manage SSH private keys securely
- 🔐 **Multiple Auth Methods** - Support for SSH keys, passwords, or SSH agent
- 🔍 **Connection Testing** - Test SSH connectivity before saving host configuration

### AI Agent (Log Review & Assistance)
- 🤖 **Automatic Log Review** - AI analyzes playbook output after each run
- 📋 **Structured Analysis** - Summary, status, issues (error/warning/info), suggestions
- 🔧 **Suggested Fix** - SSH auth failures show step-by-step fix with public key and Copy button
- 📊 **Agent Dashboard** - Recent reviews, proposals, config reports

## Quick Start

### Prerequisites
- Docker
- docker-compose
- SSH server on target hosts

### 1. Start the Container

```bash
# Clone or navigate to project directory
cd ansible-simpleweb

# Build and start (full stack: web + optional MongoDB, agent, workers)
docker-compose up -d

# Verify it's running
docker-compose ps
```

**Single image / demo:** To run only the primary container (no DB, agent, or workers), build the image and use the single-container compose file. See **Single-container (demo) mode** in `docs/REBUILD.md` and the **Single-container and expansion workflow** there for initial config, bootstrap, and adding workers later.

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
│   ├── batch_jobs.json # Batch job records (flatfile backend)
│   ├── workers.json   # Worker registry (flatfile backend)
│   └── jobs.json      # Job queue (flatfile backend)
├── web/               # Flask web application (primary server)
│   ├── app.py         # Main Flask application (~4700 lines)
│   ├── scheduler.py   # APScheduler integration (batch + single schedules)
│   ├── job_router.py  # Smart job routing with tag-based targeting
│   ├── content_repo.py # Git content repository management
│   ├── storage/       # Storage backend abstraction
│   │   ├── __init__.py    # Factory function
│   │   ├── base.py        # Abstract interface (workers, jobs, inventory, schedules)
│   │   ├── flatfile.py    # JSON file storage
│   │   └── mongodb.py     # MongoDB storage
│   ├── templates/
│   │   ├── index.html         # Batch execution page (main)
│   │   ├── playbooks.html     # Individual playbook cards
│   │   ├── schedules.html     # Schedule management
│   │   ├── inventory.html     # CMDB with host wizard
│   │   ├── cluster.html       # Cluster dashboard
│   │   ├── job_status.html    # Live job status with log streaming
│   │   └── batch_live_log.html # Live batch job monitoring
│   └── static/
├── worker/            # Worker service (runs on worker nodes)
│   ├── __main__.py    # Worker entry point
│   ├── service.py     # Main worker service loop
│   ├── config.py      # Worker configuration
│   ├── api_client.py  # Primary server API client
│   ├── executor.py    # Ansible playbook executor
│   ├── sync.py        # Content sync from primary
│   └── sync_notify.py # WebSocket sync notifications
├── agent/             # AI agent (log review, playbook generation)
│   ├── service.py     # Flask agent service
│   ├── llm_client.py  # LLM (Ollama) client
│   ├── prompts.yaml   # Prompts for log review, playbook gen
│   └── rag.py         # RAG / vector store for context
├── tests/             # Test suite (93+ tests)
├── docs/              # Documentation
│   ├── ARCHITECTURE.md  # Single architecture reference (components, workflows, logs)
│   └── CLUSTER.md     # Cluster architecture guide
├── Dockerfile.worker  # Worker container image
└── docker-compose.yml # Primary + workers + MongoDB
```

## Documentation

- **[Architecture](docs/ARCHITECTURE.md)** - Single reference: components, workflows, logs and debugging (including agent)
- **Agent (LLM)**: Ollama runs **only in the `ollama` container** (do not run Ollama on the host). Default model is `qwen2.5-coder:3b`; use `1.5b` for lightest, `7b` for best quality. Change via `LLM_MODEL` in agent-service env. Pull: `docker compose exec -T ollama ollama pull qwen2.5-coder:3b`. Verify: `./scripts/verify-ollama.sh`. Logs: `docker compose logs ollama`.
- **[Usage Guide](docs/USAGE.md)** - Detailed interface walkthrough
- **[Adding Playbooks](docs/ADDING_PLAYBOOKS.md)** - Complete guide to creating playbooks
- **[Configuration](docs/CONFIGURATION.md)** - Inventory setup and SSH configuration
- **[API Reference](docs/API.md)** - REST API endpoints
- **[Troubleshooting](docs/TROUBLESHOOTING.md)** - Common issues and solutions

## Current Playbooks

Example playbooks included:

**General (Linux/Unix)**
- **hardware-inventory** - CPU, memory, disks, GPU detection
- **software-inventory** - Installed packages with versions
- **system-health** - Uptime, load, memory, disk usage, errors
- **service-status** - System services and their status
- **network-config** - Network interfaces, routing, DNS
- **disk-usage-analyzer** - Disk space analysis
- **change-user-password** - Change user password

**MikroTik RouterOS**
- **mikrotik-router-check** - Basic RouterOS connectivity check
- **collect_stats_routeros** - Collect stats from RouterOS
- **get_config_routeros** - Retrieve RouterOS configuration

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

**Status:** Cluster mode fully functional with comprehensive test coverage (93+ tests for cluster features)

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
See [Architecture](docs/ARCHITECTURE.md) and [CLUSTER.md](docs/CLUSTER.md) for the full system and cluster detail.

---

## Future Enhancements

### Infrastructure Improvements
- Mount inventory file to workers for target host access
- Configure SSH agent forwarding for workers
- Add health check endpoint to worker Dockerfile
- Support custom ansible.cfg per worker
- Support external workers (not in Docker network)

### Security
- Rotate registration tokens periodically
- Add TLS between workers and primary
- Implement job result signing/verification
- Add worker authentication beyond token
- Add authentication system (JWT, OAuth, or basic auth)
- User management and role-based access control

### Job Management
- Job cancellation (kill running playbook on worker)
- Job retry with configurable attempts
- Job timeout handling
- Job priority queuing (high/normal/low)

### Worker Management
- Manual worker enable/disable from dashboard
- Worker maintenance mode (drain jobs before shutdown)
- Worker auto-scaling based on queue depth
- Worker groups/pools for isolation

### Monitoring
- Prometheus metrics endpoint
- Grafana dashboard templates
- Alert rules for worker failures
- Job queue depth monitoring
- Host health monitoring
- Performance metrics (execution time trends)

### User Experience
- Email notifications on playbook completion
- Slack/Teams/Discord webhook integrations
- Mobile app or PWA support
- Variable substitution in playbooks via UI
- Conditional execution based on previous results
- Ansible Vault integration

### Documentation
- Video walkthrough/tutorial
- Interactive demo environment
- Community playbook repository
- Best practices guide for playbook authors

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

**Built with Claude Code** | Generated with Claude Opus 4.5
