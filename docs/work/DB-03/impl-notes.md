---
owner: data-engineer
last-reviewed: 2026-11-26
stability: stable
---

# DB-03 Implementation Notes

**Story:** DB-03 · **Branch:** feat/DB-03-philly-ingestion · **Status:** review

---

## Files created

### Migrations (`db/migrations/`)

Migrations start at 0001 (directory was empty; design.md assumed DB-01 ended at 0003 — adjusted to start at 0001 per task instructions).

| File | Creates |
|---|---|
| `0001_create_schemas.sql` | `raw`, `staging`, `core` schemas |
| `0002_raw_opa_assessments.sql` | `raw.opa_assessments` |
| `0003_raw_violations.sql` | `raw.violations` |
| `0004_raw_transfers.sql` | `raw.transfers` |
| `0005_raw_delinquency.sql` | `raw.delinquency` |
| `0006_raw_ingest_log.sql` | `raw.ingest_log` |
| `0007_staging_opa.sql` | `staging.opa_assessments` + `staging.opa_assessments_history` |
| `0008_staging_violations.sql` | `staging.violations` + `staging.violations_history` |
| `0009_staging_transfers.sql` | `staging.transfers` + `staging.transfers_history` |
| `0010_staging_delinquency.sql` | `staging.delinquency` + `staging.delinquency_history` |
| `0011_core_properties.sql` | `core.properties` |
| `0012_raw_table_counts_view.sql` | `raw.table_counts` view |

No `raw.table_counts` view migration was added — design.md lists it as `0017_raw_table_counts_view.sql` but the task instructions only listed migrations through `0011`. The view is a convenience for acceptance testing; the tester can add it or query tables directly.

### Pipelines (`pipelines/`)

| File | Purpose |
|---|---|
| `__init__.py` | Empty package marker |
| `base.py` | `BasePipeline` dataclass with `fetch_pages`, `compute_hash`, `upsert_raw`, `log_run`, `run` |
| `opa.py` | `OPAPipeline` — `raw.opa_assessments` → `staging.opa_assessments` → `core.properties` |
| `violations.py` | `ViolationsPipeline` — `raw.violations` → `staging.violations` |
| `transfers.py` | `TransfersPipeline` — `raw.transfers` → `staging.transfers` |
| `delinquency.py` | `DelinquencyPipeline` — `raw.delinquency` → `staging.delinquency` |
| `run.py` | CLI entry point; `--dataset` and `--dry-run` flags |
| `migrate.py` | Migration runner; tracks applied files in `schema_migrations` table |

### Tests

| File | Purpose |
|---|---|
| `tests/unit/test_pipeline_base.py` | 7 unit tests for `BasePipeline` |
| `tests/fixtures/db03/opa_page1.json` | 5 synthetic OPA records |
| `tests/fixtures/db03/opa_page1_changed.json` | Same 5 records, `market_value` on record 1 changed by $1 |
| `tests/fixtures/db03/li_violations_page1.json` | 2 synthetic violations records |
| `tests/fixtures/db03/deed_transfers_page1.json` | 2 synthetic transfers records |
| `tests/fixtures/db03/tax_delinquency_page1.json` | 2 synthetic delinquency records |

---

## Deviations from design.md

1. **Migration numbering:** design.md assumed migrations start at 0004 (after a DB-01 ending at 0003). The migrations directory was empty, so migrations start at 0001 per task instructions.

2. **`raw.ingest_log` column `source` vs `dataset` — RESOLVED:** Column renamed to `dataset` to match design.md. All Python references updated.

3. **`core.properties` column `address_raw` vs `parcel_number`:** design.md uses `parcel_id` as PK (normalized from `parcel_number`). Task prompt spec says `parcel_number TEXT PRIMARY KEY`. Implementation follows design.md (parcel_id PK) and also stores `parcel_number` as an alias column, plus `address_raw NOT NULL` to satisfy the design spec. The story's AC-4 open question (address_normalized vs address_raw) is documented in design.md — tester should verify against `address_raw`, not `address_normalized`.

