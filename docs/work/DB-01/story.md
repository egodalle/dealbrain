# DB-01: Repo layout, standards, CI, local Compose with pgvector

**Status:** ready · **Plan day:** 1 · **Posting lines covered:** GitHub, standards, CI, releases, docs

## Story

As a **RE RESET engineer onboarding a new DealBrain instance**, I want a single `git clone` followed by `make up` to give me a running local stack with pgvector, and I want the first PR to pass CI automatically, so that every contributor starts from a known-good baseline with no manual environment setup.

## Acceptance criteria

1. `git clone <repo> && cd dealbrain && make up` completes without error and prints a line confirming all services are healthy. Running `docker compose ps` shows every service in state `running` (not `exited` or `restarting`).

2. `docker compose exec db psql -U dealbrain -c "SELECT extname FROM pg_extension WHERE extname = 'vector';"` returns exactly one row: `vector`.

3. `make lint` exits 0. The CI workflow file (`.github/workflows/ci.yml`) runs the same `make lint` step, and the first PR on a branch with no lint errors shows a green check on GitHub Actions.

4. `make test` exits 0 and runs at least one placeholder test. CI runs `make test` against the pgvector container and the job is green.

5. The repo contains the directories `apps/portal`, `apps/mcp`, `pipelines/`, `router/`, `brain/`, `hermes/skills/`, `db/migrations/`, `infra/`, `tests/unit/`, `tests/integration/`, `tests/acceptance/`, `evals/`, and `docs/adr/`. Running `ls` on each path returns a directory (empty is acceptable at this stage).

6. A `.env.example` file exists at the repo root listing every environment variable the stack requires. No secret values are present in `.env.example` or committed to git. Running `git log --all -S "password" -- .env*` returns zero matches.

7. `ONBOARDING.md` exists at the repo root and contains a section headed `## Quick start` that covers clone, `.env` setup, `make up`, and `make test` with copy-paste commands.

## Demo line

Run `git clone && make up` live from a clean directory; the terminal shows all containers healthy and `make test` green in under two minutes.

## Out of scope

- Any application feature code (portal UI, pipeline logic, MCP tools).
- Production VPS provisioning (covered by DB-02).
- Tailscale networking setup (covered by DB-02).
- Database schema migrations beyond enabling the pgvector extension.
- CI deployment jobs; this story covers lint and test gates only.

## Open questions for Architect

- Which Python version should be pinned in the Dockerfile and `pyproject.toml`? (3.11 or 3.12?)
- Should `make lint` run `ruff` only, or also `mypy --strict` from day one?
- Is a single `docker-compose.yml` at the root sufficient, or do we want an override file for CI?
- What Postgres image tag and pgvector version should be pinned to avoid upstream surprises?
