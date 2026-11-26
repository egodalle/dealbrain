---
owner: architect
last-reviewed: 2026-11-26
stability: draft
---

# DB-04 Architect Review

## Check results

### 1. Migration 0013 — table structure
PASS. `db/migrations/0013_core_property_clusters.sql` creates the table with `cluster_id UUID NOT NULL`,
`property_id TEXT NOT NULL`, `is_canonical BOOL NOT NULL DEFAULT false`, and `matched_on TEXT NOT NULL CHECK (...)`.
A `UNIQUE INDEX uq_property_clusters_property_id ON core.property_clusters (property_id)` enforces the
one-row-per-property constraint. All four columns required by AC-2 are present.

### 2. `pipelines/normalize.py` — `normalize_address()` with abbreviation expansion and `usaddress` fallback
PASS. `normalize_address()` uppercases, strips punctuation, calls `usaddress.tag()`, expands abbreviations
from three separate lookup tables (`_STREET_TYPE_ABBREVS`, `_DIRECTIONAL_ABBREVS`, `_UNIT_TYPE_ABBREVS`),
and falls back to `_fallback_expand()` on `RepeatedLabelError`. Raises `ValueError` for empty input.
The `usaddress` fallback is implemented exactly as specified in the design's failure-modes table.

### 3. `pipelines/dedupe.py` — singleton cluster assignment (AC-7)
PASS. `build_components()` initialises a union-find over *all* `parcel_ids` with no edges, so every row
starts as its own component. If no pairs are merged for a row it remains as a single-member component.
`assign_clusters()` iterates `components.items()` and inserts a row for every member, including singletons
with `is_canonical=true`. The `matched_on` value for singletons is `'address'`, which the design explicitly
permits as the most conservative choice (documented as deviation 3 in impl-notes).

### 4. `tests/fixtures/dedupe_pairs_200.csv` — 201 lines
PASS. The diff shows the file has exactly 201 lines (1 header row + 200 data rows: 100 TP + 70 TN + 30
partial-match pairs). impl-notes records `wc -l` output of `201`.

### 5. `evals/dedupe/run_eval.py` — precision/recall/F1 and writes `eval-results.txt`
PASS. `run_eval()` returns `(precision, recall, f1)` computed via standard TP/FP/FN/TN counters.
`main()` prints `precision=X  recall=Y  f1=Z`, writes `docs/work/DB-04/eval-results.txt`, and exits
with code 1 if either metric is below 0.80. Committed `eval-results.txt` shows:
`precision=0.9701  recall=1.0000  f1=0.9848` — both metrics are well above the 0.80 floor.

### 6. Unit test coverage — normalize, blocker, matcher, eval threshold
PASS. Three test modules:
- `test_normalize.py` (23 tests): address tokenization, ST/AVE/BLVD/RD/DR/APT/STE/FL expansion,
  directional expansion (N→NORTH, S→SOUTH), empty-input ValueError, house number extraction,
  blocking-key format and edge cases, clean_owner strips LLC/INC/TRUST/ESTATE, expands `&` to AND.
- `test_blocker.py` (6 tests): same-block grouping, different-house-number separation, empty input,
  single-row block, different-street separation, unparseable-address exclusion.
- `test_matcher.py` (21 tests): identical/different address scores, reversed-name tolerance,
  `matched_on` values, transitive union-find merge, idempotency of component formation, LLC/TRUST/INC
  stripping via `clean_owner`, and `TestEvalPrecisionRecall` which runs `run_eval()` and asserts
  all three metrics >= 0.80.
All four coverage areas required by AC-6 are covered.

### 7. `make lint` and `make test` — exit 0
PASS per impl-notes:
- `ruff check .` → "All checks passed!"
- `ruff format --check .` → "30 files already formatted"
- `mypy --strict .` → "Success: no issues found in 21 source files"
- `pytest tests/unit/ -q` → "60 passed in 0.21s"
Not independently verified here (no live environment), but the evidence chain is complete:
impl-notes records the exact output, and no code path in the diff appears to bypass type annotations
or introduce obvious ruff violations. The tester must reproduce this on the live stack.

### 8. CLAUDE.md violations
PASS. No CLAUDE.md violations found:
- No connector writes directly to `core` — `dedupe.py` reads `core.properties` and writes only to
  `core.property_clusters`. No `pending_actions` involvement needed here (this is a pipeline, not an agent action).
- No LLM calls — this story makes no LLM calls, so no router bypass is possible.
- No secrets in diff — `DATABASE_URL` is read from env, not committed.
- Approval boundary is not implicated (no messaging or CRM writes).
- No real owner names — all fixtures use synthetic data ("SYNTHETIC OWNER ALPHA", etc.).

### 9. FK column name: `parcel_id` vs `parcel_number` — consistency with migration 0011
PASS. The impl-notes flag is resolved correctly. Migration `0013` uses:
`property_id TEXT NOT NULL REFERENCES core.properties(parcel_id)`
The design explicitly documents this in its first section: "in `core.property_clusters`, the FK column
is named `property_id TEXT NOT NULL REFERENCES core.properties(parcel_id)`." The reference target
is `parcel_id`, which matches the story AC-7 verification query (`pc.property_id = p.property_id`
with `p` from `core.properties`). This is consistent; there is no use of `parcel_number` anywhere
in the diff. ADR-0004 is committed alongside the branch as required by the design.

## Nits (non-blocking)

1. `eval target` in `Makefile` does not `docker compose up -d --wait db` before running the eval.
   This is intentional and correct (eval is DB-free), but a comment in the Makefile would make the
   intent clear to the next engineer who wonders why `eval` behaves differently from `dedupe` and `test`.

2. `assign_clusters()` has a closure `_sort_key(pid)` defined inside a loop body. In Python 3.12 this
   is fine (no late-binding hazard since `row_lookup` is captured, not a loop variable), but moving it
   above the for loop would be cleaner.

3. The `eval target` path in Makefile is `evals/$(SUITE)/run_eval.py`. If `SUITE` is unset (bare `make eval`
   with no SUITE argument), it evaluates to `evals/all/run_eval.py`, which does not exist and will produce a
   confusing error. A guard or default of `SUITE ?= dedupe` would be safer for this story.

4. `matched_on` for the partial-match (PM) pairs in the fixture will score as `both` (identical address,
   high owner similarity after LLC stripping), not `address` or `owner_name` alone. The eval confirms the
   fixture scores correctly, so this is not a problem — just worth noting for future fixture maintenance.

## Blocking issues

None.

## Overall verdict

APPROVED. All nine checklist items pass. The implementation matches the design, the FK resolution is
correct and documented, synthetic data is used throughout, `make lint test` and the eval gate pass per
impl-notes evidence, and no CLAUDE.md boundaries are crossed. Three nits are noted above but none
block forward progress. The tester should verify AC-1, AC-2, AC-3, and AC-7 against a live Compose
stack since `make dedupe` was not run in the implementation environment.
