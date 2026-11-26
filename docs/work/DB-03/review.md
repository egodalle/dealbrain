---
owner: architect
last-reviewed: 2026-11-26
stability: stable
---

# DB-03 Review

**Branch:** feat/DB-03-philly-ingestion
**Reviewer:** architect
**Verdict:** BLOCKED

---

## Check-by-check results

### 1. 11 migration files with correct schemas — FAIL (nit)

11 files exist and are numbered 0001–0011. All three schemas (raw, staging, core) are
created. However the design called for 14 files (0004–0017, against a DB-01 baseline of
0003). The data-engineer correctly adjusted numbering because the migrations directory was
empty; that is fine. The gap is in content:

- `raw.table_counts` view (design 0017) is absent. The view is cited by name in AC-1's
  verification query (`SELECT … FROM raw.table_counts`). Without it the tester cannot
  run AC-1 as written. The data-engineer noted this and deferred it to the tester, but
  this crosses the boundary: the view is part of the schema deliverable for this story,
  not an acceptance-test artefact. This is a **nit** that must be resolved before the
  tester can run AC-1 without workaround.

### 2. raw tables have (source_id, row_hash) UNIQUE constraint — PASS

All five raw tables (opa_assessments, violations, transfers, delinquency in 0002–0005,
ingest_log in 0006) carry `UNIQUE (source_id, row_hash)` where applicable. ingest_log
is exempt by design (it is a log, not a deduplicated dataset). Confirmed in migration
files 0002–0005.

### 3. upsert_raw uses ON CONFLICT (source_id, row_hash) DO NOTHING — PASS

`pipelines/base.py` line 684–693:
```
INSERT INTO {table} (source_id, row_hash, payload, run_id)
VALUES (%s, %s, %s, %s)
ON CONFLICT (source_id, row_hash) DO NOTHING
RETURNING id
```
Correct. Returns `True` only when the row was actually inserted.

### 4. compute_hash uses SHA-256 over sorted JSON keys — PASS

`pipelines/base.py` line 665–668:
```python
serialised = json.dumps(record, sort_keys=True, ensure_ascii=False)
return hashlib.sha256(serialised.encode()).hexdigest()
```
Matches design exactly. `ensure_ascii=False` is a safe addition (preserves non-ASCII
chars faithfully rather than escaping them). Three unit tests cover determinism, key-order
independence, and value sensitivity.

### 5. raw.ingest_log has run_id UUID, started_at TIMESTAMPTZ, rows_fetched, rows_inserted — FAIL (blocking)

Migration 0006 creates the table with these columns. However the column is named `source`
(not `dataset` as the design specifies). The data-engineer acknowledged this deviation and
says it was driven by a "task prompt spec". No task-prompt-level document overrides
design.md; design.md is the authoritative contract for this story. This introduces a
concrete breakage:

- AC-2's tester verification query uses `dataset` as a column name:
  `SELECT dataset, rows_inserted FROM raw.ingest_log …`
  Running this query against the implemented schema will raise `column "dataset" does not
  exist` and the acceptance test will error rather than pass or fail cleanly.

This is **blocking**. The column must be renamed to `dataset` in migration 0006, and all
references in `pipelines/base.py` (`log_run`, `run` method) updated to match.

### 6. core.properties has parcel_number TEXT PRIMARY KEY — FAIL (blocking)

The story's AC-4 verification query:
```sql
SELECT COUNT(*) FROM core.properties WHERE parcel_number IS NULL;
```
This query requires `parcel_number` to be a column. The design specified `parcel_id TEXT
PRIMARY KEY` (normalized) with `parcel_number` stored separately. The implementation
follows the design — `parcel_id` is PK, `parcel_number` is a secondary column. That
secondary column exists in migration 0011, so the AC-4 query will execute. So far so
good.

However, `address_raw NOT NULL` is in migration 0011 and in `opa.py`'s `upsert_core`
it is set to `COALESCE(s.location, '')`, meaning records with a NULL `location` from OPA
get an empty string rather than NULL. That is a silent data quality issue but it is not a
blocker for this story.