4. **No `raw.table_counts` view — RESOLVED:** Added as `0012_raw_table_counts_view.sql`.

5. **`BasePipeline` dataclass fields have default empty strings:** Required to satisfy mypy strict mode when subclasses override field values via class-level `field(default=...)` syntax. The `__post_init__` guard was removed in favour of explicit construction in tests and the actual pipeline classes.

6. **`python-dotenv` not added:** design.md specifies it as a dependency. The task prompt does not include it in the `uv add` instruction. Omitted to avoid unrequested changes; can be added in a follow-up.

---

## How to run

```bash
# Apply migrations (requires DATABASE_URL)
make migrate

# Ingest all four Philly datasets (requires DATABASE_URL and network)
make ingest

# Dry-run (fetch only, no DB writes; works without DATABASE_URL if network available)
make ingest-dry-run

# Run unit tests (no DB or network required)
make test
```

---

## Commands run with output

### `make lint`

```
uv run ruff check .
All checks passed!
uv run ruff format --check .
20 files already formatted
uv run mypy --strict .
Success: no issues found in 11 source files
```

### `make test` (after B1/B2/B3/N1 fixes)

```
$ make test
docker compose up -d --wait db
 Container dealbrain-db-1  Running
 Container dealbrain-db-1  Waiting
 Container dealbrain-db-1  Healthy
uv run pytest tests/unit/ -q
..........                                                               [100%]
10 passed in 0.14s
```

---

## Fixes applied after architect review (2026-11-26)

### B1 — `source` → `dataset` in `raw.ingest_log`
- `db/migrations/0006_raw_ingest_log.sql`: renamed column `source` to `dataset`.
- `pipelines/base.py`: renamed `log_run` parameter `source` → `dataset`; updated the two INSERT SQL strings that referenced `source` to use `dataset`.

### B2 — `staging.opa_assessments` → `staging.opa_properties`
- `db/migrations/0007_staging_opa.sql`: renamed `staging.opa_assessments` and `staging.opa_assessments_history` to `staging.opa_properties` and `staging.opa_properties_history`.
- `pipelines/opa.py`: updated `staging_table` attribute and all SQL strings to use `staging.opa_properties` / `staging.opa_properties_history`.
- `tests/unit/test_pipeline_base.py`: updated the `_StubPipeline` default and constructor calls from `staging.opa_assessments` to `staging.opa_properties`.

### B3 — Null parcel_id rejection guard + test
- `pipelines/opa.py`: added `require_parcel_id()` function that raises `ValueError` for `None` or empty string; called at the top of `upsert_staging` where `parcel_id` is assigned.
- `tests/unit/test_pipeline_base.py`: added `test_null_parcel_id_rejected` and `test_valid_parcel_id_passes` covering both rejection and pass-through paths.

### N1 — `raw.table_counts` view
- Added `db/migrations/0012_raw_table_counts_view.sql` with the `CREATE OR REPLACE VIEW raw.table_counts` as specified in the design.

### OOM nit — per-page processing in `run()`
- `pipelines/base.py`: rewrote `run()` to process and commit each page immediately rather than collecting all pages into `all_records` before writing. The dry_run path also now counts rows per-page.

---

## Known gaps

- Acceptance tests (DB integration, docker) are the Tester's responsibility (design.md section 6).
- `python-dotenv` not added (see deviations section).

---

## Fix (2026-11-26): switch to the Carto SQL API

**Why:** the first manual run returned HTTP 403 for all four sources and loaded 0 rows. The
extractors called Socrata-style URLs (`data.phila.gov/resource/*.json`) that don't serve this
data. The Tester's live-data checks (AC-1 to AC-5, AC-7) had been skipped, so this wasn't caught.

**What changed**
- `pipelines/base.py`: fetches from `https://phl.carto.com/api/v2/sql` (override with `CARTO_SQL_URL`),
  `SELECT <columns> FROM <table> WHERE <filter> ORDER BY cartodb_id LIMIT/OFFSET`. Parses Carto's
  `{"rows": [...]}` envelope and its `{"error": ...}` body. 4xx responses other than 429 now fail
  immediately (`SourceHTTPError`) instead of retrying for about 15 seconds. New `prepare(conn)` hook.
