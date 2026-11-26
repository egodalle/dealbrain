---
owner: data-engineer
last-reviewed: 2026-11-26
stability: stable
---

# DealBrain Onboarding

This guide gets a new contributor to a running local stack in under five minutes.

## Prerequisites

- Docker Desktop (or Docker Engine + Compose v2.1+)
- [uv](https://docs.astral.sh/uv/) — Python package manager (`brew install uv` or `pip install uv`)
- Git

## Quick start

```bash
# 1. Clone the repo
git clone <repo-url>
cd dealbrain

# 2. Set up environment variables
cp .env.example .env
# Edit .env and set a real POSTGRES_PASSWORD (any value works locally)

# 3. Start the local stack (Postgres with pgvector)
make up
# Waits until all containers are healthy, then prints "Stack is healthy."

# 4. Run the test suite
make test
# Runs unit tests via pytest; must exit 0 with at least 1 test passing
```

## Lint

```bash
make lint
# Runs ruff check, ruff format --check, and mypy --strict
```

## Tear down

```bash
make down
# Stops containers and removes volumes for a clean-slate reset
```

## Directory layout

```
apps/portal       Portal UI (future)
apps/mcp          MCP server (future)
pipelines/        Ingestion and ETL pipelines
router/           LLM router (all LLM calls go through here)
brain/            Scoring and dedupe logic
hermes/skills/    Hermes assistant skills
db/migrations/    Numbered SQL migration files
db/init/          Init SQL run at first container start
infra/            Infrastructure definitions
tests/unit/       Unit tests (run without Docker services)
tests/integration/  Integration tests
tests/acceptance/ Acceptance tests
evals/            LLM eval suite
docs/             Architecture docs, ADRs, story work
```

## CI

GitHub Actions runs `make lint` and `make test` on every push and pull request.
Both jobs must be green before merging to `main`.

## Notes

- Never commit `.env` — it is in `.gitignore`. Commit `.env.example` only.
- LLM calls go only through `router/`. Nothing sends outbound messages without
  a human approving the action in the portal.
- See `docs/ARCHITECTURE.md` for a system overview and `docs/adr/` for decisions.
