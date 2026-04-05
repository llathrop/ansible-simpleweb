# Ansible SimpleWeb - Production Setup Notes

## Environment Overview
- **Installation Directory**: `/opt/ansible-simpleweb`
- **System User**: `ansible-simpleweb` (member of `docker` group)
- **Primary Access Port**: `3001` (HTTP) / `3443` (HTTPS if enabled)
- **Initial Admin User**: `admin`
- **Initial Admin Password**: `admin-pass-789` (set in `docker-compose.yml`)

## Architecture & Configuration
- **Storage Backend**: `flatfile` (JSON files in `/app/config/`)
  - *Note*: Switched from MongoDB due to ARM hardware incompatibility with MongoDB 5.0+.
- **Cluster Mode**: `primary` with 3 integrated workers (`worker-1`, `worker-2`, `worker-3`).
- **Agent Service**: Enabled, using Ollama (qwen2.5-coder:3b) for log review and assistance.
- **Content Repository**: Local git-based tracking at `/app/.content-repo`.

## Management Commands
- **Start/Stop Stack**:
  ```bash
  sudo -u ansible-simpleweb bash -c "cd /opt/ansible-simpleweb && docker compose up -d"
  sudo -u ansible-simpleweb bash -c "cd /opt/ansible-simpleweb && docker compose down"
  ```
- **View Logs**:
  ```bash
  sudo -u ansible-simpleweb bash -c "cd /opt/ansible-simpleweb && docker compose logs -f ansible-web"
  ```
- **Update/Rebuild**:
  ```bash
  sudo -u ansible-simpleweb bash -c "cd /opt/ansible-simpleweb && git pull && docker compose up -d --build"
  ```

## Important Paths
- **Playbooks**: `/opt/ansible-simpleweb/playbooks/`
- **Inventory**: `/opt/ansible-simpleweb/inventory/`
- **Logs**: `/opt/ansible-simpleweb/logs/`
- **Configuration**: `/opt/ansible-simpleweb/config/` (contains JSON state files)
- **SSH Keys**: `/opt/ansible-simpleweb/ssh-keys/` (uploaded) and `~/.ssh/` (mounted from host)

## Troubleshooting
- **DNS/Networking**: Workers and Agent use container names (`ansible-simpleweb`, `ollama`) to communicate.
- **MongoDB**: If re-enabling, ensure the host CPU supports ARMv8.2-A (LSE/FEAT_LSE).
