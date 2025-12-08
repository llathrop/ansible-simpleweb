#!/bin/bash
# Helper script to run Ansible playbooks with proper logging

if [ $# -lt 1 ]; then
    echo "Usage: $0 <playbook-name> [additional-ansible-args]"
    echo "Example: $0 hardware-inventory"
    exit 1
fi

PLAYBOOK_NAME="$1"
shift  # Remove first argument, keep any additional args

# Generate timestamp
TIMESTAMP=$(date +"%Y%m%d-%H%M%S")

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

# Create log filename
LOG_FILE="logs/${PLAYBOOK_NAME}-${TIMESTAMP}.log"

# Run playbook and capture output
echo "Running playbook: ${PLAYBOOK_FILE}"
echo "Log file: ${LOG_FILE}"
echo "----------------------------------------"

ansible-playbook "${PLAYBOOK_FILE}" "$@" 2>&1 | tee "${LOG_FILE}"

# Capture exit status
EXIT_STATUS=${PIPESTATUS[0]}

echo "----------------------------------------"
echo "Playbook execution completed with exit status: ${EXIT_STATUS}"
echo "Log saved to: ${LOG_FILE}"

exit ${EXIT_STATUS}