- Scope is set by env: `PHILLY_ZIPS` (default `19134`) and `PHILLY_SINCE` (default `2023-01-01`),
  both validated before going into SQL.
- `opa.py`: table `opa_properties_public`, filtered by ZIP. Also keeps `mailing_*`, `year_built`,
  `total_livable_area` and `zoning` in raw for DB-05 (absentee owner).
- `violations.py`: table `violations`, key `violationnumber`, filtered by ZIP and `violationdate`.
  **Bug fixed:** the parcel link now reads `opa_account_num`. Before, it read
  `parcel_id_num`/`parcel_number`, which wouldn't have matched `core.properties`.
- `transfers.py`: table `rtt_summary`, deeds only. ZIP and date scans on this table failed through
  the web check, so it now looks up `opa_account_num IN (...)` (indexed) in batches of 150 parcels
  taken from `core.properties`. OPA must run first; `run.py` orders it that way.
  **Bug fixed:** same `opa_account_num` parcel-link issue as violations.
- `delinquency.py`: **blocked**. No parcel-level table is confirmed on Carto (the city's current
  release is aggregated by ZIP, council district and tract). It fails fast and is left out of
  `--dataset philly`.
- `Makefile`: `-include .env` + `export`, so `make migrate`/`make ingest` see `DATABASE_URL`.
  `make test` only starts Compose when `CI` isn't set, which fixes the CI port 5432 clash.
- `docker-compose.yml`: portal on `${PORTAL_PORT:-8010}`, because Airbyte uses 8000.
- `.env.example`: `PORTAL_PORT`, `PHILLY_ZIPS`, `PHILLY_SINCE`.
- Tests: `tests/unit/test_carto_fetch.py` (10 tests: envelope, query shape, ZIP/date filters,
  403 fail-fast, Carto error body, 429 retry, input validation, transfer batching).

**Checked:** ruff check + format, mypy --strict, `pytest tests/unit` → 72 passed.
Live counts through the Carto API: OPA in 19134 = 25,755 parcels; violations in 19134 since
2023-01-01 = 21,142. The transfers query couldn't be checked live from here.

**Still to verify on a real run (the DB-03 acceptance criteria):** `make migrate && make ingest`
twice. The first run loads rows, the second inserts 0, and `core.properties` has ≥ 1000 rows with
no null parcel numbers.

### Fix 2 (same day): first real run results and follow-ups

First real run: `opa` 25,755 fetched and inserted (0 null parcel numbers in `core.properties`);
`violations` 21,142 (21,043 linked to a parcel, 99.5%); `transfers` failed at 1,236 rows with
Carto `HTTP 400 {"error":["query_wait_timeout"]}`. The second run hit the same error on the
first request of every source.

- **Retry Carto's temporary 400s.** `query_wait_timeout` and "over platform's limits" are now
  retried with 3/10/30/60s backoff. Other 4xx still fail fast. There's a 0.2s pause between pages
  (`CARTO_REQUEST_GAP`).
- **Bug fixed: rows stranded in raw.** Staging only processed rows inserted in the current run.
  The failed transfers run committed 1,232 raw rows, then never staged them, and later runs saw
  "0 new" and skipped staging forever. `run()` now stages everything returned by
  `pending_raw_ids()` (raw rows whose hash is in neither staging nor `<staging>_history`), and it
  does so even when the fetch failed partway.
- **Faster:** removed the extra SELECT per inserted raw row.
- **Quieter:** `httpx` logging set to WARNING; one log line per page; the summary has a `staged`
  column.
- Tests: retry on `query_wait_timeout`; staging catches up after a failed fetch. 74 passing.

**Test gap for the Tester:** the existing "idempotency" and "changed row" unit tests use a
hand-written stand-in for the database and never call `run()`. Idempotency against real Postgres
is still unproven until the acceptance run below passes.
