---
owner: architect
last-reviewed: 2026-11-26
stability: draft
---

# DB-05 Design: Explainable distress score + `/leads` data product with CSV export

## Schema clarification: `parcel_id` vs `parcel_number`

Before anything else, pin down the naming:

- `core.properties.parcel_id` is the `TEXT PRIMARY KEY` (migration 0011). This is the
  join key used everywhere in the codebase, including the FK in `core.property_clusters`
  (`property_id TEXT NOT NULL REFERENCES core.properties(parcel_id)`).
- `core.properties.parcel_number` is a separate nullable `TEXT` column — a human-readable
  OPA parcel identifier that may differ from `parcel_id`. It is not a PK, not indexed, and
  not used as a join key anywhere.

The story's acceptance criteria use `parcel_number` in the `/leads` response shape and CSV
header. This is the human-readable OPA identifier the acquisitions rep knows, not the
internal surrogate PK. Both columns exist; both must appear in the output. The scoring
pipeline uses `parcel_id` internally for all joins. The portal and CSV surface
`parcel_number` for display.

---

## 1. Score model

### Factors and weights

The distress score is a deterministic weighted sum (0–100). Weights are defined as
named constants in `pipelines/score.py` and asserted to sum to 100 at import time (see
ADR-0005).

| Factor | Weight | Source | Zero case |
|---|---|---|---|
| `delinquency` | 35 | `staging.delinquency.num_years_owed` where `parcel_id` matches | 0 if no row in delinquency |
| `violations` | 25 | COUNT of open `staging.violations` rows where `parcel_id` matches and `case_status != 'CLOSED'` | 0 if no open violations |
| `years_held` | 20 | `EXTRACT(YEAR FROM now()) - EXTRACT(YEAR FROM core.properties.sale_date)` | 0 if `sale_date` is NULL |
| `value_gap` | 20 | `(zip_median_assessed - p.assessed_value) / NULLIF(zip_median_assessed, 0)` capped at 1.0, negated for below-median properties | 0 if assessed_value is NULL or zip has fewer than 3 properties |

### Component calculation in detail

**`delinquency` component (max raw signal = 10+ years):**

```
raw = COALESCE(d.num_years_owed, 0)
component = MIN(raw / 10.0, 1.0) * 35
```

One year of delinquency → 3.5 points. Ten or more years → 35 points (cap).

**`violations` component (max raw signal = 5+ open violations):**

```
raw = COUNT of open violations for this parcel_id
component = MIN(raw / 5.0, 1.0) * 25
```

One open violation → 5 points. Five or more → 25 points (cap).

**`years_held` component (max raw signal = 20+ years without a sale):**

```
raw = EXTRACT(YEAR FROM now()) - EXTRACT(YEAR FROM sale_date)   -- 0 if NULL
component = MIN(MAX(raw, 0) / 20.0, 1.0) * 20
```

A property sold this year → 0 points. Not sold in 20+ years → 20 points.

**`value_gap` component (below-median assessed value is a distress signal):**

```
zip_median = median(assessed_value) for all properties sharing zip_code
             (minimum 3 properties; else 0)
gap_ratio  = (zip_median - assessed_value) / zip_median   -- positive = below median
             clamped to [0.0, 1.0]
component  = gap_ratio * 20
```

An assessed value at the median or above → 0 points. Far below median → up to 20 points.

### Sum and rounding

```
raw_total = delinquency + violations + years_held + value_gap   # float
distress_score = ROUND(raw_total)                               # int, stored as SMALLINT
```

Each component is a float before summing. The sum is rounded to an integer once. The
components stored in `score_components` are the **rounded integer portions** that sum
exactly to `distress_score`:

```
score_components = {
    "delinquency": round(delinquency_component),
    "violations":  round(violations_component),
    "years_held":  round(years_held_component),
    "value_gap":   round(value_gap_component),
}
```

The rounding rule: assign `floor()` to each component, then distribute any remainder
(0–3 points) to the highest-floating components. This guarantees
`sum(score_components.values()) == distress_score` exactly, satisfying AC-2. See
`score_property()` implementation note below.

