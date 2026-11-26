---
owner: architect
last-reviewed: 2026-11-26
stability: stable
---

# ADR-0001: Python version, lint strategy, and Compose file layout for the baseline stack

## Context

DB-01 establishes the toolchain every subsequent story inherits. Three decisions are
effectively irreversible at day 1 because changing them later forces all contributors
to re-pull images, re-pin dependencies, or rewrite CI:

1. **Python version** — determines CPython internals available to pyproject.toml and
   the Docker layer cache key.
2. **Lint surface** — adding mypy --strict after dozens of modules exist is painful;
   removing it is easy. The question is which direction carries lower cost.
3. **Compose file topology** — a split-file approach (root + CI override) adds
   cognitive overhead for a solo/small team and is only necessary when CI needs to
   diverge from local in a material way (e.g., different volumes, external secrets
   managers). Our CI divergence is exactly one fact: "no host-mounted volume needed";
   that does not justify a second file.

## Decision

**Python 3.12.** The frozen stack spec says Python 3.12 + uv. No ambiguity.

**ruff + mypy --strict from day 1.** CLAUDE.md says "CI runs lint, mypy, tests".
Mypy strict from the start keeps the type surface honest on new modules and costs
nothing on a green-field repo. The alternative—ruff only now, add mypy later—
creates a window where untyped code accumulates and the strict flag becomes a
multi-day remediation project.

**Single docker-compose.yml at repo root.** CI and local share the same file. The
only CI-specific adjustment (no named volume mount for source code) is handled by
the fact that the CI runner checks out the repo itself and the compose file never
bind-mounts the project root—it only mounts `db-data`. No override file is needed.

**postgres:16-alpine with pgvector 0.7.x.** `pgvector/pgvector:pg16` publishes a
convenience image that installs the extension at a pinned digest. We pin the image
tag to `pgvector/pgvector:0.7.4-pg16` (the latest stable release as of 2026-11-26)
rather than `:pg16` (a floating tag) to prevent silent upstream breakage.

## Consequences

- All Python files must be typed well enough to satisfy mypy --strict from commit 1.
  Placeholder modules use `pass` or raise `NotImplementedError`; stub type: ignore
  comments are forbidden except where a third-party library ships no stubs.
- The single compose file is the source of truth for both local and CI. If a future
  story genuinely needs a different topology in CI (e.g., a secrets manager), that
  story should write `docs/adr/NNNN-compose-override.md` before introducing the
  override file.
- Pinning `pgvector/pgvector:0.7.4-pg16` means the team must intentionally bump
  the tag when upgrading; this is the desired behavior.

## Alternatives rejected

- **Python 3.11**: Not what the frozen stack says. Rejected.
- **ruff only**: Saves ~10 minutes on day 1, costs days on a future story. Rejected.
- **Compose root + CI override**: The only divergence between local and CI is
  immaterial to correctness. The extra file adds cognitive load with no benefit.
  Rejected.
- **pgvector/pgvector:pg16 (floating tag)**: Upstream has broken builds before by
  publishing incompatible pgvector minor versions. Pin to digest or exact tag.
  Rejected in favor of exact tag.
