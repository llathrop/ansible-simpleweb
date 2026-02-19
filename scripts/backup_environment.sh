#!/bin/bash
#
# Environment Backup Script for Ansible SimpleWeb
# Backs up everything not in git before security implementation
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default backup directory
BACKUP_DIR="${1:-backups/pre-security-$(date +%Y%m%d-%H%M%S)}"

echo -e "${GREEN}=== Ansible SimpleWeb Environment Backup ===${NC}"
echo "Backup directory: $BACKUP_DIR"
echo ""

# Create backup directory
mkdir -p "$BACKUP_DIR"
echo -e "${GREEN}✓ Created backup directory${NC}"

# 1. Backup Docker volumes
echo -e "\n${YELLOW}--- Backing up Docker volumes ---${NC}"
VOLUMES=("mongodb_data" "agent_data" "ollama_data")

for volume in "${VOLUMES[@]}"; do
    # Check if volume exists
    if docker volume inspect "$volume" >/dev/null 2>&1; then
        echo "Backing up volume: $volume"
        docker run --rm \
            -v "${volume}:/data" \
            -v "$(pwd)/${BACKUP_DIR}:/backup" \
            alpine tar czf "/backup/${volume}.tar.gz" -C /data . 2>/dev/null
        echo -e "${GREEN}✓ Backed up $volume${NC}"
    else
        echo -e "${YELLOW}⚠ Volume $volume does not exist, skipping${NC}"
    fi
done

# 2. Backup configuration and data files
echo -e "\n${YELLOW}--- Backing up configuration and data files ---${NC}"

# Config directory
if [ -d "config" ]; then
    echo "Backing up config/"
    cp -r config "$BACKUP_DIR/config"
    echo -e "${GREEN}✓ Backed up config/${NC}"
fi

# Logs directory (only metadata, not full logs if too large)
if [ -d "logs" ]; then
    echo "Backing up logs/ (checking size)"
    LOGS_SIZE=$(du -sm logs 2>/dev/null | cut -f1)
    if [ "$LOGS_SIZE" -lt 1000 ]; then
        cp -r logs "$BACKUP_DIR/logs"
        echo -e "${GREEN}✓ Backed up logs/ (${LOGS_SIZE}MB)${NC}"
    else
        echo -e "${YELLOW}⚠ logs/ is ${LOGS_SIZE}MB, creating list instead of full backup${NC}"
        find logs -type f > "$BACKUP_DIR/logs-file-list.txt"
        echo -e "${GREEN}✓ Saved logs file list${NC}"
    fi
fi

# SSH keys directory
if [ -d "ssh-keys" ]; then
    echo "Backing up ssh-keys/"
    cp -r ssh-keys "$BACKUP_DIR/ssh-keys"
    echo -e "${GREEN}✓ Backed up ssh-keys/${NC}"
fi

# .ssh directory (if present)
if [ -d ".ssh" ]; then
    echo "Backing up .ssh/"
    cp -r .ssh "$BACKUP_DIR/.ssh"
    echo -e "${GREEN}✓ Backed up .ssh/${NC}"
fi

# 3. Backup container images (optional, commented out by default)
echo -e "\n${YELLOW}--- Backing up container images (optional) ---${NC}"
# Uncomment these lines if you want to backup images
# docker save ansible-simpleweb:latest -o "$BACKUP_DIR/ansible-simpleweb-image.tar" 2>/dev/null || echo "Image ansible-simpleweb:latest not found"
# docker save ansible-worker:latest -o "$BACKUP_DIR/ansible-worker-image.tar" 2>/dev/null || echo "Image ansible-worker:latest not found"
# docker save ansible-agent:latest -o "$BACKUP_DIR/ansible-agent-image.tar" 2>/dev/null || echo "Image ansible-agent:latest not found"
echo -e "${YELLOW}⚠ Image backup disabled (can be rebuilt)${NC}"

# 4. Backup database exports
echo -e "\n${YELLOW}--- Backing up database exports ---${NC}"

# MongoDB dump
if docker ps | grep -q ansible-simpleweb-mongodb; then
    echo "Creating MongoDB dump"
    docker compose exec -T mongodb mongodump --archive=/tmp/backup.archive --db=ansible_simpleweb 2>/dev/null || {
        echo -e "${YELLOW}⚠ MongoDB dump failed (no auth or database empty?)${NC}"
    }
    docker cp ansible-simpleweb-mongodb:/tmp/backup.archive "$BACKUP_DIR/mongodb-backup.archive" 2>/dev/null && {
        echo -e "${GREEN}✓ MongoDB dump created${NC}"
    } || {
        echo -e "${YELLOW}⚠ MongoDB dump copy failed${NC}"
    }
    # Cleanup temp file
    docker compose exec -T mongodb rm -f /tmp/backup.archive 2>/dev/null || true
else
    echo -e "${YELLOW}⚠ MongoDB container not running, skipping dump${NC}"
fi