Values are stored as JSON integers, not strings, satisfying the safer cast requirement
raised in the story's open questions. The AC-2 invariant query casts via `::numeric`
which works for both JSON integers and floats without error.

---

## 2. Schema changes — migration `0014_core_properties_score.sql`

```sql
BEGIN;

ALTER TABLE core.properties
    ADD COLUMN distress_score   SMALLINT,
    ADD COLUMN score_components JSONB;

COMMENT ON COLUMN core.properties.distress_score IS
    'Weighted distress score 0–100. NULL until score pipeline has run for this row.';

COMMENT ON COLUMN core.properties.score_components IS
    'Integer sub-scores by factor. Keys: delinquency, violations, years_held, value_gap.
     Values are integers that sum exactly to distress_score.';

CREATE INDEX idx_properties_distress_score
    ON core.properties (distress_score DESC NULLS LAST);

COMMIT;
```

Why `SMALLINT` and not `INTEGER`: the story acceptance criteria say `INTEGER`; the
instruction prompt says `SMALLINT`. The story's AC-1 SQL check only tests `column_name`
and `data_type`; `smallint` satisfies both. Using `SMALLINT` saves 2 bytes per row and
signals range 0–100 in the schema. No behavioral difference. If the tester's SQL check
against `information_schema` requires `data_type = 'integer'`, the data-engineer can
change to `INTEGER` without touching anything else — the design is not load-bearing on
this choice.

No change to `0011_core_properties.sql`. Patching an already-applied migration would
break any environment that has run it; a new file is the correct approach.

---

## 3. Scoring pipeline — `pipelines/score.py`

### Public interface

```python
WEIGHT_DELINQUENCY = 35
WEIGHT_VIOLATIONS  = 25
WEIGHT_YEARS_HELD  = 20
WEIGHT_VALUE_GAP   = 20
assert WEIGHT_DELINQUENCY + WEIGHT_VIOLATIONS + WEIGHT_YEARS_HELD + WEIGHT_VALUE_GAP == 100

def score_property(parcel_id: str, conn: psycopg.Connection[Any]) -> tuple[int, dict[str, int]]:
    """Compute (distress_score, score_components) for one property.

    Reads staging.delinquency, staging.violations, core.properties.
    Does not write. Raises ValueError if parcel_id not found in core.properties.
    Returns (score, components) where sum(components.values()) == score.
    """

def run(conn: psycopg.Connection[Any]) -> None:
    """Score all canonical properties. Idempotent: skips rows where inputs are unchanged.

    Canonical = is_canonical=true in core.property_clusters.
    Idempotency guard: before updating a row, computes a stable input hash from the
    source values used in scoring (num_years_owed, violation_count, sale_date,
    assessed_value, zip_code). Skips the UPDATE if the hash matches the value stored
    in score_components["_input_hash"]. This satisfies AC-4.
    """
```

### Input hash for idempotency

The idempotency guard uses a stable string hash:

```python
import hashlib, json

def _input_hash(
    num_years_owed: int,
    violation_count: int,
    sale_date: str | None,
    assessed_value: float | None,
    zip_code: str | None,
) -> str:
    payload = json.dumps([num_years_owed, violation_count, sale_date,
                          str(assessed_value), zip_code], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
```

Stored in `score_components["_input_hash"]`. The sum-invariant SQL in AC-2 uses
`jsonb_each_text` and sums all keys. To prevent `_input_hash` from breaking the sum:

```sql
-- AC-2 invariant query (what the tester runs):
SELECT COUNT(*)
FROM core.properties
WHERE distress_score IS NOT NULL
  AND distress_score <> (
    SELECT COALESCE(SUM(value::numeric), 0)
    FROM jsonb_each_text(score_components)
    WHERE key != '_input_hash'          -- exclude the hash key
  );
```

The story's AC-2 query does not include this `WHERE key != '_input_hash'` clause. The
data-engineer must note this discrepancy in `impl-notes.md`. **Alternative:** store
`_input_hash` in a separate column `score_input_hash TEXT` on `core.properties` to keep
`score_components` clean. This avoids touching the AC-2 query at all. Preferred.

