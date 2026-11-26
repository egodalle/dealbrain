# DB-05: Explainable distress score + `/leads` data product with CSV export

**Status:** done · **Plan day:** 3 · **Posting lines covered:** Portals, dashboards, RE data products; Collect, transform, dedupe, score, deliver

## Story
As an **acquisitions rep reviewing DealBrain leads**, I want every scored property to show
me a plain breakdown of why it ranked where it did so that I can prioritize my call list
and explain my reasoning to the investor without opening a spreadsheet.

## Acceptance criteria

1. `core.properties` has two new columns: `distress_score INTEGER` (0–100, NOT NULL after
   the scoring run) and `score_components JSONB`. Verify with:
   ```sql
   SELECT column_name, data_type
   FROM information_schema.columns
   WHERE table_schema = 'core'
     AND table_name = 'properties'
     AND column_name IN ('distress_score', 'score_components');
   ```
   Both column names must appear in the result.

2. After `make score` completes, every scored row satisfies the sum invariant. Verify with:
   ```sql
   SELECT COUNT(*)
   FROM core.properties
   WHERE distress_score IS NOT NULL
     AND distress_score <> (
       SELECT COALESCE(SUM(value::numeric), 0)
       FROM jsonb_each_text(score_components)
     );
   ```
   Result must be **0**. No row may carry a total that differs from the sum of its components.

3. `score_components` for every scored row contains at least three named factors (e.g.
   `tax_delinquency`, `code_violations`, `vacancy_indicator`). Verify with:
   ```sql
   SELECT COUNT(*)
   FROM core.properties
   WHERE distress_score IS NOT NULL
     AND jsonb_array_length(ARRAY(SELECT jsonb_object_keys(score_components))::jsonb) < 3;
   ```
   Result must be **0**.

4. `make score` is idempotent. Running it twice with no data change leaves the row counts
   and score values unchanged. Verify after the second run:
   ```sql
   SELECT COUNT(*) FROM core.properties
   WHERE distress_score IS NOT NULL
     AND updated_at > now() - interval '5 seconds';
   ```
   Result must be **0** (no rows touched on the second run).

5. `GET /leads?limit=N` on the portal returns a JSON array of the top-N canonical
   properties ordered by `distress_score DESC`. Each object must include at minimum:
   `parcel_number`, `address_normalized`, `distress_score`, and `score_components`.
   Verify by running:
   ```
   curl -s "http://localhost:8000/leads?limit=5" | python -m json.tool
   ```
   The response must be valid JSON, contain exactly 5 objects, and each object must have
   all four required keys. Non-canonical rows (`is_canonical = false` in
   `core.property_clusters`) must not appear in the results.

6. `make export-leads` produces a file `exports/leads.csv` with columns:
   `parcel_number`, `address_normalized`, `distress_score`, `factor_1`, `factor_2`,
   `factor_3` (the three highest-weighted component names). Verify:
   ```
   head -1 exports/leads.csv
   ```
   Must print exactly:
   `parcel_number,address_normalized,distress_score,factor_1,factor_2,factor_3`
   And:
   ```
   wc -l exports/leads.csv
   ```
   Must be >= 2 (header plus at least one data row).

7. `make test SUITE=db05` runs unit tests for the scoring logic and all pass. Tests must
   cover: each factor's sub-score calculation, the sum invariant check, the top-3 factor
   extraction, and idempotency guard. Output must show all tests green with no skips.

## Demo line
Open the portal `/leads` page live: the top 10 distressed properties load in under 2 seconds,
each row shows the score and the three factors that drove it; then run `make export-leads`
in the terminal and open the resulting CSV in the same frame.

## Out of scope
- Machine-learning scoring models; rule-based weighted sum only for this story
- Sending any outreach or creating any `pending_actions` row
- Score decay or time-weighted factors
- More than one city (Philly canonical data only)
- UI beyond the JSON endpoint and CSV export (charts, maps belong in a later story)
- Authentication on the `/leads` endpoint (covered by the portal auth story)

## Open questions for Architect
- Should `distress_score` and `score_components` be added via a new migration
  `0012_distress_score.sql`, or patched onto `0011_core_properties.sql`? A new file
  keeps the migration log clean; a patch avoids a two-step apply on fresh installs.
- What is the canonical weight table for the scoring factors (tax_delinquency,
  code_violations, vacancy_indicator, days_since_sale, etc.) and where does it live:
  a constants file in `pipelines/`, a config YAML, or a `core.score_weights` table?
  The choice affects how easy it is to retune weights without a code deploy.
- The sum invariant in AC-2 uses `jsonb_each_text` with a cast to numeric. If a component
  value is ever stored as a string rather than a JSON number the query returns a cast error.
  Should the data-engineer enforce JSON number types at write time, or should the invariant
  query use a safer cast?
- `GET /leads` must filter to canonical rows via `core.property_clusters`. Confirm the
  join key: is it `core.properties.parcel_id` matching `core.property_clusters.property_id`,
  or `parcel_number`? DB-04 story uses `property_id` but `0011_core_properties.sql` uses
  `parcel_id` as the primary key.
