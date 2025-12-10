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

**Status:** Production-ready for local use

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

## Future Enhancements / TODO

### Planned Features

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
- [ ] Multi-user playbook execution queue

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