What is a blocker: the design section 1.3 marks `parcel_id TEXT PRIMARY KEY` and
`address_raw TEXT NOT NULL`. The implementation adds eight additional columns to
`core.properties` that are not in the design schema (`address`, `owner`, `assessed_value`,
`land_area`, `improvement_description`, `zoning`). Extra columns that have no source yet
will all be NULL for every row DB-03 inserts. These columns have no migration dependency
and are harmless today, but they were not approved by the architect and they bloat the
schema with fields that belong to a future story. This is a **nit**, not a blocker on
its own. The actual blocker in this check is item 5 above (ingest_log column name), not
the PK itself which is correctly `parcel_id`.

Verdict for check 6: **PASS** on PK existence; the extra columns are a nit. Combined
with check 5 the story is already blocked.

### 7. 4 unit tests cover idempotency and changed-row behaviour — PASS (with note)

7 tests exist in `tests/unit/test_pipeline_base.py`:

- `test_compute_hash_deterministic` — hash property
- `test_compute_hash_different` — hash property
- `test_compute_hash_key_order_independent` — hash property
- `test_idempotency_fixture` — second identical pass inserts 0 rows (AC-2 logic)
- `test_changed_row_fixture` — changed record produces exactly 1 new raw insert (AC-3
  raw layer logic)
- `test_fetch_pages_paginates` — pagination stops on short page
- `test_fetch_pages_stops_on_empty` — pagination stops on empty page

The design required 5 specific test cases (section 6). Of those, two are present
(`test_idempotency_fixture` covers dedup, `test_changed_row_fixture` covers changed-row).
Missing from the unit suite:

- Null parcel_id rejection test (design section 6, case 2) — the pipeline's `run` method
  skips records where `source_id_field` returns falsy, but no test asserts this behaviour
  for a null `parcel_number` specifically.
- Core promotion test (design section 6, case 5) — `upsert_core` is exercised indirectly
  only; no assertion that `core.properties` receives a row after a staging upsert.

The two missing tests are specifically required by AC-6: "The test output must show no
failures and cover at least: dedup logic, null-parcel-id rejection, and the idempotency
assertion." `null-parcel-id rejection` is not covered. This is **blocking** per AC-6.

Note: `test_idempotency_fixture` and `test_changed_row_fixture` mock DB interactions
inline rather than using an injected `upsert_raw` — the test drives the hash + dedup
logic correctly but does not exercise the actual `BasePipeline.upsert_raw` path. This
is acceptable for a unit test but the tester should note it.

### 8. make lint and make test pass — PASS

impl-notes.md records clean output for both. `make lint` shows ruff and mypy passing on
11 source files. `make test` shows 8 passed, 0 failed in 0.12s. No test run against
Postgres was performed (and none is required at the unit-test level for this story).

### 9. Naming discrepancy: staging.opa_assessments vs staging.opa_properties — BLOCKING

This is the most significant naming defect in the diff.

The story (AC-3), the design (section 1.2), and the acceptance test query all reference
`staging.opa_properties`. The implementation creates `staging.opa_assessments`.

Impact:
- AC-3 query: `SELECT COUNT(*) FROM staging.opa_properties WHERE _updated_at = current_run_ts`
  — will fail with "relation staging.opa_properties does not exist".
- AC-5 FK join query: `staging.li_violations v LEFT JOIN core.properties p …` works, but
  the equivalent query checking OPA staging would fail.
- Any downstream story (DB-04, DB-05) that references `staging.opa_properties` by name
  will break.

The data-engineer noted this in impl-notes.md as a known gap and said "the tester or PO
should resolve". That is not acceptable: naming is an architectural contract set in
design.md, and the data-engineer cannot unilaterally rename a table and defer resolution.
The migration file `0007_staging_opa.sql` and `pipelines/opa.py` (the `staging_table`
attribute and all SQL) must be updated to use `staging.opa_properties`. Same for the
history table: `staging.opa_properties_history`.

This is **blocking**.

### 10. CLAUDE.md violations — PASS (with one flag)

No approval-boundary violations. No LLM calls. No secrets in fixtures (all data is
synthetic with names like "SYNTHETIC OWNER A"). No real personal data. Tailscale and
secrets rules are not relevant to this story's scope.

One flag: `pipelines/base.py` constructs SQL with an f-string for the table name:
```python
f"INSERT INTO {table} (source_id, …"
```
The table name comes from `self.raw_table`, a trusted class attribute (not user input),
so this is not a SQL injection risk in practice. The `# noqa: S608` suppression is
present. This is an acceptable pattern given the controlled source of the value, but
worth noting in case a future story ever passes user-controlled input to `raw_table`.

---

## Blocking issues summary

