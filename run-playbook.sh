#!/bin/bash
# Helper script to run Ansible playbooks with proper logging
# Supports two modes:
#   Legacy: $0 <playbook-name> [ansible-args]  (writes own log via tee)
#   Stream: $0 --stream <playbook-name> [ansible-args]  (stdout only, caller handles logging)

STREAM_MODE=false
if [ "$1" = "--stream" ]; then
    STREAM_MODE=true
    shift
fi

if [ $# -lt 1 ]; then
    echo "Usage: $0 [--stream] <playbook-name> [additional-ansible-args]"
    echo "Example: $0 hardware-inventory"
    echo "Example: $0 --stream hardware-inventory -l webservers"
    exit 1
fi

PLAYBOOK_NAME="$1"
shift  # Remove first argument, keep any additional args

# Determine playbook file
if [ -f "playbooks/${PLAYBOOK_NAME}.yml" ]; then
    PLAYBOOK_FILE="playbooks/${PLAYBOOK_NAME}.yml"
elif [ -f "playbooks/${PLAYBOOK_NAME}" ]; then
    PLAYBOOK_FILE="playbooks/${PLAYBOOK_NAME}"
    PLAYBOOK_NAME=$(basename "${PLAYBOOK_NAME}" .yml)
else
    echo "Error: Playbook not found: ${PLAYBOOK_NAME}"
    exit 1
fi

# Force unbuffered output from Ansible (Python)
export PYTHONUNBUFFERED=1

if [ "$STREAM_MODE" = true ]; then
    # Stream mode: output to stdout only, caller handles logging
    # Use stdbuf for additional line-buffering guarantee
    exec stdbuf -oL ansible-playbook "${PLAYBOOK_FILE}" "$@" 2>&1
else
    # Legacy mode: write log file via tee
    TIMESTAMP=$(date +"%Y%m%d-%H%M%S")
    LOG_FILE="logs/${PLAYBOOK_NAME}-${TIMESTAMP}.log"

    echo "Running playbook: ${PLAYBOOK_FILE}"
    echo "Log file: ${LOG_FILE}"
    echo "----------------------------------------"

    stdbuf -oL ansible-playbook "${PLAYBOOK_FILE}" "$@" 2>&1 | tee "${LOG_FILE}"

    EXIT_STATUS=${PIPESTATUS[0]}

    echo "----------------------------------------"
    echo "Playbook execution completed with exit status: ${EXIT_STATUS}"
    echo "Log saved to: ${LOG_FILE}"

    exit ${EXIT_STATUS}
fi
