---
owner: architect
last-reviewed: 2026-11-26
stability: stable
---

# DB-03 Design: Philly open-data ingestion (OPA, violations, transfers, delinquency)

**Story:** DB-03 · **ADR:** docs/adr/0003-raw-layer-append-only-and-staging-audit-pattern.md

---

## 1. Layer design

Three Postgres schemas. No connector writes directly to `core`. Every `core` row traces
back to a `raw` row via `raw_id`.

```
raw.*          append-only snapshots, never updated
staging.*      deduplicated, typed, SCD-2 current + history
core.*         clean, queryable, stable FKs
```

### 1.1 raw schema

One table per source. All share the same envelope columns; `payload` holds the
upstream JSON exactly as received.

**raw.opa_assessments**

| Column | Type | Notes |
|---|---|---|
| id | BIGSERIAL PK | |
| source_id | TEXT NOT NULL | `parcel_number` from upstream |
| row_hash | TEXT NOT NULL | SHA-256 of `payload::text` |
| payload | JSONB NOT NULL | raw upstream record |
| ingested_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |
| run_id | UUID NOT NULL | FK → raw.ingest_log.run_id |

Unique constraint: `(source_id, row_hash)`. The ingest uses `INSERT ... ON CONFLICT (source_id, row_hash) DO NOTHING`. A second identical run inserts zero rows.

**raw.li_violations**, **raw.deed_transfers**, **raw.tax_delinquency** — identical
envelope; `source_id` is `violation_id`, `document_id`, and `account_number`
respectively (see section 1.4 for the per-source canonical keys).

**raw.ingest_log**

| Column | Type | Notes |
|---|---|---|
| run_id | UUID PK DEFAULT gen_random_uuid() | |
| dataset | TEXT NOT NULL | 'opa', 'violations', 'transfers', 'delinquency' |
| started_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |
| finished_at | TIMESTAMPTZ | NULL until complete |
| rows_fetched | INT | total rows seen from API |
| rows_inserted | INT | rows actually inserted into raw |
| error | TEXT | NULL on success |

