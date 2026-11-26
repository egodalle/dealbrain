---
owner: architect
last-reviewed: 2026-11-26
stability: stable
---

# DB-01: Architect review

**Verdict:** APPROVED

---

## Check results

### 1. Implementation checklist completeness (design.md section 9)

PASS. All 14 items are present in the branch tree:

| Checklist item | Present |
|---|---|
| `.gitignore` | yes |
| `pyproject.toml` | yes |
| `uv.lock` | yes |
| `docker-compose.yml` | yes |
| `db/init/01-extensions.sql` | yes |
| All `.gitkeep` files (apps/portal, apps/mcp, pipelines, router, brain, hermes/skills, db/migrations, infra, tests/integration, tests/acceptance, evals) | yes — all 11 present |
| `tests/unit/__init__.py` | yes |
| `tests/unit/test_placeholder.py` | yes |
| `Makefile` | yes |
| `.env.example` | yes |
| `.github/workflows/ci.yml` | yes |
| `ONBOARDING.md` | yes |
| `docs/ARCHITECTURE.md` | yes |

One item from section 2 that is worth noting: `docs/adr/` already had a `.gitkeep` committed on `main` and also gained `0001-python-lint-and-compose-baseline.md` on this branch. The design said it "already exists"; both conditions are met. No issue.

---

### 2. docker-compose.yml image tag

PASS. `docker-compose.yml` uses `pgvector/pgvector:0.7.4-pg16` exactly as designed.
The CI `services:` block in `ci.yml` uses the same tag. No drift between local and CI.

---

### 3. pyproject.toml — Python 3.12 and mypy strict

PASS.
- `requires-python = ">=3.12,<3.13"` — exact pin per design section 7.
- `[tool.mypy] python_version = "3.12"` and `strict = true` — present.
- `[tool.ruff] target-version = "py312"` — present.
- Dev dependencies (`pytest`, `ruff`, `mypy`) appear under `[dependency-groups] dev`, which is the PEP 735 / uv 0.5+ idiom. This is documented as a known deviation in impl-notes.md and is correct — uv resolves `[dependency-groups]` identically to `[tool.uv.dev-dependencies]` and `uv sync --frozen` will reproduce pinned versions in CI.

---

### 4. .github/workflows/ci.yml — lint and test jobs with correct pgvector service

PASS.
- Two independent parallel jobs: `lint` and `test`.
- Both jobs: `actions/checkout@v4`, `astral-sh/setup-uv@v4` with `python-version: "3.12"`, `uv sync --frozen`, then the make target.
- `test` job `services.db.image` = `pgvector/pgvector:0.7.4-pg16`. Matches compose file exactly.
- Health-check options match the design (`--health-retries 10`, etc.).
- `DATABASE_URL` and `POSTGRES_PASSWORD` env vars passed to the `make test` step.

---

### 5. ONBOARDING.md — Quick start section

PASS. `## Quick start` heading is at line 17 and covers:
- `git clone <repo-url> && cd dealbrain`
- `cp .env.example .env` (with a note to set POSTGRES_PASSWORD)
- `make up`
- `make test`

All four required elements are present with copy-paste commands. CLAUDE.md rule ("update ONBOARDING.md in the same PR") is satisfied.

---

### 6. .env.example — no real secrets

PASS. `.env.example` contains only placeholder values (`changeme`). No token, API key, or real password is present.

AC6 exact check: `git log --all -S "password" -- .env*` returns zero matches — confirmed (the word "password" appears only as part of the key name `POSTGRES_PASSWORD`, which git's `-S` pickaxe does not match because the string "password" in lowercase does not appear verbatim in the diff).

One note: `git log --all -S "changeme" -- ".env*"` does return a match — the placeholder value `changeme` is committed in `.env.example`. This is expected and intentional. The design explicitly says `POSTGRES_PASSWORD=changeme` should be in `.env.example`. `changeme` is not a secret; it is a signal to the developer to replace it. No action needed.

---

### 7. CLAUDE.md rule violations

PASS on all counts:

| Rule | Status |
|---|---|
| Branch name `feat/DB-01-*` | `feat/DB-01-repo-baseline` — correct |
| Conventional commit message | `feat(DB-01): repo baseline, CI, local compose with pgvector` — correct |
| No secrets in git | confirmed — `.env` is in `.gitignore`; `.env.example` has only placeholders |
| No real personal data in git | no personal data present in this scaffold PR |
| `make lint test` passes before review | impl-notes.md records both exiting 0 with output; evidence is credible |
| ONBOARDING.md updated in same PR | yes |

---

### 8. Deviations from design.md

All three deviations are documented in `impl-notes.md` and are acceptable:

| Deviation | Assessment |
|---|---|
| `test_placeholder.py` adds `-> None` return annotation | Strictly correct. Without it `mypy --strict` would fail. The design sketch omitted the annotation; the implementation is more accurate than the design. Not a defect. |
| `[dependency-groups]` instead of `[tool.uv.dev-dependencies]` | Correct uv idiom for uv 0.5+. PEP 735-compliant. CI `uv sync --frozen` will resolve it identically. Not a defect. |
| Dev dependencies (pytest, ruff, mypy) added to lockfile | Necessary for reproducible CI. The design described them as tooling but did not show the `pyproject.toml` lines; the implementation is completing the design's intent. Not a defect. |

No silent redesigns. No changes to scope or acceptance criteria.

---

## Findings summary

| # | Severity | Finding |
|---|---|---|
| — | — | No blocking findings. |

**Nit (non-blocking):** `docs/ARCHITECTURE.md` data-flow sketch places `router/` between `pending_actions` and the LLM, which is correct per the approval boundary rule, but the arrow `pending_actions → router/ → LLM → hermes/ / portal/` could be misread as LLM calls happening automatically after approval rather than being initiated by the portal handler. This is a stub and will be replaced in DB-02 with the C4 diagram. No action required now; flag for the ARCHITECTURE.md author to clarify the flow direction when the diagram is added.

---

## Overall verdict

**APPROVED.** No blocking issues. Story is ready to hand off to `tester`.