**Revised schema (migration addendum):**

```sql
ALTER TABLE core.properties
    ADD COLUMN score_input_hash TEXT;
```

Add this to `0014_core_properties_score.sql` before the `COMMIT`. Now `score_components`
contains only the four integer factors and the AC-2 query works exactly as written.

### Zip-median computation

`run()` computes zip medians once before the per-property loop:

```python
# SELECT zip_code, percentile_cont(0.5) WITHIN GROUP (ORDER BY assessed_value)
#   FROM core.properties
#   WHERE assessed_value IS NOT NULL
#   GROUP BY zip_code
#   HAVING COUNT(*) >= 3
zip_medians: dict[str, float] = { ... }  # built once, passed to score_property
```

`score_property` accepts `zip_medians` as a parameter so it can be tested without DB
access.

### Revised interface after the above changes

```python
def score_property(
    parcel_id: str,
    conn: psycopg.Connection[Any],
    zip_medians: dict[str, float],
) -> tuple[int, dict[str, int]]:
    ...

def run(conn: psycopg.Connection[Any]) -> None:
    ...  # computes zip_medians, iterates canonical properties, calls score_property,
         # checks score_input_hash, issues UPDATE only if hash changed or NULL
```

### Sequence of calls (happy path)

```
make score
  └─ pipelines/score.py run()
       ├─ psycopg3: connect via DATABASE_URL
       ├─ SELECT zip_code, percentile_cont(0.5) → zip_medians dict
       ├─ SELECT p.parcel_id, p.parcel_number, p.assessed_value, p.zip_code,
       │         p.sale_date, p.score_input_hash
       │    FROM core.properties p
       │    JOIN core.property_clusters pc ON pc.property_id = p.parcel_id
       │    WHERE pc.is_canonical = true
       ├─ for each row:
       │    SELECT total_due, num_years_owed FROM staging.delinquency
       │      WHERE parcel_id = %s  (single row or NULL)
       │    SELECT COUNT(*) FROM staging.violations
       │      WHERE parcel_id = %s AND case_status != 'CLOSED'
       │    compute input_hash
       │    if row.score_input_hash == input_hash: continue  (idempotency skip)
       │    score, components = score_property(parcel_id, conn, zip_medians)
       │    UPDATE core.properties
       │      SET distress_score = %s,
       │          score_components = %s::jsonb,
       │          score_input_hash = %s,
       │          updated_at = now()
       │      WHERE parcel_id = %s
       └─ print "scored N, skipped M (unchanged)"
```

### Failure modes

| Failure | Behaviour |
|---|---|
| `parcel_id` not in `core.property_clusters` | Only canonical rows are queried; this cannot occur in `run()`. `score_property()` raises `ValueError` if called directly on a non-existent parcel. |
| `sale_date` NULL | `years_held` component = 0; not an error. |
| `assessed_value` NULL | `value_gap` component = 0; not an error. |
| Zip has fewer than 3 assessed properties | Median = None; `value_gap` component = 0. |
| DB connection lost mid-run | psycopg3 raises; pipeline exits non-zero; operator re-runs. Already-updated rows have their new `score_input_hash` and are skipped on retry. |
| Rounding distributes points incorrectly | Covered by `test_score_components_sum` — the allocation algorithm is tested with many inputs before ship. |

---

## 4. Portal `/leads` endpoint

Extend `apps/portal/main.py`. The portal has no DB connection setup yet; the data-engineer
adds a module-level connection obtained from `DATABASE_URL` env var, following the same
psycopg3 pattern used in `pipelines/`.

### Dependency

`psycopg[binary]` is already in `pyproject.toml` production dependencies. The portal's
`apps/portal/requirements.txt` needs `psycopg[binary]` added (currently only fastapi +
uvicorn).

### `GET /leads`

```
GET /leads?limit=50&min_score=0
```

Query:

