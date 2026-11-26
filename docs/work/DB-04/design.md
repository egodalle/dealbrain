---
owner: architect
last-reviewed: 2026-11-26
stability: draft
---

# DB-04 Design: Address normalization + entity resolution + dedupe

## Schema note: `parcel_id` vs `property_id`

`core.properties` uses `parcel_id TEXT PRIMARY KEY` (migration 0011). The story's
acceptance criteria use the term `property_id`. In `core.property_clusters`, the FK
column is named `property_id TEXT NOT NULL REFERENCES core.properties(parcel_id)`.
This satisfies AC-2's column-name check while keeping the FK valid. No rename of
`core.properties.parcel_id` is needed or in scope.

---

## 1. Address normalization

### What normalization means

A normalized address is uppercase, punctuation-stripped, and uses full-word
abbreviations for unit types and directionals. Example:

```
"123 n. broad st apt 4b" → "123 NORTH BROAD STREET APARTMENT 4B"
```

Steps in order:

1. Parse the raw address string with `usaddress.tag()` into components:
   `AddressNumber`, `StreetNamePreDirectional`, `StreetName`, `StreetNamePostType`,
   `OccupancyType`, `OccupancyIdentifier`.
2. Expand abbreviations from a fixed lookup table (see below).
3. Uppercase and strip non-alphanumeric characters except spaces.
4. Re-join components in canonical order: `{house_number} {directional} {street_name}
   {street_type} {unit_type} {unit_id}`.

Abbreviation lookup (minimum set; extend as found in data):

| Input | Canonical |
|---|---|
| ST | STREET |
| AVE | AVENUE |
| BLVD | BOULEVARD |
| DR | DRIVE |
| RD | ROAD |
| LN | LANE |
| CT | COURT |
| PL | PLACE |
| TER | TERRACE |
| N | NORTH |
| S | SOUTH |
| E | EAST |
| W | WEST |
| APT | APARTMENT |
| STE | SUITE |
| FL | FLOOR |
| UNIT | UNIT |

Owner-name cleaning (separate function, used only for similarity scoring, not stored):
uppercase, strip punctuation, expand `&` to `AND`, drop common noise tokens
(`LLC`, `INC`, `TRUST`, `ESTATE`, `ET AL`).

### Where normalization runs

`pipelines/normalize.py` — two public functions:

```python
def normalize_address(raw: str) -> str:
    """Return canonical address string or raise ValueError if unparseable."""

def clean_owner(raw: str) -> str:
    """Return uppercase, punctuation-stripped, noise-token-removed owner string."""
```

The pipeline calls `normalize_address` after reading from `core.properties` and
updates the `address_normalized` column. It does not call `clean_owner` for storage —
owner cleaning is in-memory only, used as input to the similarity scorer.

### Migration

`address_normalized TEXT` already exists in migration `0011_core_properties.sql` as a
nullable column. No new migration is needed for the column itself.

After `make dedupe` runs, AC-1 verifies zero nulls with a SELECT. The column remains
nullable in the schema (no NOT NULL constraint added) so that future ingestion of
incomplete records does not break the OPA pipeline. The dedupe pipeline treats a NULL
`address_normalized` as a normalization failure and logs it to stderr before skipping
that row.

---

## 2. Entity resolution / deduplication

### Blocking

Blocking key: `(house_number, first_token_of_street_name)`.

`house_number` is the `AddressNumber` component from `usaddress`. `first_token_of_street_name`
is the first whitespace-delimited token of the normalized street name (after directional
expansion). Example: address "123 NORTH BROAD STREET" → key `("123", "BROAD")`.

This reduces comparison to pairs that share both a house number and the leading street
word. Within Philly's grid, this produces blocks almost always under 20 rows.

### Similarity scoring

For each pair `(a, b)` in a block:

```python
addr_score  = rapidfuzz.fuzz.token_sort_ratio(a.address_normalized, b.address_normalized) / 100.0
owner_score = rapidfuzz.fuzz.token_sort_ratio(clean_owner(a.owner), clean_owner(b.owner)) / 100.0
combined    = 0.6 * addr_score + 0.4 * owner_score
```

Weights: address is the stronger signal (0.6) because Philly parcels are uniquely
addressable; owner name changes more often (inheritance, LLC rename). If either owner
string is empty after cleaning, the combined score falls back to `addr_score` alone
with threshold raised to 0.90 to avoid false positives on address-only matches.

