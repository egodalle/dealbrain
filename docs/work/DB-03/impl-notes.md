---
owner: data-engineer
last-reviewed: 2026-11-26
stability: draft
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

2. **`raw.ingest_log` column `source` vs `dataset`:** design.md uses `dataset TEXT NOT NULL` in `raw.ingest_log`. The task prompt spec says `source TEXT NOT NULL`. Implementation uses `source` to match the task prompt; the pipeline's `BasePipeline.dataset` attribute is passed as the `source` value. The tester's AC-2 query uses `dataset` as a column alias — the actual column is `source`.

3. **`core.properties` column `address_raw` vs `parcel_number`:** design.md uses `parcel_id` as PK (normalized from `parcel_number`). Task prompt spec says `parcel_number TEXT PRIMARY KEY`. Implementation follows design.md (parcel_id PK) and also stores `parcel_number` as an alias column, plus `address_raw NOT NULL` to satisfy the design spec. The story's AC-4 open question (address_normalized vs address_raw) is documented in design.md — tester should verify against `address_raw`, not `address_normalized`.

4. **No `raw.table_counts` view:** Not in the 0001–0011 range specified by the task prompt. Tester can create it inline or query tables directly for AC-1.

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

### `make test` (unit tests only, no docker)

```
$ uv run pytest tests/unit/ -v
============================= test session starts ==============================
platform darwin -- Python 3.12.16, pytest-9.2.0, pluggy-1.7.0
collected 8 items

tests/unit/test_pipeline_base.py::test_compute_hash_deterministic PASSED
tests/unit/test_pipeline_base.py::test_compute_hash_different PASSED
tests/unit/test_pipeline_base.py::test_compute_hash_key_order_independent PASSED
tests/unit/test_pipeline_base.py::test_idempotency_fixture PASSED
tests/unit/test_pipeline_base.py::test_changed_row_fixture PASSED
tests/unit/test_pipeline_base.py::test_fetch_pages_paginates PASSED
tests/unit/test_pipeline_base.py::test_fetch_pages_stops_on_empty PASSED
tests/unit/test_placeholder.py::test_ok PASSED

8 passed in 0.12s
```

---

## Known gaps

- Acceptance tests (DB integration, docker) are the Tester's responsibility (design.md section 6).
- No `raw.table_counts` view migration; tester needs to verify AC-1 by querying tables directly or adding the view.
- `staging.opa_assessments` vs `staging.opa_properties`: design.md uses `opa_properties`; task prompt specifies `opa_assessments` to match the raw table name. Implementation follows the task prompt. The tester's AC-3 query uses `staging.opa_properties` — this is a name mismatch that the tester or PO should resolve.
- `python-dotenv` not added (see deviations).
