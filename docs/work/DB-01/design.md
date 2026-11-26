---
owner: architect
last-reviewed: 2026-11-26
stability: stable
---

# DB-01 Design: Repo layout, standards, CI, local Compose with pgvector

ADR: [docs/adr/0001-python-lint-and-compose-baseline.md](../../adr/0001-python-lint-and-compose-baseline.md)

---

## 1. Answers to the open questions

### Python version
**Python 3.12.** Matches the frozen stack spec in CLAUDE.md verbatim. Pin in
`pyproject.toml` (`requires-python = ">=3.12,<3.13"`) and in the Dockerfile
(`FROM python:3.12-slim`).

### Lint scope
**ruff + mypy --strict from day 1.** CLAUDE.md already says CI runs mypy.
Starting strict on a green-field repo costs nothing; retrofitting strict on a
mature codebase costs days. See ADR-0001.

### docker-compose.yml structure
**Single file at the repo root.** CI and local run the same file. No override.
See ADR-0001.

### Postgres image and pgvector version
**`pgvector/pgvector:0.7.4-pg16`** — exact image tag, not a floating alias.
This image ships Postgres 16 with the pgvector 0.7.4 extension already compiled
and installed. No `CREATE EXTENSION` in an init script is needed beyond the
one-line SQL that the compose `POSTGRES_INITDB_ARGS` or an init file will run.
See ADR-0001.

---

## 2. Directory scaffold (AC5)

Every path below must exist. Empty directories use a `.gitkeep` file so git
tracks them.

```
apps/
  portal/
    .gitkeep
  mcp/
    .gitkeep
pipelines/
  .gitkeep
router/
  .gitkeep
brain/
  .gitkeep
hermes/
  skills/
    .gitkeep
db/
  migrations/
    .gitkeep
  init/
    01-extensions.sql        # CREATE EXTENSION IF NOT EXISTS vector;
infra/
  .gitkeep
tests/
  unit/
    __init__.py
    test_placeholder.py      # one passing test, satisfies AC4
  integration/
    .gitkeep
  acceptance/
    .gitkeep
evals/
  .gitkeep
docs/
  adr/                       # already exists
  work/
    DB-01/                   # already exists
  backlog.md                 # already exists
  ARCHITECTURE.md            # stub, required by CLAUDE.md layout
```

The `tests/unit/` directory gets `__init__.py` and a real (if trivial) test
so `make test` has something to run from day 1.

---

## 3. docker-compose.yml structure

```yaml
services:
  db:
    image: pgvector/pgvector:0.7.4-pg16
    environment:
      POSTGRES_DB: dealbrain
      POSTGRES_USER: dealbrain
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - db-data:/var/lib/postgresql/data
      - ./db/init:/docker-entrypoint-initdb.d:ro
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U dealbrain"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  db-data:
```

The `./db/init/01-extensions.sql` file runs at first container start:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

Both extensions are in scope per the frozen stack. Installing them together
here avoids a separate migration step in DB-03.

The healthcheck drives the `make up` readiness check: the Makefile waits
for `db` to be healthy before printing the success message.

---

## 4. Makefile targets

```makefile
.PHONY: up down lint test

up:
	docker compose up -d --wait
	@docker compose ps
	@echo "Stack is healthy."

down:
	docker compose down -v

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy --strict .

test:
	docker compose up -d --wait db
	uv run pytest tests/unit/ -q
```

Notes:
- `--wait` (Compose v2.1+) blocks until all healthchecks pass, satisfying AC1.
- `make lint` runs ruff check, ruff format check, then mypy strict — in that
  order so format errors surface first.
- `make test` starts only the db service (not the full stack) so the placeholder
  test can grow into a real integration test without changing the target. It
  uses `uv run` so the developer never needs to activate a venv manually.
- `make down` removes volumes, giving a clean-slate reset.

---

## 5. CI workflow (.github/workflows/ci.yml)

Single file, two jobs: `lint` and `test`. They are independent and run in
parallel to keep total wall time low.

