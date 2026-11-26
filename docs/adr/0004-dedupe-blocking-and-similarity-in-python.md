---
owner: architect
last-reviewed: 2026-11-26
stability: stable
---

# ADR-0004: Dedupe blocking and string similarity run in Python, not SQL

## Context

DB-04 must cluster duplicate property records by address and owner name. Two
implementation paths exist:

**Option A — Python blocking + rapidfuzz:** Pull candidate pairs into Python using a
blocking key (house number + first street token), then score each pair with
`rapidfuzz.fuzz.token_sort_ratio`. Write matched clusters back to Postgres.

**Option B — Pure SQL with pg_trgm:** Create GIN trigram indexes on
`address_normalized` and `owner`. Use `pg_trgm.similarity()` in a self-join to find
pairs above a threshold. No Python needed for the matching step.

### Comparison

| Dimension | Python + rapidfuzz | pg_trgm SQL self-join |
|---|---|---|
| Pair explosion without blocking | O(N²) | O(N²) unless manually blocked |
| Blocking control | Explicit in code, easy to test | Requires WHERE clause engineering; harder to verify |
| Precision-recall tuning | Adjust threshold constant in one place | Adjust index parameter `pg_trgm.similarity_threshold` globally |
| Testability | Pure functions, no DB needed for unit tests | Must spin up Postgres to unit-test |
| Owner-name normalization | Full Python string pipeline before comparison | Would require a SQL function or computed column |
| Incremental cost | Scales with block size, not full table | Full GIN scan per run unless carefully indexed |
| Library stability | rapidfuzz 3.x; well-maintained; MIT | pg_trgm is core Postgres, always available |

The blocking key — (house_number, first_token_of_street_name) — is straightforward to
extract in Python after normalization. Without blocking, a pg_trgm self-join on 580k
rows produces up to 336 billion pair evaluations; in practice the GIN index prunes most,
but Postgres must still plan and execute the join, and there is no idiomatic way to
inject a blocking step into the query plan.

The eval harness (AC-4) requires calling the matcher from Python with a labeled CSV.
If matching lives in SQL, the eval must either replicate the SQL logic in Python or
hit a live database. Both are fragile. With Python matching, the eval calls the same
function the pipeline calls.

## Decision

Blocking and string similarity run in Python using `rapidfuzz`. Postgres is used for
storage only during the dedupe step. The pipeline:

1. Reads normalized rows from `core.properties` into Python.
2. Builds blocks keyed on `(house_number, first_street_token)`.
3. Within each block, scores every pair with
   `rapidfuzz.fuzz.token_sort_ratio(addr_a, addr_b)` and
   `rapidfuzz.fuzz.token_sort_ratio(owner_a, owner_b)`.
4. Merges pairs where the combined score exceeds 0.85 using union-find.
5. Writes clusters back to `core.property_clusters` via a single bulk INSERT with
   `ON CONFLICT DO NOTHING` for idempotency.

The `usaddress` library parses raw addresses into components (house number, street
name, unit type, etc.) before normalization, which is the input to both the
blocking key and the similarity score.

`pg_trgm` remains installed (it was enabled in DB-03 for future full-text search on
`core.properties`). It is not used for dedupe matching in this story.

## Consequences

- Two new runtime dependencies: `rapidfuzz` and `usaddress`. Both are pure Python
  wheels; no C extension compilation beyond what rapidfuzz's optional speedup provides.
  Both are added to `pyproject.toml`.
- The dedupe pipeline is a Python process (`pipelines/dedupe.py`), not a SQL procedure.
  It can be called from `make dedupe` and from supercronic without a psql dependency.
- Unit tests for `normalize()`, `blocker()`, and `matcher()` run without a database.
  This satisfies the CI constraint that unit tests must run against a pgvector container
  but do not need real data loaded.
- If the parcel count grows beyond ~2M rows, block sizes may become large enough that
  Python memory becomes a concern. At that point, pre-filtering blocks by count before
  loading is the first mitigation. This is out of scope for the current story (Philly
  OPA is ~580k parcels, block sizes are typically under 50 rows).

## Alternatives rejected

- **pg_trgm SQL self-join:** Cannot easily incorporate blocking; eval harness would
  need a live DB; normalization pipeline harder to test in isolation. Rejected.
- **jellyfish:** Lacks token-aware comparison (Jaro-Winkler is character-level, which
  is weak for multi-word addresses like "123 N BROAD ST"). `rapidfuzz.token_sort_ratio`
  handles word-order variation better. Rejected.
- **Dedicate schema `dedupe`:** `core.property_clusters` is read by DB-05 (distress
  scorer) and DB-08 (GBrain). Putting it in a separate schema adds a schema grant to
  every downstream consumer. The `core` schema is already the authoritative layer for
  downstream reads. Rejected.
