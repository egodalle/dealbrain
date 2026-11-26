---
owner: tester
last-reviewed: 2026-11-26
stability: stable
---

# DB-05 Test Report: Explainable distress score + `/leads` data product with CSV export

**Story status at time of test:** review
**Branch:** feat/DB-05-distress-score-leads
**Tester:** tester agent
**Date:** 2026-11-26

---

## Acceptance Criteria Results

| AC | Description | Result | Notes |
|---|---|---|---|
| AC-1 | `core.properties` has `distress_score INTEGER` and `score_components JSONB` columns | SKIPPED / CANNOT-VERIFY | Requires live Postgres + pgvector container. Migration file `db/migrations/0014_core_properties_score.sql` verified to exist and contain `ADD COLUMN IF NOT EXISTS distress_score   INTEGER` and `ADD COLUMN IF NOT EXISTS score_components JSONB`. Column type is `INTEGER` as required. |
| AC-2 | Sum invariant: every scored row has `distress_score == sum(score_components values)` | SKIPPED / CANNOT-VERIFY (live SQL); unit test proxy PASS | Live SQL check requires running database. `test_components_sum_equals_total` and `test_distribute_maintains_sum` (50 random cases, seed 42) both pass, covering the rounding algorithm end-to-end without a DB. |
| AC-3 | `score_components` has at least 3 named factors for every scored row | SKIPPED / CANNOT-VERIFY | Requires live database. Design mandates 4 keys (`delinquency`, `violations`, `years_held`, `value_gap`); unit tests confirm all four are written. |
| AC-4 | `make score` is idempotent — second run with no data change leaves no rows touched | SKIPPED / CANNOT-VERIFY | Requires live database. Idempotency guard (`score_input_hash` column) is present in migration and exercised in `run()`. |
| AC-5 (story) | `GET /leads?limit=N` returns top-N canonical properties ordered by `distress_score DESC` with required keys | SKIPPED / CANNOT-VERIFY (live curl); unit test proxy PASS | Live curl requires running portal + DB. `test_leads_endpoint_shape` passes: status 200, list of 2 items, all 5 keys present (`parcel_number`, `address_normalized`, `distress_score`, `score_components`, `owner`). `test_leads_min_score_filter` passes: min_score filtering works. |
| AC-6 (story) | `make export-leads` produces `exports/leads.csv` with correct 6-column header and >= 2 lines | SKIPPED / CANNOT-VERIFY (live make target); unit test proxy PASS | Live target requires running portal. `test_csv_export_columns` passes: `GET /leads/export.csv` returns `text/csv`, header is exactly `parcel_number,address_normalized,distress_score,factor_1,factor_2,factor_3`, body has >= 2 lines, top-factor ordering is correct. |
| AC-7 (story) | `make test SUITE=db05` runs unit tests and all pass with no skips | PASS | 16/16 tests pass. See full pytest output below. |

---

## Additional Verification Checks

| Check | Command | Result |
|---|---|---|
| `make lint` exits 0 | `make lint` | PASS — ruff check, ruff format --check, mypy --strict all clean |
| `make test` exits 0 (all 90 tests) | `make test` | PASS — 90 passed, 1 warning (starlette deprecation, non-blocking) |
| Migration file exists | `test -f db/migrations/0014_core_properties_score.sql` | PASS — file exists |
| `distress_score INTEGER` in migration | read file | PASS — line 4: `ADD COLUMN IF NOT EXISTS distress_score   INTEGER` (extra spaces caused literal grep to return empty; column type is INTEGER) |
| All 4 weight constants present | `grep -n "W_DELINQUENCY\|W_VIOLATIONS\|W_YEARS_HELD\|W_VALUE_GAP" pipelines/score.py` | PASS — lines 22–25 define all four; line 27 asserts sum == 100 |
| Both `/leads` routes in portal | `grep -n "/leads" apps/portal/main.py` | PASS — line 91: `@app.get("/leads")`, line 112: `@app.get("/leads/export.csv")` |

---

## Full pytest output — DB-05 suite