```sql
SELECT
    p.parcel_number,
    p.address_normalized,
    p.distress_score,
    p.score_components,
    COALESCE(p.owner_1, p.owner) AS owner
FROM core.properties p
JOIN core.property_clusters pc ON pc.property_id = p.parcel_id
WHERE pc.is_canonical = true
  AND p.distress_score IS NOT NULL
  AND p.distress_score >= %(min_score)s
ORDER BY p.distress_score DESC
LIMIT %(limit)s;
```

Response: `application/json`, array of objects:

```json
[
  {
    "parcel_number": "...",
    "address_normalized": "...",
    "distress_score": 78,
    "score_components": {"delinquency": 35, "violations": 20, "years_held": 15, "value_gap": 8},
    "owner": "..."
  }
]
```

`parcel_number` may be NULL if the OPA record lacked it. The endpoint does not filter
on NULL `parcel_number`; that is a data quality concern separate from scoring.

### `GET /leads/export.csv`

```
GET /leads/export.csv
```

Same query with no LIMIT. Response: `text/csv; charset=utf-8` with
`Content-Disposition: attachment; filename="leads.csv"`.

Column order: `parcel_number,address_normalized,distress_score,factor_1,factor_2,factor_3`.

`factor_1`, `factor_2`, `factor_3` are the keys of the three highest-value entries in
`score_components`, sorted descending by value. Ties broken alphabetically.

The `make export-leads` target writes to `exports/leads.csv` by calling the endpoint and
redirecting (`curl -s ... > exports/leads.csv`). The `exports/` directory is created by
the target if it does not exist.

### FastAPI function signatures

```python
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse

@app.get("/leads")
async def get_leads(
    limit: int = Query(default=50, ge=1, le=500),
    min_score: int = Query(default=0, ge=0, le=100),
) -> list[dict[str, Any]]:
    ...

@app.get("/leads/export.csv")
async def export_leads_csv() -> StreamingResponse:
    ...
```

---

## 5. Dependencies

No new packages. All required libraries are already present:

| Library | Use | Already in |
|---|---|---|
| `psycopg[binary]` | DB access in score pipeline and portal | `pyproject.toml` production deps |
| `fastapi` | Portal endpoints | `apps/portal/requirements.txt` |
| `hashlib`, `json` | Input hash | stdlib |
| `csv` | CSV generation | stdlib |

The portal's `requirements.txt` needs `psycopg[binary]>=3.3.9` added — it currently only
lists fastapi and uvicorn.

---

## 6. Makefile targets

```makefile
score:
	docker compose up -d --wait db
	uv run python -m pipelines.score

export-leads:
	mkdir -p exports
	curl -sf "http://localhost:8000/leads/export.csv" -o exports/leads.csv
	@echo "Written to exports/leads.csv"
	@wc -l exports/leads.csv
```

Add both to `.PHONY`. Add `score` and `export-leads` to the `.PHONY` line.

The portal must be running for `export-leads` to work. The target does not start it
automatically — the operator runs `make up` first. This matches existing patterns (`make
ingest` also requires the stack to be up).

---

## 7. Testing — `tests/unit/db05/`

All tests use synthetic data. No live database required.

### `test_score_components.py`

**`test_score_components_sum`** — given mock inputs for all four factors (at least five
distinct combinations covering edge cases: all zeros, all maxed, mixed), assert
`sum(components.values()) == score` for every combination.

**`test_score_range`** — fuzz 50 random input combinations (num_years_owed in [0,20],
violation_count in [0,10], sale_date ranging from 10 days ago to 40 years ago,
assessed_value from $1 to $500 000, zip_median from $50 000 to $300 000). Assert
`0 <= score <= 100` for every case.

**`test_top_factors`** — given `{"delinquency": 30, "violations": 15, "years_held": 10,
"value_gap": 8}`, assert the top-3 extraction returns `["delinquency", "violations",
"years_held"]` in order.

**`test_top_factors_ties`** — given two components with equal value, assert tie-breaking
is alphabetical and deterministic.

### `test_leads_endpoint.py`

**`test_leads_endpoint`** — use `fastapi.testclient.TestClient`. Patch the DB connection
at the module level with a mock that returns two synthetic property rows. Call
`GET /leads?limit=2`. Assert: status 200, response is a list of length 2, each item has
keys `parcel_number`, `address_normalized`, `distress_score`, `score_components`, `owner`.

