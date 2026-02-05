#!/usr/bin/env bash
# Run the full test suite in a virtualenv so all dependencies (Flask, etc.) are available.
# Per memory.md §8: do not skip tests; use venv or container and run real tests.
#
# Usage:
#   ./scripts/run_tests.sh           # create venv if needed, install deps, run pytest
#   ./scripts/run_tests.sh --no-venv # run pytest with current python (must have deps)
#
set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT="$PWD"
VENV_DIR="${VENV_DIR:-$PROJECT_ROOT/.venv}"

run_with_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        echo "Creating venv at $VENV_DIR ..."
        python3 -m venv "$VENV_DIR"
    fi
    echo "Using venv: $VENV_DIR"
    "$VENV_DIR/bin/pip" install -q --upgrade pip
    "$VENV_DIR/bin/pip" install -q -r requirements.txt
    "$VENV_DIR/bin/pip" install -q pytest openai psutil
    [ -f agent/requirements.txt ] && "$VENV_DIR/bin/pip" install -q -r agent/requirements.txt || true
    # So that web.app can resolve scheduler, storage, etc. (same as Docker: app runs with web on path)
    export PYTHONPATH="${PROJECT_ROOT}/web:${PROJECT_ROOT}:${PYTHONPATH:-}"
    export PATH="$VENV_DIR/bin:$PATH"
    exec "$VENV_DIR/bin/python" -m pytest tests/ -v "$@"
}

if [ "$1" = "--no-venv" ]; then
    shift
    export PYTHONPATH="${PROJECT_ROOT}/web:${PROJECT_ROOT}:${PYTHONPATH:-}"
    exec python3 -m pytest tests/ -v "$@"
fi
run_with_venv "$@"