```
$ uv run pytest tests/unit/db05/ -v
============================= test session starts ==============================
platform darwin -- Python 3.12.16, pytest-9.2.0, pluggy-1.7.0 -- /Users/edgodalle/dealbrain/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/edgodalle/dealbrain
configfile: pyproject.toml
plugins: anyio-4.6.0
collecting ... collected 16 items

tests/unit/db05/test_leads_api.py::test_leads_endpoint_shape PASSED      [  6%]
tests/unit/db05/test_leads_api.py::test_leads_min_score_filter PASSED    [ 12%]
tests/unit/db05/test_leads_api.py::test_csv_export_columns PASSED        [ 18%]
tests/unit/db05/test_score.py::test_components_sum_equals_total PASSED   [ 25%]
tests/unit/db05/test_score.py::test_score_range_low PASSED               [ 31%]
tests/unit/db05/test_score.py::test_score_range_high PASSED              [ 37%]
tests/unit/db05/test_score.py::test_score_range_clamped PASSED           [ 43%]
tests/unit/db05/test_score.py::test_input_hash_deterministic PASSED      [ 50%]
tests/unit/db05/test_score.py::test_input_hash_changes PASSED            [ 56%]
tests/unit/db05/test_score.py::test_distribute_maintains_sum PASSED      [ 62%]
tests/unit/db05/test_score.py::test_delinquency_cap PASSED               [ 68%]
tests/unit/db05/test_score.py::test_violations_cap PASSED                [ 75%]
tests/unit/db05/test_score.py::test_years_held_cap PASSED                [ 81%]
tests/unit/db05/test_score.py::test_value_gap_below_median PASSED        [ 87%]
tests/unit/db05/test_score.py::test_value_gap_above_median PASSED        [ 93%]
tests/unit/db05/test_score.py::test_value_gap_no_data PASSED             [100%]

16 passed, 1 warning in 0.18s
```

```
$ make lint
uv run ruff check .
All checks passed!
uv run ruff format --check .
35 files already formatted
uv run mypy --strict .
Success: no issues found in 26 source files
```

```
$ make test
 Container dealbrain-db-1  Running
 Container dealbrain-db-1  Waiting
 Container dealbrain-db-1  Healthy
uv run pytest tests/unit/ -q
........................................................................................ [ 80%]
..................
90 passed, 1 warning in 0.52s
```

---

## Targeted test commands (as specified)

```
$ uv run pytest tests/unit/db05/test_score.py::test_components_sum_equals_total -v
1 passed in 0.05s

$ uv run pytest tests/unit/db05/test_leads_api.py -v
3 passed, 1 warning in 0.21s

$ uv run pytest tests/unit/db05/ -v -k "csv"
1 passed, 15 deselected, 1 warning in 0.20s
```

---

## Notes and observations

1. **`distress_score INTEGER` grep false negative** — the story check `grep -n "distress_score INTEGER"` returns empty because the migration uses two spaces between the column name and type (`distress_score   INTEGER`). The column type is `INTEGER` as required by AC-1; this is a cosmetic formatting choice, not a defect.

2. **`SMALLINT` vs `INTEGER`** — design.md proposed `SMALLINT` but noted AC-1 says `INTEGER`. The data-engineer chose `INTEGER` per the story AC wording. This is correct and consistent with AC-1.

3. **`_input_hash` stored in separate column** — per design.md's preferred alternative, `_input_hash` is stored in `score_input_hash TEXT` column, not inside `score_components`. This keeps `score_components` clean (4 integer keys only), so the AC-2 `jsonb_each_text` invariant SQL works exactly as written without filtering the hash key. Correct call.

4. **`add_column IF NOT EXISTS`** — the migration uses `IF NOT EXISTS` guards on all three `ALTER TABLE` column additions. This makes the migration safely re-runnable without error on a database that already has the columns. No behavioral downside.

5. **Starlette deprecation warning** — `fastapi.testclient` recommends `httpx2` over `httpx`. This is a non-breaking upstream deprecation warning that does not affect correctness.

6. **DB-05 suite is 16 tests, not 13** — impl-notes.md lists 13 tests in `test_score.py` but actual count is 13 score tests + 3 endpoint tests = 16 total. The suite count in impl-notes.md is accurate for the per-file breakdown; total is 16.

---

## Bugs filed

None. No defects found in locally verifiable criteria.

---

## Overall result

PASS (locally verifiable criteria). AC-1 through AC-6 (live-database criteria) are SKIPPED / CANNOT-VERIFY per instructions; their unit-test proxies all pass.
