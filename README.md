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

### Step 2: Configure and Test Playbooks 🔄 IN PROGRESS

**Planned Playbooks**:
- Hardware inventory (CPU, memory, drives, GPU detection)
- Software inventory (Ubuntu package list)
- Additional test playbooks (TBD)

**Status**: Not started

---

### Step 3: Web Interface Development 📋 PLANNED

**Planned Features**:
- List available playbooks
- Run button for each playbook
- View log button for each playbook
- Status indicator (running/ready)
- Page refresh functionality

**Status**: Not started

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

```bash
docker-compose exec -T ansible-web ansible-playbook playbooks/your-playbook.yml
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
