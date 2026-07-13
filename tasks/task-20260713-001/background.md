# Task Background

## Task

Build the Agent, Task, and Run data model for the private Claude Agent platform.

## Objective

Restructure the platform so that Agents and Tasks are independent entities.

A Task must be able to contain multiple Runs, and each Run may be executed by a different Agent. This structure should support future collaboration among multiple Claude Agents.

## System Context

The current prototype already supports:

- Ubuntu 24.04 ARM64
- Docker and Docker Compose
- A mock Agent Runtime
- Independent Docker containers
- Persistent mounted workspaces
- Basic command-line scripts for running and inspecting containers

The previous prototype used the same identifier for:

- Agent
- Docker container
- Workspace
- Task

This design is being replaced because it does not support long-term task history or multi-Agent collaboration.

## Requirements

1. Agents must be stored independently under `agents/`.
2. Tasks must be stored independently under `tasks/`.
3. Each Task must have:
   - Structured metadata
   - A background file
   - A Task status
   - A collection of Runs
4. Each Run must identify which Agent executed it.
5. Different Runs in the same Task may use different Agents.
6. Run outputs must not overwrite previous Run outputs.
7. After a Run finishes, a placeholder update must be appended to this background file.
8. A future summary Agent may replace the placeholder with a structured summary.

## Task Status

Current status: **in_progress**

Allowed Task statuses:

- `not_started`
- `in_progress`
- `completed`
- `abandoned`

## Current Progress

- Legacy Agent workspaces have been archived.
- A shared Workspace has been created.
- The first formal Agent configuration has been created.
- The Task and Run directory model is now being implemented.

## Constraints

- Do not store Claude API keys in Task files.
- Do not overwrite previous Run records.
- Preserve historical logs and outputs.
- Keep Agent identity separate from container identity.
- Keep Task status separate from Run status.
- The system is private and currently intended for two trusted users.

## Run Updates

<!-- RUN_UPDATES_START -->

No Runs have been created yet.

<!-- RUN_UPDATES_END -->