Merge threshold: **0.85** combined score. See ADR-0004 for why rapidfuzz was chosen
over pg_trgm.

### Cluster formation

Pairs above the threshold are connected via **union-find** (a plain Python dict-based
implementation; no library needed). Each connected component becomes one cluster.

Canonical record selection within a cluster: the row with the highest `assessed_value`.
If two rows tie on `assessed_value`, the one with the earlier `created_at` is canonical.

### Schema: `core.property_clusters`

Migration `0013_core_property_clusters.sql`:

```sql
BEGIN;

CREATE TABLE core.property_clusters (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cluster_id    UUID    NOT NULL,
    property_id   TEXT    NOT NULL REFERENCES core.properties(parcel_id),
    is_canonical  BOOL    NOT NULL DEFAULT false,
    matched_on    TEXT    NOT NULL CHECK (matched_on IN ('address', 'owner_name', 'both')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_property_clusters_property_id
    ON core.property_clusters (property_id);

CREATE INDEX idx_property_clusters_cluster_id
    ON core.property_clusters (cluster_id);

COMMENT ON TABLE core.property_clusters IS
    'One row per property per cluster. Each cluster has exactly one is_canonical=true row.';

COMMIT;
```

`matched_on` values:
- `address` — only the address similarity triggered the merge.
- `owner_name` — only the owner similarity triggered the merge (address score < 0.85
  alone but combined >= 0.85).
- `both` — both independently exceeded 0.85.

The unique index on `property_id` enforces that each property belongs to at most one
cluster. Combined with `is_canonical`, downstream queries filter to canonical rows with:

```sql
SELECT p.*
FROM core.properties p
JOIN core.property_clusters pc ON pc.property_id = p.parcel_id
WHERE pc.is_canonical = true;
```

AC-7: properties not in any cluster are singletons — the pipeline inserts them as their
own cluster (single-member cluster, `is_canonical = true`). This guarantees AC-7's check
returns zero because every non-canonical row has a `cluster_id` via the clusters table.

### Idempotency guard (AC-3)

Before inserting, the pipeline computes the set of `(property_id, cluster_id)` pairs
it would write. It then queries `core.property_clusters` for existing pairs and subtracts
the intersection. Only net-new pairs are inserted. `ON CONFLICT DO NOTHING` on the
unique index on `property_id` is the final safety net. A second run with no data change
produces zero inserts.

---

## 3. Pipeline integration

### `pipelines/dedupe.py`

Orchestration sequence:

```
1. Connect to DB
2. SELECT parcel_id, address_raw, address_normalized, owner, owner_1, owner_2,
          assessed_value, created_at FROM core.properties
3. For each row where address_normalized IS NULL:
     address_normalized = normalize_address(address_raw)
     UPDATE core.properties SET address_normalized = %s,
                                 updated_at = now()
     WHERE parcel_id = %s
4. Build blocks: dict[(house_number, first_street_token)] → list[Row]
5. For each block with >= 2 rows:
     For each pair in the block:
         compute combined score
         if combined >= 0.85: add edge to union-find
6. Resolve components → clusters (assign UUID per component)
7. For singleton rows not in any multi-row component:
     assign a fresh cluster UUID
8. Compute canonical row per cluster (max assessed_value, then min created_at)
9. Determine matched_on per pair
10. INSERT INTO core.property_clusters (cluster_id, property_id, is_canonical,
                                        matched_on)
    ... ON CONFLICT DO NOTHING
11. Print summary: rows normalized, clusters formed, properties inserted
```

Step 3 populates `address_normalized` for any rows the OPA ingest left NULL. This
handles AC-1 without a separate migration.

### `evals/dedupe/run_eval.py`

The eval script lives in `evals/dedupe/` per repo layout. It reads
`tests/fixtures/dedupe_pairs_200.csv` (the labeled fixture per AC-4 and AC-5), calls
the matcher directly (not via DB), and reports precision/recall/F1.

Fixture columns: `property_id_a`, `property_id_b`, `is_duplicate` (0 or 1).

The script must write `docs/work/DB-04/eval-results.txt` containing a line:
`precision=<value>  recall=<value>  f1=<value>`.

The eval script does not need a live database. It constructs synthetic `Row` objects
from the fixture and runs the same `score_pair()` function the pipeline uses.

