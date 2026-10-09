# Runbooks

This directory contains execution runbooks for bounded autonomous engineering work.

## Convention

Use one directory per workstream, then one ordered directory per substantial stage:

```text
runbooks/
  <workstream>/
    README.md
    01-<stage>/
      README.md
    02-<stage>/
      README.md
    03-<stage>/
      README.md
```

Rules:

- A runbook is an execution contract, not a general architecture document.
- Each stage should state starting evidence, objective, role assignment, constraints,
  acceptance criteria, tests/live verification, and exit conditions.
- Later runbooks may rely on earlier recorded evidence, but must identify the exact
  checkpoint they start from.
- Do not rewrite completed stage runbooks into current-state documentation. Current
  implementation truth belongs in `docs/` and `note/`.
- If a stage produces a durable specification or architecture decision, synchronize the
  relevant authority document separately.
- One workstream may end with "no production change required" when evidence does not
  justify implementation.

## Migration policy

Existing runbooks outside this directory do not need to move during an active work item.

Move them later in a dedicated documentation-only change after:

1. active branches depending on the old path are finished or updated;
2. all references in `AGENTS.md`, Codex prompts, and docs are known;
3. the move does not get mixed with production implementation.

This avoids noisy rename diffs and broken instructions during an in-progress investigation.

## Active workstreams

- [Piccoma free-only Site Adapter](piccoma-free/README.md) — five-role autonomous
  discovery/capture/direct-batch/E2E implementation contract (planned).
