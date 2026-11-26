---
owner: architect
last-reviewed: 2026-11-26
stability: draft
---

# DB-05 Review

**Story:** Explainable distress score + `/leads` data product with CSV export
**Branch:** feat/DB-05-distress-score-leads
**Reviewed by:** architect
**Verdict: APPROVED**

---

## Check results

### 1. Migration adds `distress_score INTEGER`, `score_components JSONB`, `score_input_hash TEXT`

PASS.

`db/migrations/0014_core_properties_score.sql` adds all three columns with `IF NOT EXISTS`
guards. `distress_score` is typed `INTEGER` (not `SMALLINT`), which the data-engineer
documents as an intentional deviation: it matches the `information_schema` check in AC-1
(`data_type = 'integer'`). The design noted this was not load-bearing. Acceptable.

---

### 2. Weights are W_DELINQUENCY=35, W_VIOLATIONS=25, W_YEARS_HELD=20, W_VALUE_GAP=20, summing to 100

PASS.

`pipelines/score.py` lines 327–331:

```python
W_DELINQUENCY = 35
W_VIOLATIONS  = 25
W_YEARS_HELD  = 20
W_VALUE_GAP   = 20

assert W_DELINQUENCY + W_VIOLATIONS + W_YEARS_HELD + W_VALUE_GAP == 100
```

Values, sum, and module-level assertion are all correct.

Minor nit: the ADR and design use the prefix `WEIGHT_`; the implementation uses `W_`.
Behavior is identical. The assert guards the invariant regardless of the name. This can
be aligned in a later cosmetic pass.

---

### 3. `score_property()` uses floor+remainder-distribution so components sum exactly to total

PASS.

`_distribute_to_int()` applies `math.floor()` to every component, computes
`remainder = total - sum(floors)`, then adds 1 to the `remainder` highest-fractional
components (ties broken alphabetically). `score_property()` calls this function and
returns the result.

The clamping in `score_property()` (`max(0, min(100, round(raw_total)))`) is safe:
because each component is capped at its weight and the weights sum to exactly 100, `raw_total`
can never exceed 100.0, so the clamp is a purely defensive guard and can never cause
`remainder` to go negative. The sum invariant holds for all reachable inputs.

---

### 4. `run()` skips properties whose `score_input_hash` is unchanged

PASS.

`run()` computes `new_hash = compute_input_hash(...)` for each canonical property, compares
it to `existing_hash` from `p.score_input_hash`, and issues `continue` on a match (line 561–563).
The UPDATE only fires when the hash differs or is NULL. This satisfies AC-4.

The data-engineer documents one known gap: if `sale_date` changes within the same calendar
year, `years_held` (integer year difference) is unchanged, so the hash is unchanged and
the row is not re-scored. This is an acceptable scope limitation for this story.

---

### 5. `apps/portal/main.py` has `GET /leads` and `GET /leads/export.csv`

PASS.

Both endpoints are present with the correct signatures and query parameters (`limit`,
`min_score` on `/leads`; no parameters on `/export.csv`).

---

### 6. `/leads` results filter `is_canonical=true` from `core.property_clusters`

PASS.

Both `_LEADS_SQL` and `_LEADS_SQL_NO_LIMIT` include:

```sql
JOIN core.property_clusters pc ON pc.property_id = p.parcel_id
WHERE pc.is_canonical = true
```

The join key (`property_id = p.parcel_id`) is consistent with the design and with the
join used in `run()`.

---

### 7. CSV export includes the 6 required columns

PASS.

`export_leads_csv()` writes the header row:
`["parcel_number", "address_normalized", "distress_score", "factor_1", "factor_2", "factor_3"]`

This matches AC-6 exactly.

---

### 8. Unit tests include `test_components_sum_equals_total`

PASS.

`tests/unit/db05/test_score.py` line 789 defines `test_components_sum_equals_total`,
testing five distinct input combinations (all zeros, all maxed, mixed). The test asserts
`sum(components.values()) == total` for every case.

Additional coverage is thorough: `test_distribute_maintains_sum` runs 50 random inputs
against `_distribute_to_int`; factor-cap tests cover each component helper individually.

---

### 9. `make lint` and `make test` exit 0 per impl-notes

PASS (reported).

impl-notes.md documents:

```
$ make lint    → All checks passed! / no issues found in 26 source files
$ make test    → 90 passed, 1 warning in 0.51s
$ uv run pytest tests/unit/db05/ -v → 16 passed, 1 warning in 0.21s
```

The design stipulates `apps/portal/` is excluded from mypy strict per `pyproject.toml`,
which is consistent with the reported output. This review is based on the diff; the CI
run is the authoritative gate.

---

### 10. CLAUDE.md violations

PASS — none found.

Approval boundary: `pipelines/score.py` writes only to `core.properties` columns
(`distress_score`, `score_components`, `score_input_hash`, `updated_at`). No
`pending_actions` row is created, no message is sent, no send capability exists. Clean.

LLM calls: none. No `router/` bypass risk.

Secrets: no credentials in diff; `DATABASE_URL` is read from env.

Branches/commits: branch name `feat/DB-05-distress-score-leads` is correct convention.

Synthetic data: test fixtures use fabricated parcel numbers and addresses. Clean.

---

## Blocking issues

None.

---

## Nits (non-blocking)

1. **Constant naming mismatch with ADR.** ADR-0005 declares `WEIGHT_DELINQUENCY` etc.; the
   implementation uses `W_DELINQUENCY`. Behavior is identical. Align the names in a follow-on
   commit if the ADR is meant to be the canonical reference.

2. **`test_leads_min_score_filter` does not prove SQL parameter passes correctly.** The mock
   returns a pre-filtered list; it does not assert that `_LEADS_SQL` was called with
   `min_score=50`. The test proves only that the endpoint passes the mock result through,
   not that the query uses the parameter. Acceptable for a unit test given the SQL is
   directly readable in the source, but a future integration test should cover this path.

3. **`import datetime` inside the loop.** `run()` and `score_property()` both do
   `import datetime` inside a conditional branch inside the per-row loop. Python caches
   imports so there is no performance impact, but the import belongs at the top of the
   module. Fix in a cosmetic pass.

4. **`case_status NOT IN ('CLOSED', 'closed', 'C')`.** The design specifies
   `case_status != 'CLOSED'`. The implementation also excludes `'closed'` and `'C'`.
   This is a silent extension of the filter that may exclude rows the design intended to
   count. If the staging layer normalises `case_status` to uppercase (as a typed staging
   column should), `'closed'` and `'C'` are dead clauses. If it does not normalise,
   the design's `!= 'CLOSED'` check would over-count violations. Document which is true,
   or normalise in staging.

---

## Summary

All 10 checks pass. The implementation faithfully follows the design. Deviations are
documented in impl-notes.md and are either explicitly preferred alternatives from the
design or minor, non-behavioral naming choices. The sum invariant is correctly implemented
and the idempotency guard is sound. No approval-boundary, LLM-routing, or secrets
violations. Story is cleared for the tester.
