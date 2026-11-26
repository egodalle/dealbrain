---
owner: architect
last-reviewed: 2026-11-26
stability: stable
---

# ADR-0005: Scoring weights as code constants, not a database table

## Context

DB-05 requires a weighted sum across four distress factors. The story's open questions ask
whether weights should live in a constants file in `pipelines/`, a config YAML, or a
`core.score_weights` table. The choice affects how easy it is to retune weights without a
code deploy, and whether weight changes are auditable.

## Decision

Weights are defined as named constants at the top of `pipelines/score.py`. They are not
stored in the database, not read from a YAML file, and not configurable via environment
variable.

```python
WEIGHT_DELINQUENCY  = 35
WEIGHT_VIOLATIONS   = 25
WEIGHT_YEARS_HELD   = 20
WEIGHT_VALUE_GAP    = 20
# Must sum to 100.
```

A module-level assertion `assert WEIGHT_DELINQUENCY + WEIGHT_VIOLATIONS + WEIGHT_YEARS_HELD + WEIGHT_VALUE_GAP == 100` guards the invariant at import time.

## Consequences

Positive:
- Weight changes are code changes — they appear in git history with a commit message,
  code review, and CI run. This is the audit trail we want.
- No new DB objects, no migration, no env-var handling.
- Tests can import the constants directly; no DB or config fixture needed.
- The scoring function is fully deterministic from code alone — identical inputs always
  produce identical outputs regardless of environment or deployment state.

Negative:
- Retuning requires a code deploy. At the current stage (one city, rule-based model,
  pre-launch) this is acceptable; the team deploys multiple times per day.
- If a business stakeholder wants live weight editing from a UI, this needs to change.
  The right time to add `core.score_weights` is when that requirement arrives, not
  speculatively.

## Alternatives rejected

**YAML config file (`config/score_weights.yaml`)** — adds a file format, a parser, and
error handling for missing or malformed values. Provides no benefit over code constants
at this stage since the YAML is still committed to git and still requires a deploy.

**`core.score_weights` table** — adds a migration, a SELECT on every scoring run, and the
possibility of weights being changed in production without a code review. Versioning weight
changes via DB rows is more complex than versioning via commits. Deferred until the product
explicitly needs live tuning.

**Environment variables** — worse than a constants file: values are hidden from code
review, not logged in CI, and require the VPS environment to be updated in sync with the
code that uses them.
