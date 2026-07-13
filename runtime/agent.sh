#!/usr/bin/env bash

set -euo pipefail

echo "=== Agent Runtime Started ==="
echo "Agent name: ${AGENT_NAME:-unknown}"
echo "Task: ${AGENT_TASK:-No task provided}"
echo "Workspace: /workspace"
echo "Started at: $(date)"

echo
echo "Workspace contents before execution:"
ls -la /workspace

echo
echo "Simulating agent work..."
sleep 5

cat > /workspace/agent-output.txt <<EOF
Agent: ${AGENT_NAME:-unknown}
Task: ${AGENT_TASK:-No task provided}
Completed at: $(date)
Result: Simulated task completed successfully.
EOF

echo
echo "Workspace contents after execution:"
ls -la /workspace

echo
echo "=== Agent Runtime Completed ==="
