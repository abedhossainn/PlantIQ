#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${1:-llm}"

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD="docker-compose"
else
  echo "❌ Docker Compose not found; cannot verify LLM GPU runtime." >&2
  exit 1
fi

CONTAINER_ID="$($COMPOSE_CMD ps -q "$SERVICE_NAME" 2>/dev/null || true)"
if [[ -z "${CONTAINER_ID}" ]]; then
  echo "❌ Compose service '$SERVICE_NAME' is not running; cannot verify GPU runtime." >&2
  echo "   Start it first: $COMPOSE_CMD up -d $SERVICE_NAME" >&2
  exit 1
fi

CONTAINER_NAME="$(docker inspect --format '{{.Name}}' "$CONTAINER_ID" | sed 's#^/##')"
RUNTIME="$(docker inspect --format '{{.HostConfig.Runtime}}' "$CONTAINER_ID")"

if [[ "${RUNTIME}" != "nvidia" ]]; then
  echo "❌ LLM container '${CONTAINER_NAME}' is running with runtime='${RUNTIME}' (expected 'nvidia')." >&2
  echo "   Fix docker-compose service '$SERVICE_NAME' by setting: runtime: nvidia" >&2
  echo "   Then recreate: $COMPOSE_CMD up -d --force-recreate $SERVICE_NAME" >&2
  exit 1
fi

if ! docker exec "$CONTAINER_NAME" sh -lc 'test -e /dev/nvidiactl && test -e /dev/nvidia-uvm'; then
  echo "❌ NVIDIA device nodes are missing inside '${CONTAINER_NAME}'." >&2
  echo "   Container has nvidia runtime configured, but GPU devices are not accessible." >&2
  exit 1
fi

if docker logs --since 15m "$CONTAINER_NAME" 2>&1 | grep -q "ggml_cuda_init: failed to initialize CUDA"; then
  echo "❌ Recent Ollama logs show CUDA initialization failure." >&2
  echo "   Check NVIDIA Container Toolkit / driver status and recreate '$SERVICE_NAME'." >&2
  exit 1
fi

echo "✅ LLM GPU runtime check passed for '${CONTAINER_NAME}'"
echo "   runtime=${RUNTIME} and NVIDIA device nodes are present"
