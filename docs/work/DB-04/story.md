# DB-04: Address normalization + entity resolution + dedupe

**Status:** done · **Plan day:** 3 · **Posting lines covered:** Collect, transform, dedupe, score, deliver

## Story
As a **RE RESET engineer running the DealBrain deduplication pipeline**, I want every
property record address normalized to a canonical form and duplicate records clustered
by owner and address so that the distress scorer and GBrain work against a single
authoritative property per parcel rather than fragmented duplicates.

## Acceptance criteria

1. Running `make dedupe` completes without error. After it finishes,
   `SELECT COUNT(*) FROM core.properties WHERE address_normalized IS NULL;`
   returns 0. The column was left NULL by DB-03; this pipeline must populate it for
   every row.

2. A table `core.property_clusters` exists with at least the columns
   `cluster_id`, `property_id`, `is_canonical`, and `matched_on`
   (the signal that triggered the match: `address`, `owner_name`, or `both`).
   Verify with:
   `SELECT column_name FROM information_schema.columns WHERE table_schema = 'core' AND table_name = 'property_clusters';`
   — all four column names must appear in the result.

3. Running `make dedupe` a second time with no data change produces 0 new rows in
   `core.property_clusters`. Verify with:
   `SELECT COUNT(*) FROM core.property_clusters WHERE created_at = (SELECT MAX(created_at) FROM core.property_clusters);`
   — result must be 0 on the second run (the pipeline must be idempotent).

4. Precision and recall are measured against the labeled test fixture at
   `tests/fixtures/dedupe_pairs_200.csv` (200 labeled pairs, columns:
   `property_id_a`, `property_id_b`, `is_duplicate`).
   Running `make eval SUITE=dedupe` prints a report to stdout containing at least:
   `precision=<value>  recall=<value>  f1=<value>`
   Both precision and recall must be >= 0.80. The exact values must also be written to
   `docs/work/DB-04/eval-results.txt` for the tester to record as evidence.

5. The labeled fixture `tests/fixtures/dedupe_pairs_200.csv` contains exactly 200 rows
   (excluding the header) and uses only synthetic property records — no real owner names.
   Verify with:
   `wc -l tests/fixtures/dedupe_pairs_200.csv` — result must be 201 (header + 200 pairs).

6. `make test SUITE=db04` runs the unit tests for the normalization and blocking logic and
   all pass. Test output must show coverage of at least: address tokenization, unit-type
   abbreviation expansion (e.g., `APT` → `APARTMENT`), owner-name cleaning, and the
   idempotency guard on `property_clusters`.

7. `core.properties.property_id` for every non-canonical cluster member carries the
   `cluster_id` of its canonical record so that downstream queries can filter to
   canonical rows with a single `WHERE is_canonical = true` join.
   Verify with:
   `SELECT COUNT(*) FROM core.property_clusters pc JOIN core.properties p ON pc.property_id = p.property_id WHERE pc.is_canonical = false AND pc.cluster_id IS NULL;`
   — result must be 0.

## Demo line
Run `make dedupe` live: terminal shows 0 null addresses remaining and prints the
precision/recall table; then open the portal and show two previously fragmented records
merged under one cluster with the canonical flag highlighted.

## Out of scope
- Distress scoring (DB-05)
- Cross-city or cross-dataset entity resolution (Philly only)
- Probabilistic matching models (ML-based); rule-based blocking + string similarity is sufficient
- Any CRM or outbound action
- Geocoding or lat/lon enrichment

## Open questions for Architect
- What string-similarity library should the data-engineer use for address and owner-name
  matching — `rapidfuzz`, `jellyfish`, or a Postgres `pg_trgm` index? The choice affects
  whether blocking runs in Python or pure SQL. Decide before implementation starts.
- Should `core.property_clusters` live in the `core` schema or a separate `dedupe` schema?
  Downstream stories (DB-05, DB-08) will join against it; prefer `core` unless there is a
  strong isolation reason.
- DB-03 left `address_normalized` as a nullable `text` column. Confirm the column already
  exists in the migration before the data-engineer adds a NOT NULL constraint — or should
  the constraint be deferred until after this pipeline populates it?
- The labeled fixture must use synthetic data only. Should the data-engineer generate it
  from the existing synthetic OPA fixture (seeded in DB-03), or is a separate generation
  script needed?
