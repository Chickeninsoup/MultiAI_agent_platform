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
  exit 1
fi

sudo docker inspect \
  --format 'Name: {{.Name}}
Status: {{.State.Status}}
Exit code: {{.State.ExitCode}}
Started at: {{.State.StartedAt}}
Finished at: {{.State.FinishedAt}}' \
  "$AGENT_NAME"
