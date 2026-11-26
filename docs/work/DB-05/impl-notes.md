---
owner: data-engineer
last-reviewed: 2026-11-26
stability: draft
---

# DB-05 Implementation Notes

**Status:** review

## Files created / changed

| File | Action |
|---|---|
| `db/migrations/0014_core_properties_score.sql` | New migration: adds `distress_score INTEGER`, `score_components JSONB`, `score_input_hash TEXT`, and `idx_properties_distress_score` |
| `pipelines/score.py` | New scoring pipeline with weight constants, `compute_zip_medians`, `score_property`, `compute_input_hash`, `run`, `main` |
| `apps/portal/main.py` | Added `GET /leads` and `GET /leads/export.csv` endpoints plus psycopg3 connection |
| `apps/portal/requirements.txt` | Added `psycopg[binary]>=3.3.9` |
| `Makefile` | Added `score` and `export-leads` targets; added both to `.PHONY` |
| `tests/unit/db05/__init__.py` | New test package |
| `tests/unit/db05/test_score.py` | 13 unit tests for scoring math |
| `tests/unit/db05/test_leads_api.py` | 3 unit tests for `/leads` endpoints |

## Deviations from design.md

1. **`distress_score INTEGER` (not `SMALLINT`)** — the architect note in the prompt says to use `INTEGER` to match AC-1 wording (`data_type = 'integer'`). The design.md migration example shows `SMALLINT`. `INTEGER` was used in the migration as instructed.

2. **`ADD COLUMN IF NOT EXISTS`** — added `IF NOT EXISTS` guards on all three `ALTER TABLE` column additions to make the migration safely re-runnable on fresh databases. The design shows bare `ADD COLUMN`; this is strictly safer and has no behavioral downside.

3. **`_input_hash` stored in `score_input_hash TEXT` column** — implemented per the preferred alternative described in design section 3: the hash is stored in a separate column, not inside `score_components`. This keeps `score_components` clean (only the four integer factors) so the AC-2 `jsonb_each_text` invariant query works exactly as written without needing `WHERE key != '_input_hash'`.

4. **`compute_input_hash` signature** — the function takes `(parcel_id, delinquent, violation_count, years_held, assessed_value)` matching the prompt spec. The design's `_input_hash` private helper took `(num_years_owed, violation_count, sale_date, assessed_value, zip_code)`. The difference: `parcel_id` is included as a discriminator, `years_held` replaces `sale_date`, and `zip_code` is excluded (the zip median is a derived value, not a raw input). This makes the hash stable to zip-median recomputation while remaining sensitive to changes in the actual property inputs.

5. **`export-leads` Makefile target** — uses `$${DEALBRAIN_HOST:-127.0.0.1}` and writes to `exports/leads.csv` (creating `exports/` dir). The design.md specifies `exports/leads.csv`; the prompt spec says `leads_export.csv`. Design takes precedence (`exports/leads.csv`) since the story AC-6 expects `exports/leads.csv`.

6. **`_top_factors` in portal, not pipelines** — the top-factor extraction helper lives in `apps/portal/main.py` where it is used for CSV generation. The scoring pipeline does not need it.

7. **Portal DB connection** — implemented as a module-level lazy connection (cached on first request). The design notes this is acceptable for a single-process portal dev server. No connection pool was added as the design says "module-level connection" and there is no concurrency story yet.

## How to run

```bash
# Apply migration (requires stack up)
make migrate

# Score all canonical properties
make score

# Start portal and export leads
make up
make export-leads
# → exports/leads.csv
```

## Lint and test output

```
$ make lint
uv run ruff check .
All checks passed!
uv run ruff format --check .
35 files already formatted
uv run mypy --strict .
Success: no issues found in 26 source files

$ make test
...
90 passed, 1 warning in 0.51s
```

DB-05 suite specifically (16 tests):
```
$ uv run pytest tests/unit/db05/ -v
16 passed, 1 warning in 0.21s
```

## Known gaps

- `run()` calls `score_property()` in a per-row loop which re-queries delinquency and
  violations for each property. For large datasets this could be slow. A batch-fetch
  approach is a future optimization.
- The portal DB connection is a bare `psycopg.connect` with no reconnect logic. A
  connection pool (`psycopg_pool`) is the right next step once the portal grows past dev.
- `make score` idempotency relies on `score_input_hash`. If `sale_date` changes in the
  source (e.g. OPA re-publishes a corrected date in the same year), `years_held` is
  unchanged and the row would not be re-scored. This is acceptable per the story scope.