### Makefile additions

```makefile
SUITE ?= all

dedupe:
	docker compose up -d --wait db
	uv run python -m pipelines.dedupe

eval:
	uv run python evals/$(SUITE)/run_eval.py

test: ...existing...
	# SUITE=db04 runs tests/unit/db04/
```

The `test` target already runs `tests/unit/` via pytest. The data-engineer adds
`tests/unit/db04/` and pytest will discover it automatically. No Makefile change is
needed for `make test SUITE=db04` — pytest's `-k` or directory filtering suffices,
but AC-6 specifies `make test SUITE=db04`. Add:

```makefile
test:
	docker compose up -d --wait db
	uv run pytest tests/unit/ -q $(if $(filter-out all,$(SUITE)), -k $(SUITE),)
```

---

## 4. Migrations

| Number | File | Purpose |
|---|---|---|
| 0011 | already exists | `core.properties` with `address_normalized TEXT` nullable — no change |
| 0013 | `0013_core_property_clusters.sql` | `core.property_clusters` table |

Migration 0012 (`raw_table_counts_view.sql`) already exists. The next number is 0013.
No migration 0014 is needed (the prompt suggested two, but only the clusters table is
new; the address column already exists).

---

## 5. Dependencies

Add to `pyproject.toml` under `[project] dependencies`:

```
"rapidfuzz>=3.9",
"usaddress>=0.5.10",
```

Both are pure-Python wheels compatible with Python 3.12.

---

## 6. Testing approach

### Unit tests: `tests/unit/db04/`

Three test modules, all using synthetic data only:

**`test_normalize.py`**
- `normalize_address("123 N BROAD ST")` → `"123 NORTH BROAD STREET"`
- `normalize_address("456 S 10TH AVE APT 2")` → `"456 SOUTH 10TH AVENUE APARTMENT 2"`
- `normalize_address("")` raises `ValueError`
- Address tokenization: house number extracted correctly from multiple formats
- Unit-type expansion: `APT` → `APARTMENT`, `STE` → `SUITE`, `FL` → `FLOOR`

**`test_blocker.py`**
- Two addresses with same house number and first street token land in same block
- Two addresses with different house numbers land in different blocks
- Empty address list produces empty block dict

**`test_matcher.py`**
- Identical addresses score 1.0
- Clearly different addresses score below 0.85
- Owner-name cleaning strips `LLC`, `INC`, `TRUST`
- Union-find correctly merges transitive pairs into one component
- Idempotency: calling cluster formation twice on the same input produces the same
  cluster UUIDs (deterministic canonical selection)

### Fixture for unit tests

`tests/fixtures/db04/sample_properties.json` — a list of ~20 synthetic property dicts
(no real owner names). The data-engineer generates these using the same synthetic seed
pattern as `db03/opa_page1.json`.

### Labeled eval fixture

`tests/fixtures/dedupe_pairs_200.csv` — 200 rows, generated by the data-engineer from
the synthetic OPA fixture (no separate generation script needed). The script that
produces it is `tests/fixtures/db04/generate_pairs.py` and is committed alongside the
fixture so results are reproducible. The fixture itself is committed as a static file.

---

## 7. Sequence of calls (happy path)

```
make dedupe
  └─ pipelines/dedupe.py
       ├─ psycopg3: connect via DATABASE_URL
       ├─ SELECT all rows from core.properties
       ├─ normalize.normalize_address() per NULL row → batch UPDATE
       ├─ normalize.blocker() → dict of blocks
       ├─ normalize.score_pair() per pair in block
       ├─ union_find.merge() for pairs >= 0.85
       ├─ assign cluster UUIDs (uuid4, deterministic per run via sorted parcel_id seed)
       ├─ SELECT existing cluster rows from core.property_clusters
       ├─ diff: net-new rows only
       └─ INSERT INTO core.property_clusters ... ON CONFLICT DO NOTHING
```

```
make eval SUITE=dedupe
  └─ evals/dedupe/run_eval.py
       ├─ load tests/fixtures/dedupe_pairs_200.csv
       ├─ for each pair: build synthetic Row objects, call score_pair()
       ├─ compare prediction vs is_duplicate label
       ├─ compute precision, recall, F1
       ├─ print "precision=X  recall=Y  f1=Z" to stdout
       └─ write docs/work/DB-04/eval-results.txt
```