# Flatfile storage (if using flatfile backend)
if [ -f "config/schedules.json" ] || [ -f "config/inventory.json" ]; then
    echo "Flatfile storage detected (already backed up with config/)"
    echo -e "${GREEN}✓ Flatfile storage included in config backup${NC}"
fi

# 5. Current state snapshot
echo -e "\n${YELLOW}--- Creating current state snapshot ---${NC}"

# Docker compose state
echo "Saving docker compose state"
docker compose ps > "$BACKUP_DIR/docker-compose-state.txt" 2>/dev/null || {
    echo -e "${YELLOW}⚠ Could not capture docker compose ps${NC}"
}
docker compose config > "$BACKUP_DIR/docker-compose-resolved.yml" 2>/dev/null || {
    echo -e "${YELLOW}⚠ Could not capture docker compose config${NC}"
}

# Git status
echo "Saving git status"
git status > "$BACKUP_DIR/git-status.txt" 2>/dev/null || {
    echo -e "${YELLOW}⚠ Could not capture git status${NC}"
}
git log -10 --oneline > "$BACKUP_DIR/git-log.txt" 2>/dev/null || {
    echo -e "${YELLOW}⚠ Could not capture git log${NC}"
}

# Get current branch
git branch --show-current > "$BACKUP_DIR/git-branch.txt" 2>/dev/null || echo "unknown" > "$BACKUP_DIR/git-branch.txt"

echo -e "${GREEN}✓ State snapshot created${NC}"

# 6. Create backup manifest
echo -e "\n${YELLOW}--- Creating backup manifest ---${NC}"

cat > "$BACKUP_DIR/BACKUP_MANIFEST.txt" << EOF
Ansible SimpleWeb Environment Backup
=====================================

Backup Date: $(date)
Backup Location: $BACKUP_DIR
Git Branch: $(cat "$BACKUP_DIR/git-branch.txt")
Git Commit: $(git rev-parse HEAD 2>/dev/null || echo "unknown")

Contents:
---------
$(ls -lh "$BACKUP_DIR")

Docker Volumes:
--------------
$(for vol in "${VOLUMES[@]}"; do
    if [ -f "$BACKUP_DIR/${vol}.tar.gz" ]; then
        echo "  ✓ ${vol}.tar.gz ($(du -h "$BACKUP_DIR/${vol}.tar.gz" | cut -f1))"
    else
        echo "  ✗ ${vol}.tar.gz (not found)"
    fi
done)

Configuration Files:
-------------------
$(if [ -d "$BACKUP_DIR/config" ]; then echo "  ✓ config/ directory"; else echo "  ✗ config/ not found"; fi)
$(if [ -d "$BACKUP_DIR/logs" ]; then echo "  ✓ logs/ directory"; else if [ -f "$BACKUP_DIR/logs-file-list.txt" ]; then echo "  ✓ logs file list"; else echo "  ✗ logs not backed up"; fi; fi)
$(if [ -d "$BACKUP_DIR/ssh-keys" ]; then echo "  ✓ ssh-keys/ directory"; else echo "  ✗ ssh-keys/ not found"; fi)
$(if [ -d "$BACKUP_DIR/.ssh" ]; then echo "  ✓ .ssh/ directory"; else echo "  ✗ .ssh/ not found"; fi)

Database Exports:
----------------
$(if [ -f "$BACKUP_DIR/mongodb-backup.archive" ]; then echo "  ✓ MongoDB dump ($(du -h "$BACKUP_DIR/mongodb-backup.archive" | cut -f1))"; else echo "  ✗ MongoDB dump not created"; fi)

State Snapshots:
---------------
$(if [ -f "$BACKUP_DIR/docker-compose-state.txt" ]; then echo "  ✓ docker-compose-state.txt"; else echo "  ✗ docker-compose-state.txt"; fi)
$(if [ -f "$BACKUP_DIR/docker-compose-resolved.yml" ]; then echo "  ✓ docker-compose-resolved.yml"; else echo "  ✗ docker-compose-resolved.yml"; fi)
$(if [ -f "$BACKUP_DIR/git-status.txt" ]; then echo "  ✓ git-status.txt"; else echo "  ✗ git-status.txt"; fi)
$(if [ -f "$BACKUP_DIR/git-log.txt" ]; then echo "  ✓ git-log.txt"; else echo "  ✗ git-log.txt"; fi)

Total Backup Size:
-----------------
$(du -sh "$BACKUP_DIR" | cut -f1)

Restore Instructions:
--------------------
See scripts/restore_environment.sh for restore procedure.

IMPORTANT: Verify this backup before proceeding with security implementation!

EOF

echo -e "${GREEN}✓ Backup manifest created${NC}"

# Display manifest
echo -e "\n${GREEN}=== Backup Complete ===${NC}"
cat "$BACKUP_DIR/BACKUP_MANIFEST.txt"

echo -e "\n${GREEN}✓ Backup created successfully at: $BACKUP_DIR${NC}"
echo -e "${YELLOW}⚠ IMPORTANT: Test restore before proceeding with implementation${NC}"

exit 0
