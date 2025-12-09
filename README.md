# Ansible Simple Web Interface

A lightweight, Docker-based web interface for managing and executing Ansible playbooks. Run playbooks with a single click, monitor execution status in real-time, and view logs through a clean, modern web UI.

## Features

- 🚀 **One-Click Execution** - Run any playbook with a single button click
- 🎯 **Multi-Host Support** - Target individual hosts or groups via dropdown selection
- 📊 **Real-Time Status** - Live status updates (Ready/Running/Completed/Failed)
- 📝 **Log Management** - Automatic log capture with timestamped filenames
- 🔍 **Log Viewer** - Browse and view all execution logs in the browser
- 🔌 **REST API** - JSON endpoints for external integrations
- 🐳 **Fully Containerized** - Rocky Linux 9 with Ansible 8.7.0 pre-configured
- 🔒 **Localhost First** - Secure by default, ready for authentication later

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
│   └── hosts          # Main inventory file
├── logs/              # Playbook execution logs (auto-generated)
├── web/               # Flask web application
│   ├── app.py
│   └── templates/
└── docker-compose.yml
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
