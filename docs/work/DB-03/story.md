# DB-03: Philly open-data ingestion (OPA, violations, transfers, delinquency)

**Status:** review · **Plan day:** 2 · **Posting lines covered:** Collect, transform, dedupe, score, deliver

## Story
As a **RE RESET engineer running the DealBrain ingestion pipeline**, I want Philly open-data
(OPA property assessments, L&I violations, deed transfers, and tax delinquency) loaded into
a three-layer schema (raw → staging → core) so that every downstream feature — scoring,
GBrain, the portal — has a clean, stable, non-duplicate property dataset.

## Acceptance criteria
1. Running `make ingest DATASET=philly` completes without error and the `raw` schema
   contains at least one populated table per dataset (opa_properties, li_violations,
   deed_transfers, tax_delinquency). Check with:
   `SELECT table_name, COUNT(*) FROM raw.table_counts GROUP BY 1;` (all counts > 0).

2. A second run of the same command (`make ingest DATASET=philly`) inserts 0 new rows
   into every raw table. Verify by querying the two most recent `ingest_log` rows ordered
   by `started_at` and confirming `rows_inserted = 0` for every dataset in the later run:
   `SELECT dataset, rows_inserted FROM raw.ingest_log WHERE started_at = (SELECT MAX(started_at) FROM raw.ingest_log) AND rows_inserted > 0;`
   — result must return 0 rows.

3. When exactly one OPA record in the fixture is changed (e.g., market_value updated by $1)
   and the pipeline is re-run, exactly 1 row is updated in `staging.opa_properties` and
   the previous version is preserved in `staging.opa_properties_history` (or equivalent
   audit mechanism). Verify with:
   `SELECT COUNT(*) FROM staging.opa_properties WHERE _updated_at = current_run_ts;`
   — result must be 1.

4. After the first ingest, `core.properties` contains at least 1000 rows and every row
   has a non-null `parcel_number`. Verify with:
   `SELECT COUNT(*) FROM core.properties;` — result must be >= 1000.
   `SELECT COUNT(*) FROM core.properties WHERE parcel_number IS NULL;` — result must be 0.

5. All four datasets join to `core.properties` via `parcel_id` with no foreign-key
   violations. Verify with:
   `SELECT COUNT(*) FROM staging.li_violations v LEFT JOIN core.properties p ON v.parcel_id = p.parcel_id WHERE p.parcel_id IS NULL;`
   — result must be 0 (same query pattern for the other three staging tables).

6. `make test SUITE=db03` runs the unit tests for the pipeline transforms and all pass.
   The test output must show no failures and cover at least: dedup logic, null-parcel-id
   rejection, and the idempotency assertion.

7. Running `make ingest DATASET=philly` a third time after no data change completes in
   under 90 seconds on the local Compose environment (timed by CI). The pipeline log line
   `"No new rows — skipped staging upsert"` must appear for all four datasets.

## Demo line
Show the terminal: first run loads N properties, second run logs "0 rows inserted" for
all four Philly datasets, then open the portal and see property counts match.

## Out of scope
- Address normalization / entity resolution (DB-04)
- Distress scoring (DB-05)
- Any dataset outside the four listed (permits, zoning, census)
- Pulling data from any source other than Philly open-data (city API or static CSV fixture)
- Outbound messages or CRM sync

## Open questions for Architect
- Should raw tables be append-only with an `ingested_at` timestamp, or should raw be
  overwritten per run? The idempotency test assumes append-only with dedup on ingest;
  confirm this is the intended pattern before the data-engineer starts.
- What is the canonical key for OPA records — `parcel_id` alone, or a composite? The
  dedup logic depends on this.
- Is the `_history` table the preferred audit pattern, or should staging use
  `updated_at` + a row-version column? The acceptance criteria in AC-3 reference a
  history table; align before implementation.
- Does the pipeline need to handle paginated API calls to the Philly open-data endpoint,
  or should Day-2 work use a static CSV fixture to keep the build deterministic?