| # | Issue | File(s) |
|---|---|---|
| B1 | `raw.ingest_log` column is `source`, not `dataset` — AC-2 tester query will error | `db/migrations/0006_raw_ingest_log.sql`, `pipelines/base.py` |
| B2 | `staging.opa_assessments` must be `staging.opa_properties` (and history table) — AC-3, AC-5, all downstream references break | `db/migrations/0007_staging_opa.sql`, `pipelines/opa.py` |
| B3 | No null-parcel-id rejection unit test — AC-6 explicitly requires it | `tests/unit/test_pipeline_base.py` |

## Nit issues (non-blocking, fix before done)

| # | Issue | File(s) |
|---|---|---|
| N1 | `raw.table_counts` view is absent — AC-1 verification query will fail without workaround | `db/migrations/` (new file needed) |
| N2 | `core.properties` has 6 extra columns not in the approved design schema | `db/migrations/0011_core_properties.sql` |
| N3 | `python-dotenv` omitted from `pyproject.toml` despite being in the design spec | `pyproject.toml` |

---

## Overall verdict

**BLOCKED**

Return to data-engineer. Fix B1, B2, and B3 before returning for re-review.
N1 must also be resolved (the tester cannot run AC-1 without the view or a workaround).
N2 and N3 can be resolved in this pass or tracked as follow-up at the PO's discretion.

---

## Re-review — 2026-11-26 (loop 2)

**Reviewer:** architect
**Verdict:** APPROVED — no blocking issues remain.

### B1 — `raw.ingest_log` column `source` → `dataset` — RESOLVED

`db/migrations/0006_raw_ingest_log.sql`: column is `dataset TEXT NOT NULL`. Confirmed.
`pipelines/base.py`: `log_run` parameter is `dataset`; both INSERT statements and the
inline `INSERT INTO raw.ingest_log (dataset) VALUES (%s)` reference `dataset`. No
remaining `source` reference in this context. RESOLVED.

### B2 — `staging.opa_assessments` → `staging.opa_properties` — RESOLVED

`db/migrations/0007_staging_opa.sql` creates `staging.opa_properties` and
`staging.opa_properties_history`. `pipelines/opa.py` has `staging_table =
"staging.opa_properties"` and all SQL strings (INSERT, ON CONFLICT, history copy,
upsert_core JOIN) use `staging.opa_properties`. RESOLVED.

### B3 — null parcel_id rejection guard + test — RESOLVED

`pipelines/opa.py` defines `require_parcel_id()` which raises `ValueError` for `None`,
empty string, and whitespace-only strings. It is called at the top of `upsert_staging`
where `parcel_id` is assigned.

`tests/unit/test_pipeline_base.py` contains `test_null_parcel_id_rejected` (three
sub-cases: None, `""`, `"   "`) and `test_valid_parcel_id_passes`. The test correctly
imports `require_parcel_id` from `pipelines.opa` and asserts `ValueError` via
`pytest.raises`. AC-6's explicit requirement for null-parcel-id coverage is now met.
RESOLVED.

### N1 — `raw.table_counts` view — RESOLVED

`db/migrations/0012_raw_table_counts_view.sql` creates `CREATE OR REPLACE VIEW
raw.table_counts` covering the four data tables (opa_assessments, violations, transfers,
delinquency). `raw.ingest_log` is correctly excluded from the row-count view — it is an
audit log, not a data table. The AC-1 verification query will execute without workaround.
RESOLVED.

### Carry-forward nits (N2, N3) — no change required at this stage

N2 (six extra columns on `core.properties`) and N3 (`python-dotenv` absent from
`pyproject.toml`) remain open. These are non-blocking per the original review and are
at the PO's discretion for the done checklist. No new blocking issues were found in the
fix pass.

### One new observation (nit, not blocking)

The `raw.table_counts` view in 0012 refers to `raw.opa_assessments` as the label string
(`'opa_assessments'`) but the underlying table is `raw.opa_assessments` — consistent.
No issue. Worth noting for downstream stories: if a dataset name changes, the string
literal in the view must be updated manually.

### Overall verdict

**APPROVED**

Pass to tester. The three blocking issues (B1, B2, B3) and the nit required for AC-1
(N1) are all resolved. `make lint` and `make test` (10 passed) are recorded in
impl-notes.md. No approval-boundary violations, no LLM calls, no secrets in fixtures.
