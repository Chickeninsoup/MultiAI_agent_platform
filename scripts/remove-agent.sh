#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <agent-name>"
  exit 1
fi

AGENT_NAME="$1"

if ! sudo docker ps -a \
  --format '{{.Names}}' |
  grep -qx "$AGENT_NAME"; then
  echo "Agent '$AGENT_NAME' does not exist."
  exit 0
fi

if sudo docker ps \
  --format '{{.Names}}' |
  grep -qx "$AGENT_NAME"; then
  sudo docker stop "$AGENT_NAME"
fi

sudo docker rm "$AGENT_NAME"

echo "Agent container '$AGENT_NAME' removed."
echo "Workspace was preserved."
