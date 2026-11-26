---
owner: architect
last-reviewed: 2026-11-26
stability: stable
---

# ADR-0003: Raw layer is append-only with content hash; staging uses SCD-2 for audit

## Context

DB-03 ingests four Philly open-data datasets into a three-layer schema. Two questions
from story.md must be answered before the data-engineer writes any code, because the
wrong choice here propagates into every downstream story (DB-04, DB-05, DB-08):

1. **Raw table pattern** — overwrite-per-run, or append-only?
2. **Staging audit pattern** — history table (SCD-2 style), or `updated_at` + row version?

### Raw layer options

**Overwrite-per-run:** each ingest replaces all rows with the latest API snapshot.
Simple to query. Loses the ability to replay what the data looked like on day N.
Cannot distinguish "data was unchanged" from "data was re-fetched identically",
so idempotency must be enforced at a different layer. The story's acceptance criterion
AC-2 requires "0 new rows on second run", which is impossible to verify if rows are
overwritten rather than inserted.

**Append-only with a content hash:** each ingest run reads the upstream API, hashes
each record, and skips INSERT if a row with the same (source_id, row_hash) already
exists. A new row is only inserted when content changes. This makes idempotency
verifiable via a row count on the ingest run, satisfies AC-2 exactly, and preserves
historical snapshots for future replay or audit. The cost is that raw tables grow over
time; for Philly OPA (~580k parcels) this is ~200 MB/year at typical change rates —
acceptable on a $10 VPS.

### Staging audit options

**History table (SCD-2 style):** a `staging.opa_properties` current table plus a
`staging.opa_properties_history` table that captures every prior version. This is
exactly what AC-3 references. It is explicit, queryable without window functions, and
easy to prune by date if storage becomes a concern. Downside: two tables per dataset
(eight tables total across four datasets).

**Row version + updated_at only:** a single table with `row_version INTEGER` and
`_updated_at TIMESTAMPTZ`. Simpler schema. But the previous version of a row is gone
once it is updated; rollback and time-travel queries require reading the raw layer
instead. This contradicts the layered guarantee: staging is supposed to be the clean,
versioned representation so that raw can be archived.

## Decision

**Raw layer: append-only with a SHA-256 content hash (`row_hash`).** Each raw table
has a composite unique constraint on `(source_id, row_hash)`. The ingest code hashes
the upstream JSON for each record and uses `INSERT ... ON CONFLICT DO NOTHING`. A
second run with identical upstream data produces zero inserts. `ingested_at` records
when each snapshot was written.

**Staging audit pattern: SCD-2 history table.** Each dataset has a `current` table
and a `_history` table. When staging processes a raw row that differs from the current
staging row (by `row_hash`), it inserts the old version into `_history` with
`valid_to = now()` and upserts the new version into `current`. This satisfies AC-3
directly and gives DB-04 and DB-08 access to change history without touching raw.

**Canonical key for OPA records: `parcel_number`.** This is the standard Philly AIS
(Address Information System) parcel identifier, present in every Philly open-data
dataset. It is the foreign key that joins OPA, L&I violations, RTT transfers, and tax
delinquency at the core layer. The story asked whether a composite key was needed; it
is not — `parcel_number` is unique per assessable unit.

## Consequences

- Raw tables grow approximately linearly with the upstream change rate. For Philly's
  four datasets combined, estimate < 1 GB/year. Acceptable. If storage becomes a
  concern, a future story can archive raw rows older than N months to object storage
  without changing the schema contract.
- Each dataset produces three migration files: raw table, staging current table,
  staging history table. Plus one migration for `core.properties` and one for the
  `raw.ingest_log` bookkeeping table. Total: 14 migration files for DB-03.
  This is a one-time cost; the pattern does not repeat per new field added.
- The `ON CONFLICT DO NOTHING` strategy means the pipeline never updates a raw row.
  If a future dataset requires correction of a previously ingested row (e.g., API
  error was backfilled), a separate "raw correction" procedure must be defined. That
  is out of scope for DB-03.
- DB-04 (address normalization) and DB-08 (GBrain) read from `staging.*` current
  tables only. They do not need to read `_history` tables. The history tables are
  written by the ingest pipeline and queried only for audit.

## Alternatives rejected

- **Overwrite-per-run raw**: Cannot satisfy AC-2 (verify 0 insertions on second run).
  Rejected.
- **MD5 hash instead of SHA-256**: MD5 is faster but has known collision
  vulnerabilities (irrelevant for content dedup, but the standard is SHA-256 for new
  code). The performance difference on 580k records is under one second. Rejected in
  favor of SHA-256.
- **Row version + updated_at only for staging**: Loses the prior row value at the
  staging layer. Contradicts the layered guarantee. Rejected.
- **Single staging table with `is_current` flag (SCD-2 in-place)**: Requires filtering
  `WHERE is_current = true` on every read. With 580k parcels, this needs a partial
  index to be fast. The separate current/history table design is simpler for reads and
  the index is on the primary key. Rejected.
