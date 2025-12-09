# Ansible Simple Web Interface

A Docker-based web interface for managing and running Ansible playbooks with a simple Flask frontend.

## Project Overview

This project provides a web interface to list, run, and monitor Ansible playbooks. The interface runs locally and allows users to execute playbooks with a single click and view execution logs.

## Architecture

- **Base OS**: Rocky Linux 9
- **Configuration Management**: Ansible 8.7.0 (ansible-core 2.15.13)
- **Web Framework**: Flask 3.0.0
- **Container**: Docker with docker-compose
- **Port**: 3001 (localhost only)

## Project Structure

```
ansible-simpleweb/
├── Dockerfile               # Rocky Linux 9, Ansible, Flask setup
├── docker-compose.yml       # Container orchestration config
├── requirements.txt         # Python dependencies
├── ansible.cfg              # Ansible configuration (SSH key + password support)
├── inventory/
│   └── hosts               # Inventory file (localhost + remote placeholder)
├── playbooks/              # Directory for Ansible playbooks
├── logs/                   # Playbook execution logs
│   └── ansible.log        # Ansible log file
└── web/
    └── app.py             # Flask web application
```

## Features

- **SSH Authentication**: Supports both SSH keys (mounted from ~/.ssh) and password authentication (using sshpass)
- **Volume Mounts**: All directories mounted for easy editing without rebuilding container
- **Ansible Configuration**:
  - Proper logging to ./logs/ansible.log
  - Host key checking disabled for easier setup
  - Privilege escalation configured
- **Development Mode**: Flask runs in development mode with auto-reload

## Setup and Installation

### Prerequisites
- Docker
- docker-compose

### Starting the Service

```bash
# Build and start the container
docker-compose build
docker-compose up -d

# Check container status
docker-compose ps

# View logs
docker-compose logs -f
```

### Accessing the Interface

Open your browser to: http://localhost:3001

### Stopping the Service

```bash
docker-compose down
```

## Development Progress

### Step 1: Docker Container Setup ✅ COMPLETE

**Completed**: Initial project setup with Docker container, Ansible, and Flask web server.

**What's Working**:
- Docker Container: Rocky Linux 9 based container with Ansible and Flask
- Web Server: Flask running on http://localhost:3001
- Ansible: Version 8.7.0 installed and tested
- Git Repository: Initialized with version control

**Test Results**:
- Container Status: Running
- Flask endpoint: http://localhost:3001 - Responding correctly
- Ansible connectivity: localhost ping successful

**Git Commits**:
1. Initial project setup
2. Configuration fixes (Ansible version, network mode)
3. Added project documentation

---

### Step 2: Configure and Test Playbooks ✅ COMPLETE

**Completed**: Five test playbooks created, tested, and verified with proper JSON output.

**Implemented Playbooks**:
1. **hardware-inventory.yml** - Hardware inventory collection
   - CPU information (model, cores, vcpus, architecture)
   - Memory information (total, free, swap)
   - Disk information (devices, mounts, sizes)
   - GPU detection (NVIDIA, AMD, Intel)
   - System information (distribution, kernel, virtualization)

2. **software-inventory.yml** - Software package inventory
   - All installed packages with versions
   - Support for both Debian/Ubuntu (apt) and RedHat/Rocky (dnf/yum)
   - Shows first 100 packages for brevity
   - Package manager information

3. **system-health.yml** - System health monitoring
   - Uptime (days, hours, minutes)
   - Load averages (1min, 5min, 15min)
   - Memory usage (total, used, free, percentage)
   - Swap usage
   - Disk usage for all mounts (with percentages)
   - Recent system errors from logs

4. **service-status.yml** - Service status check
   - List of all system services
   - Running services count and details
   - Failed services (systemd only)
   - Enabled services list
   - Service manager type

5. **network-config.yml** - Network configuration
   - Default IPv4 and IPv6 addresses
   - Default gateway
   - DNS servers
   - Network interfaces list
   - Routing table
   - Listening ports

**Helper Script**:
- `run-playbook.sh` - Executes playbooks with proper timestamped logging
- Log format: `<playbookname>-YYYYMMDD-HHMMSS.log`

**Test Results**:
- All 5 playbooks executed successfully on localhost
- JSON output format validated
- Log files created with proper naming convention
- All logs saved to `logs/` directory

**Status**: Complete and ready for web interface integration

---

### Step 3: Web Interface Development ✅ COMPLETE

**Completed**: Full-featured web interface for managing and running Ansible playbooks.

**Implemented Features**:
1. **Main Dashboard** (`/`)
   - Grid layout showing all available playbooks
   - Real-time status indicators (Ready, Running, Completed, Failed)
   - Run button for each playbook
   - View latest log button
   - Last run timestamp
   - Auto-refresh status every 3 seconds

2. **Playbook Execution**
   - One-click playbook execution via `/run/<playbook>`
   - Background thread execution (non-blocking)
   - Automatic redirect to dashboard after triggering
   - Prevents duplicate runs while playbook is running

3. **Log Management**
   - All logs page (`/logs`) with sortable list
   - Individual log viewer (`/logs/<logfile>`)
   - Monospace terminal-style log display
   - File size and modification time
   - Quick navigation between pages

4. **API Endpoints**
   - `/api/playbooks` - JSON list of all playbooks with status
   - `/api/status` - Current status of all playbooks
   - RESTful design ready for external integrations

5. **User Interface**
   - Clean, modern design
   - Responsive grid layout
   - Color-coded status badges
   - Pulse animation for running playbooks
   - Mobile-friendly

**Security**:
- Localhost only (0.0.0.0:3001)
- No authentication (local access)
- Ready for authentication layer addition

**Status**: Complete and operational at http://localhost:3001

---

## Testing

### Verify Ansible Installation

```bash
docker-compose exec -T ansible-web ansible --version
```

### Test Localhost Connectivity

```bash
docker-compose exec -T ansible-web ansible localhost -m ping
```

### Run a Playbook

Using the helper script (recommended - includes timestamped logging):
```bash
# Copy the script to the container first
docker cp run-playbook.sh ansible-simpleweb:/app/

# Run a playbook
docker-compose exec -T ansible-web bash /app/run-playbook.sh hardware-inventory
docker-compose exec -T ansible-web bash /app/run-playbook.sh software-inventory
docker-compose exec -T ansible-web bash /app/run-playbook.sh system-health
docker-compose exec -T ansible-web bash /app/run-playbook.sh service-status
docker-compose exec -T ansible-web bash /app/run-playbook.sh network-config
```

Or run directly with ansible-playbook:
```bash
docker-compose exec -T ansible-web ansible-playbook playbooks/hardware-inventory.yml
```

### View Playbook Logs

```bash
# List all logs
ls -lh logs/

# View a specific log
cat logs/hardware-inventory-20251208-234958.log
```

## Troubleshooting

### Container won't start
- Check Docker is running: `docker ps`
- Check logs: `docker-compose logs`

### Permission issues with SSH keys
- Ensure ~/.ssh directory has correct permissions (700)
- Ensure private keys have correct permissions (600)

### Ansible connection issues
- Check inventory file: `inventory/hosts`
- Verify SSH connectivity manually
- Check Ansible logs: `logs/ansible.log`

## Contributing

This project uses git for version control. Each significant change should be committed with a descriptive commit message.

## License

Internal use only.
