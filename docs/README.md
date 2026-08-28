# docs/

A collection point for reference material — not a second source of
truth. Points to where things live rather than duplicating them,
except where the original had nowhere else to go.

- **Project overview, architecture, setup, known limitations** — see
  the root [`README.md`](../README.md). Not duplicated here; it's
  actively maintained at the repo root and a copy would just go
  stale.
- **[`history_compression.md`](history_compression.md)** — design doc
  for Short-term History Compression (5D-6B-4): pipeline, components,
  invariants, benchmark results, known limitations. Moved here from a
  loose `ShortTermHistoryCompression.txt` at the repo root. The
  condensed version of the same material also lives in the root
  README's "History Compression" section.
- **[`memory/`](memory/)** — a point-in-time export of Claude's
  auto-memory for this project (normally stored outside the repo, at
  `~/.claude/projects/-Users-hukaikun-claude-agent-platform/memory/`,
  and not visible from inside the IDE). `memory/MEMORY.md` is the
  index; each linked file covers one topic (a completed stage, an
  open bug, a design decision). This is a **snapshot, not a live
  sync** — re-copy from the source directory when you want it
  current.
