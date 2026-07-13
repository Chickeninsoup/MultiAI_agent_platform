#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <agent-name> <task>"
  exit 1
fi

AGENT_NAME="$1"
AGENT_TASK="$2"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="$PROJECT_DIR/workspaces/$AGENT_NAME"
IMAGE_NAME="private-agent-runtime:0.1"

if sudo docker ps -a \
  --format '{{.Names}}' |
  grep -qx "$AGENT_NAME"; then
  echo "Error: Container '$AGENT_NAME' already exists."
  echo "Remove it before reusing the name."
  exit 1
fi

mkdir -p "$WORKSPACE_DIR"

echo "Starting agent: $AGENT_NAME"
echo "Task: $AGENT_TASK"
echo "Workspace: $WORKSPACE_DIR"

sudo docker run -d \
  --name "$AGENT_NAME" \
  --memory=512m \
  --cpus=1 \
  -e AGENT_NAME="$AGENT_NAME" \
  -e AGENT_TASK="$AGENT_TASK" \
  -v "$WORKSPACE_DIR:/workspace" \
  "$IMAGE_NAME"

echo "Agent started successfully."
echo "Use this command to view logs:"
echo "  ./scripts/logs-agent.sh $AGENT_NAME"