```
name: CI

on:
  push:
    branches: ["**"]
  pull_request:

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          python-version: "3.12"
      - run: uv sync --frozen
      - run: make lint

  test:
    runs-on: ubuntu-latest
    services:
      db:
        image: pgvector/pgvector:0.7.4-pg16
        env:
          POSTGRES_DB: dealbrain
          POSTGRES_USER: dealbrain
          POSTGRES_PASSWORD: test
        options: >-
          --health-cmd "pg_isready -U dealbrain"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
        ports:
          - 5432:5432
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          python-version: "3.12"
      - run: uv sync --frozen
      - run: make test
        env:
          DATABASE_URL: postgresql://dealbrain:test@localhost:5432/dealbrain
          POSTGRES_PASSWORD: test
```

The `test` job spins up the same image the compose file uses so there is
no version drift between local and CI.

---

## 6. .env.example

```dotenv
# Postgres
POSTGRES_PASSWORD=changeme

# App database URL (constructed from the above)
DATABASE_URL=postgresql://dealbrain:changeme@localhost:5432/dealbrain

# Log level
LOG_LEVEL=INFO
```

Rules:
- No actual password, token, or key may appear here.
- `.env` is in `.gitignore`. `.env.example` is committed.
- `git log --all -S "password" -- .env*` must return zero matches because
  the word "password" appears only as a key name, not as a value with a real
  credential.

---

## 7. pyproject.toml structure

```toml
[project]
name = "dealbrain"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = []

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]

[tool.mypy]
python_version = "3.12"
strict = true

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Dependencies are empty at this stage. Each subsequent story adds its own
deps via `uv add`.

---

## 8. Failure modes

| Failure | Cause | Recovery |
|---|---|---|
| `make up` hangs | db healthcheck never passes | `docker compose logs db`; most likely POSTGRES_PASSWORD not set in .env |
| pgvector extension missing | wrong image tag or init script not mounted | verify image tag; check `./db/init/` is mounted `:ro` |
| mypy fails on placeholder files | missing `py.typed` or wrong stub | add `# type: ignore` only on third-party call sites with no stubs |
| CI test job can't connect to db | service not healthy before pytest starts | the `--health-retries 10` option handles this; if it fails, the GH Actions service startup log will show the error |

---

## 9. Tests that prove the story

| AC | Test / command |
|---|---|
| AC1 | `make up` exits 0; `docker compose ps` output has no `exited` or `restarting` |
| AC2 | `docker compose exec db psql -U dealbrain -c "SELECT extname FROM pg_extension WHERE extname = 'vector';"` returns 1 row |
| AC3 | `make lint` exits 0 locally and in CI |
| AC4 | `make test` exits 0; pytest output shows at least 1 passed |
| AC5 | `ls apps/portal apps/mcp pipelines/ router/ brain/ hermes/skills/ db/migrations/ infra/ tests/unit tests/integration tests/acceptance evals/ docs/adr/` all resolve |
| AC6 | `.env.example` committed; `git log --all -S "password" -- .env*` returns zero matches |
| AC7 | `ONBOARDING.md` exists; `grep -n "## Quick start" ONBOARDING.md` returns a line |

---

## Implementation checklist

Create these files and directories in this order. Each item is unblocked by
the items above it.

1. `.gitignore` — include `.env`, `__pycache__/`, `.mypy_cache/`, `.ruff_cache/`, `*.egg-info/`, `dist/`
2. `pyproject.toml` — project metadata, ruff, mypy, pytest config (section 7 above)
3. `uv.lock` — generated by `uv sync` after pyproject.toml exists
4. `docker-compose.yml` — section 3 above
5. `db/init/01-extensions.sql` — `CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;`
6. All `.gitkeep` files — one per empty directory listed in section 2
7. `tests/unit/__init__.py` — empty file
8. `tests/unit/test_placeholder.py` — single `def test_ok(): assert True`
9. `Makefile` — targets from section 4
10. `.env.example` — variables from section 6
11. `.github/workflows/ci.yml` — workflow from section 5
12. `ONBOARDING.md` — must include `## Quick start` covering clone, .env setup, `make up`, `make test`
13. `docs/ARCHITECTURE.md` — stub with one-paragraph description of the system and a placeholder diagram note; link ADR-0001
14. Verify: `make up` → `make lint` → `make test` → all three exit 0
