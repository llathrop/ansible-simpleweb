#!/bin/bash
#
# Environment Restore Script for Ansible SimpleWeb
# Restores backup created by backup_environment.sh
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check for backup directory argument
if [ -z "$1" ]; then
    echo -e "${RED}Error: Backup directory required${NC}"
    echo "Usage: $0 <backup-directory>"
    echo ""
    echo "Available backups:"
    ls -d backups/*/ 2>/dev/null || echo "  No backups found"
    exit 1
fi

BACKUP_DIR="$1"

if [ ! -d "$BACKUP_DIR" ]; then
    echo -e "${RED}Error: Backup directory not found: $BACKUP_DIR${NC}"
    exit 1
fi

echo -e "${GREEN}=== Ansible SimpleWeb Environment Restore ===${NC}"
echo "Backup directory: $BACKUP_DIR"
echo ""

# Display backup manifest if it exists
if [ -f "$BACKUP_DIR/BACKUP_MANIFEST.txt" ]; then
    echo -e "${YELLOW}--- Backup Manifest ---${NC}"
    cat "$BACKUP_DIR/BACKUP_MANIFEST.txt" | head -20
    echo ""
fi

# Confirmation prompt
read -p "Are you sure you want to restore from this backup? This will OVERWRITE current data! (yes/no): " -r
echo
if [[ ! $REPLY =~ ^yes$ ]]; then
    echo "Restore cancelled"
    exit 1
fi

# Stop services first
echo -e "\n${YELLOW}--- Stopping Docker services ---${NC}"
docker compose down || echo -e "${YELLOW}⚠ Services may already be stopped${NC}"
echo -e "${GREEN}✓ Services stopped${NC}"

# Restore Docker volumes
echo -e "\n${YELLOW}--- Restoring Docker volumes ---${NC}"
VOLUMES=("mongodb_data" "agent_data" "ollama_data")

for volume in "${VOLUMES[@]}"; do
    if [ -f "$BACKUP_DIR/${volume}.tar.gz" ]; then
        echo "Restoring volume: $volume"

        # Remove existing volume if it exists
        docker volume rm "$volume" 2>/dev/null || true

        # Create volume
        docker volume create "$volume"

        # Restore data
        docker run --rm \
            -v "${volume}:/data" \
            -v "$(pwd)/${BACKUP_DIR}:/backup" \
            alpine sh -c "cd /data && tar xzf /backup/${volume}.tar.gz"

        echo -e "${GREEN}✓ Restored $volume${NC}"
    else
        echo -e "${YELLOW}⚠ Volume backup ${volume}.tar.gz not found, skipping${NC}"
    fi
done

# Restore configuration and data files
echo -e "\n${YELLOW}--- Restoring configuration and data files ---${NC}"

# Config directory
if [ -d "$BACKUP_DIR/config" ]; then
    echo "Restoring config/"
    rm -rf config
    cp -r "$BACKUP_DIR/config" config
    echo -e "${GREEN}✓ Restored config/${NC}"
fi

# Logs directory
if [ -d "$BACKUP_DIR/logs" ]; then
    echo "Restoring logs/"
    rm -rf logs
    cp -r "$BACKUP_DIR/logs" logs
    echo -e "${GREEN}✓ Restored logs/${NC}"
elif [ -f "$BACKUP_DIR/logs-file-list.txt" ]; then
    echo -e "${YELLOW}⚠ Only logs file list available (logs not restored)${NC}"
fi

# SSH keys directory
if [ -d "$BACKUP_DIR/ssh-keys" ]; then
    echo "Restoring ssh-keys/"
    rm -rf ssh-keys
    cp -r "$BACKUP_DIR/ssh-keys" ssh-keys
    echo -e "${GREEN}✓ Restored ssh-keys/${NC}"
fi

# .ssh directory
if [ -d "$BACKUP_DIR/.ssh" ]; then
    echo "Restoring .ssh/"
    rm -rf .ssh
    cp -r "$BACKUP_DIR/.ssh" .ssh
    chmod 700 .ssh
    chmod 600 .ssh/* 2>/dev/null || true
    echo -e "${GREEN}✓ Restored .ssh/${NC}"
fi

# Restore database
echo -e "\n${YELLOW}--- Restoring database ---${NC}"

if [ -f "$BACKUP_DIR/mongodb-backup.archive" ]; then
    echo "MongoDB dump found, will restore after starting services"
    RESTORE_MONGODB=true
else
    echo -e "${YELLOW}⚠ No MongoDB dump found${NC}"
    RESTORE_MONGODB=false
fi

# Start services
echo -e "\n${YELLOW}--- Starting Docker services ---${NC}"
docker compose up -d
echo -e "${GREEN}✓ Services started${NC}"

# Wait for MongoDB to be ready
if [ "$RESTORE_MONGODB" = true ]; then
    echo "Waiting for MongoDB to be ready..."
    sleep 10

    # Copy backup to MongoDB container
    echo "Copying MongoDB backup to container"
    docker cp "$BACKUP_DIR/mongodb-backup.archive" ansible-simpleweb-mongodb:/tmp/backup.archive

    # Restore MongoDB
    echo "Restoring MongoDB database"
    docker compose exec -T mongodb mongorestore --archive=/tmp/backup.archive --drop

    # Cleanup
    docker compose exec -T mongodb rm -f /tmp/backup.archive

    echo -e "${GREEN}✓ MongoDB database restored${NC}"
fi

# Summary
echo -e "\n${GREEN}=== Restore Complete ===${NC}"
echo ""
echo "Services have been restored from backup: $BACKUP_DIR"
echo ""
echo "Current status:"
docker compose ps

echo -e "\n${GREEN}✓ Environment restored successfully${NC}"
echo -e "${YELLOW}⚠ Verify services are running correctly:${NC}"
echo "  - Check web: http://localhost:3001"
echo "  - Check logs: docker compose logs"

exit 0