**`test_leads_min_score_filter`** — mock returns one row with score 80 and one with score
40. Call `GET /leads?min_score=50`. Assert only one row returned.

**`test_csv_export`** — call `GET /leads/export.csv` with same mock. Assert:
- `Content-Type` header contains `text/csv`
- First line of body is exactly
  `parcel_number,address_normalized,distress_score,factor_1,factor_2,factor_3`
- Second line contains the expected values for the highest-scored mock row

### Test isolation note

`score_property()` is a pure function given `zip_medians` as a parameter — it can be
tested without any DB mock. The `run()` function requires a DB mock (psycopg3 connection).
Tests of `score_property` should not use `unittest.mock`; pass synthetic inputs directly.

---

## 8. What tests prove it (AC mapping)

| Acceptance criterion | Verified by |
|---|---|
| AC-1: both columns in `information_schema` | `make migrate` + SQL check |
| AC-2: sum invariant on all scored rows | SQL query (zero rows must differ) |
| AC-3: `score_components` has at least 3 keys | SQL query (zero rows with < 3 keys) |
| AC-4: `make score` is idempotent | SQL check for `updated_at > now() - interval '5 seconds'` after second run |
| AC-5: `/leads?limit=5` returns 5 canonical objects | `curl` + `python -m json.tool` |
| AC-6: `exports/leads.csv` has correct header and >= 2 lines | `head -1` + `wc -l` |
| AC-7: `make test SUITE=db05` all green | pytest output |

---

## Implementation checklist (ordered for data-engineer)

Work on branch `feat/DB-05-distress-score`.

1. **Migration 0014:** create `db/migrations/0014_core_properties_score.sql` with
   `distress_score SMALLINT`, `score_components JSONB`, `score_input_hash TEXT`, and
   the descending index. Run `make migrate`. Verify with `\d core.properties` in psql —
   all three columns must appear.

2. **`pipelines/score.py`:** implement `WEIGHT_*` constants with module-level assertion,
   `score_property(parcel_id, conn, zip_medians)`, and `run(conn)`. Follow the sequence
   in section 3. Keep `_input_hash()` as a private module-level function.

3. **Unit tests `tests/unit/db05/test_score_components.py`:** implement
   `test_score_components_sum`, `test_score_range`, `test_top_factors`,
   `test_top_factors_ties`. Run `uv run pytest tests/unit/db05/ -q`. All must pass before
   proceeding.

4. **Makefile `score` target:** add to `Makefile` and `.PHONY`. Test with `make score`
   against local Compose stack. Verify AC-2 and AC-4 SQL queries return 0.

5. **Portal DB connection:** add psycopg3 connection setup to `apps/portal/main.py` using
   `DATABASE_URL` env var. Add `psycopg[binary]>=3.3.9` to `apps/portal/requirements.txt`.

6. **Portal `GET /leads` and `GET /leads/export.csv`:** implement per section 4. Test
   manually with `make up` and `curl`.

7. **Unit tests `tests/unit/db05/test_leads_endpoint.py`:** implement
   `test_leads_endpoint`, `test_leads_min_score_filter`, `test_csv_export` using
   TestClient and DB mock. Run `uv run pytest tests/unit/db05/ -q`. All must pass.

8. **Makefile `export-leads` target:** add target and `.PHONY` entry. Run
   `make export-leads` and verify `exports/leads.csv` header and line count.

9. **`make lint test`** passes (ruff, mypy --strict on pipelines/, all unit tests).
   Note: `apps/portal/` is excluded from mypy strict per `pyproject.toml` — no change
   needed there.

10. **`impl-notes.md`:** write `docs/work/DB-05/impl-notes.md` covering: actual
    `distress_score` column type used, any deviation from rounding algorithm, precision
    of zip-median queries, and the `_input_hash` storage location decision. Set story
    status to `review`.

---

## ADR reference

ADR-0005 (`docs/adr/0005-scoring-weights-as-code-constants.md`) records the decision to
store scoring weights as code constants rather than a database table or config file.
