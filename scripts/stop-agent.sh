#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <agent-name>"
  exit 1
fi

AGENT_NAME="$1"

if ! sudo docker ps \
  --format '{{.Names}}' |
  grep -qx "$AGENT_NAME"; then
  echo "Agent '$AGENT_NAME' is not running."
  exit 0
fi

sudo docker stop "$AGENT_NAME"

echo "Agent '$AGENT_NAME' stopped."
