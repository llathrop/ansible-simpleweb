#!/bin/bash

# Ansible SimpleWeb Rebuild Helper
# Usage: ./rebuild.sh [--workers|--web|--all]

set -e

show_help() {
    echo "Usage: ./rebuild.sh [OPTION]"
    echo ""
    echo "Options:"
    echo "  --workers    Restart worker nodes (fast, for worker/*.py changes)"
    echo "  --web        Restart web node (fast, usually auto-reloads)"
    echo "  --all        Full rebuild & restart (slow, for requirements.txt/Dockerfile)"
    echo "  --help       Show this help message"
}

if [ "$1" == "--workers" ]; then
    echo "Restarting workers..."
    docker-compose restart worker-1 worker-2 worker-3
    echo "Done."

elif [ "$1" == "--web" ]; then
    echo "Restarting web service..."
    docker-compose restart ansible-web
    echo "Done."

elif [ "$1" == "--all" ]; then
    echo "Rebuilding and restarting all services..."
    docker-compose down
    docker-compose up -d --build
    echo "Done. Services are starting up."

elif [ "$1" == "--help" ] || [ -z "$1" ]; then
    show_help

else
    echo "Unknown option: $1"
    show_help
    exit 1
fi
