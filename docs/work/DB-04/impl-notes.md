---
owner: data-engineer
last-reviewed: 2026-11-26
stability: draft
---

# DB-04 Implementation Notes

## Status: review

## Files created

| File | Purpose |
|---|---|
| `db/migrations/0013_core_property_clusters.sql` | `core.property_clusters` table with idempotent unique index |
| `pipelines/normalize.py` | `normalize_address()`, `clean_owner()`, `blocking_key()` |
| `pipelines/dedupe.py` | Full pipeline: normalization, blocking, scoring, cluster formation |
| `tests/unit/db04/__init__.py` | Package marker |
| `tests/unit/db04/test_normalize.py` | 23 unit tests for normalize + clean_owner + blocking_key |
| `tests/unit/db04/test_blocker.py` | 6 unit tests for `build_blocks()` |
| `tests/unit/db04/test_matcher.py` | 21 unit tests for scoring, union-find, eval integration |
| `tests/fixtures/db04/sample_properties.json` | 20 synthetic property rows for unit tests |
| `tests/fixtures/db04/generate_pairs.py` | Generator script for `dedupe_pairs_200.csv` |
| `tests/fixtures/dedupe_pairs_200.csv` | 200 labeled pairs (100 TP + 70 TN + 30 partial) |
| `evals/__init__.py` | Package marker (required for mypy) |
| `evals/dedupe/__init__.py` | Package marker (required for mypy) |
| `evals/dedupe/run_eval.py` | Eval harness; writes `docs/work/DB-04/eval-results.txt` |
| `docs/work/DB-04/eval-results.txt` | Precision/recall evidence written by `run_eval.py` |

## Files modified

| File | Change |
|---|---|
| `pyproject.toml` | Added `rapidfuzz>=3.9`, `usaddress>=0.5.10`; added `usaddress` mypy override |
| `Makefile` | Added `dedupe` and `eval` targets; added `SUITE` variable; added suite filter to `test` target |

## Deviations from design.md

1. **`blocking_key()` function placement:** design.md says to put `blocking_key()` in
   `pipelines/normalize.py` (or a sibling `dedupe_logic.py`). It is in `normalize.py`
   as a third public function alongside `normalize_address()` and `clean_owner()`. This
   matches the design's intent and keeps pure functions together.

2. **`score_pair()` exposed from `dedupe.py`:** design.md describes `score_pair()` living
   in `pipelines/normalize.py` or a sibling module. It lives in `pipelines/dedupe.py`
   because it imports from `pipelines/normalize.py` (clean_owner) and belongs with the
   orchestration logic. The eval imports it directly from `pipelines.dedupe`.

3. **`matched_on` for singletons:** singletons have no pairs; the design does not specify
   `matched_on` for them. Set to `'address'` as the most conservative choice; the CHECK
   constraint permits it.

4. **`evals/__init__.py` and `evals/dedupe/__init__.py` added:** mypy --strict emits a
   "source file found twice" error for files inside a directory not marked as a package.
   Adding `__init__.py` resolves this without changing any behavior.

5. **`tests/unit/db04/test_dedupe.py` naming:** the design specifies a single
   `tests/unit/test_dedupe.py`. Implementation uses three focused modules inside
   `tests/unit/db04/` matching the three-module structure described in the design's
   "Testing approach" section. All tests are discovered by pytest automatically.

## Library versions installed

| Package | Requested | Installed |
|---|---|---|
| rapidfuzz | >=3.9 | 3.14.6 |
| usaddress | >=0.5.10 | 0.5.16 |

## Commands run and output

### make lint (all three linters)
```
uv run ruff check .          → All checks passed!
uv run ruff format --check . → 30 files already formatted
uv run mypy --strict .       → Success: no issues found in 21 source files
```

### make test (without docker — unit only)
```
uv run pytest tests/unit/ -q
60 passed in 0.21s
```

New tests added: 50 (in tests/unit/db04/). Pre-existing: 10.

### eval precision/recall
```
uv run python evals/dedupe/run_eval.py
precision=0.9701  recall=1.0000  f1=0.9848
Results written to docs/work/DB-04/eval-results.txt
PASS: precision and recall >= 0.80
```

### fixture line count
```
wc -l tests/fixtures/dedupe_pairs_200.csv
201 tests/fixtures/dedupe_pairs_200.csv    (header + 200 rows)
```

## Known gaps

- `make dedupe` requires Docker (live Postgres). Not run here because no DB is available
  in the implementation environment. The migration SQL, pipeline logic, and idempotency
  guard are tested structurally via unit tests; the tester should verify AC-1, AC-2,
  AC-3, and AC-7 against a live stack.
- `make test SUITE=db04` relies on pytest `-k db04` filtering by test name. Because the
  test files are in `tests/unit/db04/`, running `uv run pytest tests/unit/ -k db04 -q`
  discovers them correctly. The Makefile passes `-k $(SUITE)` only when SUITE != all.