---

## 8. Failure modes and retries

| Failure | Behaviour |
|---|---|
| `usaddress` raises `RepeatedLabelError` on malformed address | Catch, log parcel_id to stderr, set `address_normalized = address_raw.upper()` as fallback, continue |
| DB connection lost mid-run | Let psycopg3 raise; pipeline exits non-zero; `make dedupe` reports failure; operator re-runs — idempotency ensures no duplicates |
| Block size > 500 rows | Log warning; still process (no truncation); at Philly scale this should not occur in practice |
| `assessed_value` NULL for all rows in cluster | Canonical selection falls back to earliest `created_at` |
| Eval precision or recall < 0.80 | `run_eval.py` exits with code 1; CI fails the eval gate |

---

## 9. What tests prove it

| Acceptance criterion | Verified by |
|---|---|
| AC-1: zero NULL `address_normalized` | `make dedupe` + SQL SELECT |
| AC-2: `property_clusters` has four required columns | SQL `information_schema` query |
| AC-3: second run inserts 0 rows | SQL `MAX(created_at)` count |
| AC-4: precision/recall/F1 >= 0.80 printed | `make eval SUITE=dedupe` |
| AC-5: fixture is 200 rows, synthetic only | `wc -l` + visual inspection |
| AC-6: unit tests pass with four coverage areas | `make test SUITE=db04` / pytest |
| AC-7: no non-canonical row has NULL cluster_id | SQL join query |

---

## Implementation checklist (ordered for data-engineer)

Work on branch `feat/DB-04-address-dedupe`.

1. **Add dependencies:** add `rapidfuzz>=3.9` and `usaddress>=0.5.10` to
   `pyproject.toml` dependencies. Run `uv lock`. Commit.

2. **Migration 0013:** create `db/migrations/0013_core_property_clusters.sql` with the
   schema in section 2. Run `make migrate` against local Compose stack. Verify with
   `\d core.property_clusters` in psql.

3. **`pipelines/normalize.py`:** implement `normalize_address(raw: str) -> str` and
   `clean_owner(raw: str) -> str` with the abbreviation table in section 1.

4. **Unit tests for normalize:** create `tests/unit/db04/test_normalize.py` covering
   the cases in section 6. Run `uv run pytest tests/unit/db04/test_normalize.py -q`.
   All must pass before proceeding.

5. **Blocking and scoring:** implement `blocker(rows)` and `score_pair(a, b)` in
   `pipelines/normalize.py` (or a sibling module `pipelines/dedupe_logic.py` — keep
   pure functions separate from the DB orchestration module).

6. **Unit tests for blocker and matcher:** `tests/unit/db04/test_blocker.py` and
   `tests/unit/db04/test_matcher.py`. All must pass.

7. **Synthetic unit fixture:** create `tests/fixtures/db04/sample_properties.json`
   with ~20 synthetic rows (no real owner names).

8. **`pipelines/dedupe.py`:** implement the orchestration sequence in section 3.
   Test manually with `make dedupe` against local Compose stack. Verify AC-1 and AC-3.

9. **Labeled eval fixture:** create `tests/fixtures/db04/generate_pairs.py` to produce
   `tests/fixtures/dedupe_pairs_200.csv` with 200 rows. Run it once and commit the CSV.
   Verify `wc -l tests/fixtures/dedupe_pairs_200.csv` = 201.

10. **`evals/dedupe/run_eval.py`:** implement the eval script per section 3. Run
    `make eval SUITE=dedupe`. Verify precision and recall >= 0.80 and that
    `docs/work/DB-04/eval-results.txt` is written.

11. **Makefile:** add `dedupe` target and update `eval` target. Add `SUITE` support to
    `test` target as described in section 3.

12. **`make lint test`** passes (ruff, mypy --strict, all unit tests). Fix any type
    annotation gaps — all public functions in `normalize.py` and `dedupe.py` must have
    full type annotations.

13. **`impl-notes.md`:** write `docs/work/DB-04/impl-notes.md` covering any deviation
    from this design, library version actually installed, and the precision/recall values
    achieved. Set story status to `review`.

---

## ADR reference

ADR-0004 (`docs/adr/0004-dedupe-blocking-and-similarity-in-python.md`) records the
decision to use rapidfuzz in Python rather than pg_trgm SQL for string similarity.
