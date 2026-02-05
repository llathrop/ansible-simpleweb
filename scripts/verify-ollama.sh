#!/usr/bin/env bash
# Verify the Ollama container is running and responds. Uses Docker network (ollama:11434).
# Port 11434 is NOT published to the host to avoid triggering host Ollama.
# Exit 0 if OK, 1 otherwise. Part of project ownership of the ollama service.
set -e

COMPOSE_CMD="${COMPOSE_CMD:-docker compose}"
# Use ansible-web to curl (same network as ollama); no localhost:11434 on host
CURL_CMD="$COMPOSE_CMD exec -T ansible-web curl -sf"

echo "Checking Ollama container (part of this project)..."
if ! $COMPOSE_CMD ps ollama 2>/dev/null | grep -q 'Up'; then
  echo "Ollama container is not running. Start with: $COMPOSE_CMD up -d ollama"
  exit 1
fi

echo "Container running. Checking API (via Docker network)..."
if ! $CURL_CMD --connect-timeout 5 http://ollama:11434/api/tags >/dev/null 2>&1; then
  echo "Ollama API at http://ollama:11434 did not respond (from ansible-web container)"
  exit 1
fi
echo "API /api/tags OK."

echo "Running a minimal generate (smoke test)..."
RESP=$($CURL_CMD --connect-timeout 10 --max-time 60 -X POST http://ollama:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5-coder:1.5b","messages":[{"role":"user","content":"Reply with exactly: OK"}],"max_tokens":10}' 2>/dev/null) || true
if echo "$RESP" | grep -q '"choices"'; then
  echo "Generate OK. Ollama container is healthy and responding."
  exit 0
fi
echo "API reachable; generate failed (model may not be pulled). Pull with: $COMPOSE_CMD exec ollama ollama run qwen2.5-coder:1.5b"
echo "Logs: $COMPOSE_CMD logs ollama"
exit 0