This satisfies the AC-2 verification query: `SELECT COUNT(*) FROM raw.ingest_log WHERE run_number = 2 AND rows_inserted > 0` (note: the story uses `run_number`; `ingest_log` stores the concept via the ordered `started_at`; the tester's AC-2 query is best rewritten against `run_id` ordering, but the design ensures `rows_inserted = 0` on a second identical run regardless of how the query is phrased).

### 1.2 staging schema

**staging.opa_properties** (current)

| Column | Type | Notes |
|---|---|---|
| parcel_id | TEXT PK | normalized from `parcel_number` |
| raw_id | BIGINT NOT NULL | FK → raw.opa_assessments.id (latest) |
| row_hash | TEXT NOT NULL | matches raw row that produced this version |
| location | TEXT | street address as-received |
| unit | TEXT | |
| zip_code | TEXT | |
| owner_1 | TEXT | |
| owner_2 | TEXT | |
| building_code | TEXT | |
| building_code_description | TEXT | |
| category_code | TEXT | |
| category_code_description | TEXT | |
| market_value | NUMERIC | |
| sale_date | DATE | |
| sale_price | NUMERIC | |
| taxable_land | NUMERIC | |
| taxable_building | NUMERIC | |
| exempt_land | NUMERIC | |
| exempt_building | NUMERIC | |
| _created_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |
| _updated_at | TIMESTAMPTZ NOT NULL DEFAULT now() | set on each upsert |

**staging.opa_properties_history**

Same columns plus:

| Column | Type | Notes |
|---|---|---|
| history_id | BIGSERIAL PK | |
| valid_from | TIMESTAMPTZ NOT NULL | copied from `_updated_at` of the row being replaced |
| valid_to | TIMESTAMPTZ NOT NULL DEFAULT now() | when this version was superseded |

Before upserting a changed row into `staging.opa_properties`, the pipeline copies the
existing row into `_history`. This satisfies AC-3.

**staging.li_violations** (current) — key columns:

| Column | Type |
|---|---|
| violation_id | TEXT PK |
| parcel_id | TEXT NOT NULL (FK → core.properties when populated) |
| raw_id | BIGINT NOT NULL |
| row_hash | TEXT NOT NULL |
| address | TEXT |
| violation_code | TEXT |
| violation_desc | TEXT |
| violation_date | DATE |
| case_opened_date | DATE |
| case_status | TEXT |
| _updated_at | TIMESTAMPTZ NOT NULL DEFAULT now() |

**staging.li_violations_history** — same SCD-2 pattern.

**staging.deed_transfers** (current) — key columns:

| Column | Type |
|---|---|
| document_id | TEXT PK |
| parcel_id | TEXT NOT NULL |
| raw_id | BIGINT NOT NULL |
| row_hash | TEXT NOT NULL |
| grantee | TEXT |
| grantor | TEXT |
| recording_date | DATE |
| sale_price | NUMERIC |
| document_type | TEXT |
| _updated_at | TIMESTAMPTZ NOT NULL DEFAULT now() |

**staging.deed_transfers_history** — same SCD-2 pattern.

**staging.tax_delinquency** (current) — key columns:

| Column | Type |
|---|---|
| account_number | TEXT PK |
| parcel_id | TEXT NOT NULL |
| raw_id | BIGINT NOT NULL |
| row_hash | TEXT NOT NULL |
| owner | TEXT |
| total_due | NUMERIC |
| num_years_owed | INT |
| lien_number | TEXT |
| _updated_at | TIMESTAMPTZ NOT NULL DEFAULT now() |

**staging.tax_delinquency_history** — same SCD-2 pattern.

### 1.3 core schema

**core.properties**

| Column | Type | Notes |
|---|---|---|
| parcel_id | TEXT PK | = staging.opa_properties.parcel_id |
| address_raw | TEXT NOT NULL | as-received from OPA |
| address_normalized | TEXT | NULL until DB-04 runs |
| zip_code | TEXT | |
| owner_1 | TEXT | |
| owner_2 | TEXT | |
| market_value | NUMERIC | |
| building_code | TEXT | |
| category_code | TEXT | |
| sale_date | DATE | |
| sale_price | NUMERIC | |
| source_updated_at | TIMESTAMPTZ NOT NULL | = staging._updated_at at time of core write |
| raw_id | BIGINT NOT NULL | FK → raw.opa_assessments.id |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |
| updated_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

AC-4 is satisfied: `parcel_id` and `address_raw` are NOT NULL. `address_normalized`
is intentionally nullable until DB-04; the AC-4 query checks `address_normalized`
specifically, so DB-04 must populate it before the acceptance test for DB-04 runs.
(The DB-03 acceptance test for AC-4 must check `address_raw`, not `address_normalized`
— the data-engineer should raise this with the PO if the story's SQL differs from the
design intent.)

**Note on AC-4 discrepancy:** The story's AC-4 verification SQL checks
`address_normalized IS NULL`. Since address normalization is DB-04's scope, `core.properties`
at the end of DB-03 will have `address_normalized = NULL` for all rows. The tester
must confirm with PO whether AC-4 should check `address_raw` for DB-03, deferring the
`address_normalized` check to DB-04. This is a **blocking open question** for the PO.

### 1.4 Canonical keys per source

| Dataset | Socrata resource | `source_id` column | Notes |
|---|---|---|---|
| OPA assessments | w7rb-qrn8 | `parcel_number` | Standard AIS parcel key |
| L&I violations | t2h5-k7ba | `violationid` | Socrata field name |
| RTT transfers | 4iqs-r3wa | `document_id` | Deed recording number |
| Tax delinquency | dknd-xqk9 | `account_number` | Tax account, maps to parcel via OPA join |

`parcel_id` in staging and core is populated from `parcel_number` (OPA), from the
address-matched field in violations and transfers, and from a join through OPA for
tax delinquency. All four staging tables must have a non-null `parcel_id` before
any row is inserted into `core.properties`. Rows that cannot resolve a `parcel_id`
are written to staging with `parcel_id = NULL` and skipped for core promotion; they
are logged in `raw.ingest_log.error` as a warning (not a pipeline failure).

---

## 2. Idempotency contract

### Second run inserts 0 raw rows (AC-2)

```
fetch page from API
  → for each record:
      compute row_hash = SHA-256(json.dumps(record, sort_keys=True, ensure_ascii=False))
      INSERT INTO raw.<table> (source_id, row_hash, payload, run_id)
      VALUES (%s, %s, %s, %s)
      ON CONFLICT (source_id, row_hash) DO NOTHING
  → update ingest_log.rows_inserted = COUNT of actually inserted rows
```

If upstream data is unchanged, every record hits the conflict and `rows_inserted = 0`.
The pipeline logs `"No new rows — skipped staging upsert"` and exits cleanly. This
satisfies AC-7 (no staging upsert means no history writes, no core updates, and the
run completes in well under 90 seconds because it only fetches page 1 to compare
hashes — see pagination strategy below).

**Optimization:** before fetching all pages, the pipeline can compare the page-1
`$order` + `$limit=1` record hash against the most recent raw hash for that source.
If they match, skip remaining pages and log "No new rows — skipped staging upsert".
This cuts the no-op run from ~30s (full re-fetch) to ~2s (single-record probe).

### One changed row updates exactly 1 staging row (AC-3)

```
for each new raw row (rows_inserted > 0):
  look up staging current row by parcel_id
  if exists AND row_hash differs:
    INSERT INTO staging.<table>_history (SELECT *, valid_from=_updated_at, valid_to=now() FROM staging.<table> WHERE pk = parcel_id)
    UPDATE staging.<table> SET <all columns>, row_hash, _updated_at = now() WHERE pk = parcel_id
  elif not exists:
    INSERT INTO staging.<table> (<all columns>)
  → upsert staging row into core.properties
```

The upsert into core uses `INSERT ... ON CONFLICT (parcel_id) DO UPDATE SET ...`.

---

## 3. Pipeline structure

```
pipelines/
  __init__.py
  base.py          # BasePipeline: fetch → raw → staging → core loop
  opa.py           # OPAPipeline(BasePipeline)
  violations.py    # ViolationsPipeline(BasePipeline)
  transfers.py     # TransfersPipeline(BasePipeline)
  delinquency.py   # DelinquencyPipeline(BasePipeline)
  run.py           # entry point: CLI args, calls selected pipeline(s)
```

### pipelines/base.py — public interface

```python
class BasePipeline:
    dataset: str                        # e.g. "opa"
    socrata_url: str                    # full resource URL
    source_id_field: str               # field name used as source_id
    raw_table: str                      # e.g. "raw.opa_assessments"
    staging_table: str                  # e.g. "staging.opa_properties"

    def fetch_pages(self, offset: int = 0, limit: int = 50_000) -> Iterator[list[dict[str, Any]]]: ...
    def compute_hash(self, record: dict[str, Any]) -> str: ...
    def insert_raw(self, conn: Connection, records: list[dict[str, Any]], run_id: str) -> int: ...
    def upsert_staging(self, conn: Connection, raw_ids: list[int]) -> int: ...
    def upsert_core(self, conn: Connection) -> int: ...
    def run(self, conn: Connection, dry_run: bool = False) -> IngestResult: ...
```

`IngestResult` is a dataclass: `{run_id, dataset, rows_fetched, rows_inserted, rows_updated_staging, rows_updated_core, elapsed_seconds, skipped: bool}`.

Each subclass overrides `upsert_staging` to handle its specific column mapping. The
`insert_raw` and `compute_hash` methods live in `BasePipeline` and are shared.

### pipelines/run.py — entry point

```
usage: python -m pipelines.run [--dataset {philly,opa,violations,transfers,delinquency}]
                                [--dry-run]
                                [--limit N]        # max rows per page, default 50000
```

`--dry-run` fetches and hashes but does not write to the database. Used by `make ingest-dry-run`.

### Pagination strategy

The Socrata API uses `$offset` + `$limit`. The pipeline fetches pages until a page
returns fewer rows than the limit (last page). For OPA (~580k rows at 50k/page = 12
pages), a full ingest takes roughly 60–90s on a typical connection — within the AC-7
90s budget for no-op runs only if the early-exit optimization is active. For first
runs, 90s may be tight; CI should allow 5 minutes for a first-run acceptance test.

---

## 4. Migrations

Fourteen SQL files in `db/migrations/`, numbered sequentially from where DB-01 left
off. The data-engineer must check the last migration number before naming these.
Assuming DB-01 ends at `0003_`:

| File | Creates |
|---|---|
| `0004_raw_schema.sql` | `CREATE SCHEMA raw;` |
| `0005_raw_ingest_log.sql` | `raw.ingest_log` |
| `0006_raw_opa_assessments.sql` | `raw.opa_assessments` with unique (source_id, row_hash) |
| `0007_raw_li_violations.sql` | `raw.li_violations` |
| `0008_raw_deed_transfers.sql` | `raw.deed_transfers` |
| `0009_raw_tax_delinquency.sql` | `raw.tax_delinquency` |
| `0010_staging_schema.sql` | `CREATE SCHEMA staging;` |
| `0011_staging_opa_properties.sql` | `staging.opa_properties` + `staging.opa_properties_history` |
| `0012_staging_li_violations.sql` | `staging.li_violations` + `staging.li_violations_history` |
| `0013_staging_deed_transfers.sql` | `staging.deed_transfers` + `staging.deed_transfers_history` |
| `0014_staging_tax_delinquency.sql` | `staging.tax_delinquency` + `staging.tax_delinquency_history` |
| `0015_core_schema.sql` | `CREATE SCHEMA core;` (if not already present) |
| `0016_core_properties.sql` | `core.properties` |
| `0017_raw_table_counts_view.sql` | `CREATE VIEW raw.table_counts AS ...` (used in AC-1) |

Each migration file runs inside a transaction (`BEGIN; ... COMMIT;`). The migration
runner (to be defined by DB-01, or added in this story if missing) applies files in
numeric order and skips already-applied ones.

---

## 5. Sequence of calls

```
make ingest DATASET=philly
  → pipelines/run.py --dataset philly
      → open DB connection (DATABASE_URL from env)
      → for each pipeline in [OPA, Violations, Transfers, Delinquency]:
          → INSERT INTO raw.ingest_log (dataset, started_at) → run_id
          → fetch_pages() [HTTP GET Socrata, paginated]
              → early-exit probe: compare first record hash to latest raw row
              → if match: log "No new rows — skipped staging upsert", update ingest_log
              → else: iterate all pages
          → insert_raw(records, run_id) → rows_inserted count
          → if rows_inserted > 0:
              → upsert_staging(raw_ids)
              → upsert_core()
          → UPDATE raw.ingest_log SET finished_at, rows_fetched, rows_inserted
      → print summary table
```

### Failure modes

| Failure | Behaviour |
|---|---|
| Socrata API returns HTTP 5xx | Retry 3× with exponential backoff (2s, 4s, 8s). After 3 failures, log error to `ingest_log`, mark run failed, continue with next dataset. |
| Socrata returns a record with no `parcel_number` | Log warning, skip that record. Count in `ingest_log.error` as a note. Do not fail the run. |
| DB connection lost mid-ingest | The raw INSERT is inside a transaction per page. A lost connection rolls back the current page; on reconnect the pipeline retries that page. `ON CONFLICT DO NOTHING` ensures the retry is safe. |
| Staging upsert finds a row with NULL parcel_id | Skip core promotion. Log count. |
| All four datasets fail | Pipeline exits non-zero. CI marks the run failed. |

---

## 6. Testing approach

Tests live in `tests/unit/test_db03_pipeline.py` and run with `make test SUITE=db03`.

### No live API calls

All tests use fixture JSON files stored in `tests/fixtures/db03/`. Each fixture
contains 5–10 records from the real Socrata API, captured once and committed to the
repo. The pipeline's HTTP client is injected as a dependency so tests can substitute
a fixture reader.

```python
# tests/fixtures/db03/
opa_page1.json         # 5 OPA records, all valid
opa_page1_changed.json # same 5 records, one market_value changed by $1
li_violations_page1.json
deed_transfers_page1.json
tax_delinquency_page1.json
```

### Test cases required by AC-6

1. **Dedup logic** — insert `opa_page1.json`, then insert again; assert `rows_inserted = 0` on second call. Uses an in-memory SQLite substitute or a real Postgres test DB spun up by `docker compose up db`.
2. **Null parcel_id rejection** — insert a record with `parcel_number = None`; assert the record is skipped and does not appear in staging, and the run does not raise an exception.
3. **Idempotency assertion** — insert `opa_page1.json`, then insert `opa_page1_changed.json`; assert `rows_inserted = 1`, `staging.opa_properties` has 1 row with `_updated_at = current_run_ts`, and `staging.opa_properties_history` has 1 row for the previous version.
4. **Hash stability** — same record serialized twice produces the same hash (guards against dict ordering issues).
5. **Core promotion** — after a staging upsert, assert the corresponding `core.properties` row exists with non-null `parcel_id` and `address_raw`.

### Test DB strategy

`make test` already does `docker compose up -d --wait db`. Tests in `tests/unit/`
that need Postgres use a `db_conn` pytest fixture that reads `TEST_DATABASE_URL` from
env (defaulting to the Compose DB). Each test wraps in a transaction and rolls back
at teardown (no persistent state between tests).

---

## 7. Dependencies

Add to `pyproject.toml` under `[project] dependencies`:

```toml
dependencies = [
  "httpx>=0.27",        # async-capable HTTP client; preferred over requests per frozen stack
  "psycopg[binary]>=3.1",  # psycopg3; binary package avoids libpq compilation
  "python-dotenv>=1.0", # DATABASE_URL from .env in local dev
]
```

**Why httpx over requests:** httpx supports both sync and async, has a clean `transport`
injection point (used by tests to substitute fixture responses without monkeypatching),
and aligns with FastAPI's test client pattern already in use.

**Why psycopg3 over asyncpg:** psycopg3 is synchronous by default (matching the
pipeline's sync design), supports the `COPY` protocol for bulk inserts if needed in
a future story, and has better mypy stubs than psycopg2.

**polars / pandas are not needed:** the pipeline's transform work (hash, type-cast,
upsert) is straightforward row-by-row processing. Pulling in a dataframe library
adds 50+ MB to the image for no structural benefit at this data volume.

---

## 8. Makefile targets

Add to the existing `Makefile`:

```makefile
DATASET ?= philly

ingest:
	uv run python -m pipelines.run --dataset $(DATASET)

ingest-dry-run:
	uv run python -m pipelines.run --dataset $(DATASET) --dry-run

test:
	docker compose up -d --wait db
	uv run pytest tests/unit/ -q $(if $(SUITE),--co -q -k $(SUITE),)
```

The `SUITE` variable allows `make test SUITE=db03` to run only the DB-03 test module
(via pytest `-k db03` keyword filter against file names).

---

## 9. Answers to open questions from story.md

| Question | Answer |
|---|---|
| Raw table pattern | Append-only with `row_hash` (SHA-256). See ADR-0003. |
| Canonical key for OPA | `parcel_number`. Single column, not composite. |
| Audit pattern | SCD-2 history table (`staging.<table>_history`). See ADR-0003. |
| Paginated API vs static fixture | Both: pipeline supports pagination in production; tests use static fixture files in `tests/fixtures/db03/`. |

**Open question for PO (blocking):** AC-4 checks `address_normalized IS NULL` as a
failure condition, but address normalization is DB-04's scope. At the end of DB-03,
`address_normalized` will be NULL for all rows. The tester cannot pass AC-4 as written.
Recommend PO changes AC-4 to check `address_raw IS NULL` for DB-03, and adds an
`address_normalized` check to DB-04's acceptance criteria.

---

## 10. Implementation checklist (ordered for data-engineer)

Work on branch `feat/DB-03-philly-ingest`.

- [ ] 1. Confirm last migration number from `db/migrations/` and rename the 14 migration files in this design to match.
- [ ] 2. Write migration `000N_raw_schema.sql` through `000N_raw_table_counts_view.sql`. Run `make up` and verify all schemas and tables exist.
- [ ] 3. Add `httpx`, `psycopg[binary]`, and `python-dotenv` to `pyproject.toml` dependencies. Run `uv lock` and commit `uv.lock`.
- [ ] 4. Create `pipelines/__init__.py`, `pipelines/base.py` with `BasePipeline` and `IngestResult`. Add full mypy-compatible type annotations. Run `make lint`.
- [ ] 5. Create `pipelines/opa.py` (OPAPipeline). Implement `upsert_staging` with the OPA column mapping. Do not hardcode the Socrata URL — read from `PHILLY_OPA_URL` env var, defaulting to the production endpoint.
- [ ] 6. Create fixture `tests/fixtures/db03/opa_page1.json` by running a one-off fetch against the live API (5 records). Create `opa_page1_changed.json` by editing one `market_value`. Commit both.
- [ ] 7. Write `tests/unit/test_db03_pipeline.py` covering all five test cases in section 6. All tests must pass with `make test SUITE=db03` before proceeding.
- [ ] 8. Create `pipelines/violations.py`, `pipelines/transfers.py`, `pipelines/delinquency.py`. Add matching fixtures and extend the test file for null-parcel-id and idempotency checks for each dataset.
- [ ] 9. Create `pipelines/run.py` with `--dataset` and `--dry-run` arguments.
- [ ] 10. Add `ingest` and `ingest-dry-run` targets to `Makefile`. Verify `make ingest-dry-run DATASET=opa` runs without hitting a live database.
- [ ] 11. Run `make lint test` — both must pass clean.
- [ ] 12. Write `docs/work/DB-03/impl-notes.md` noting: actual migration numbers used, any deviation from this design, and the fixture capture date.
- [ ] 13. Set story status to `review` in `docs/work/DB-03/story.md` and open a draft PR on branch `feat/DB-03-philly-ingest`.
