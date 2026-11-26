BEGIN;

ALTER TABLE core.properties
    ADD COLUMN IF NOT EXISTS distress_score   INTEGER,
    ADD COLUMN IF NOT EXISTS score_components JSONB,
    ADD COLUMN IF NOT EXISTS score_input_hash TEXT;

COMMENT ON COLUMN core.properties.distress_score IS
    'Weighted distress score 0–100. NULL until score pipeline has run for this row.';

COMMENT ON COLUMN core.properties.score_components IS
    'Integer sub-scores by factor. Keys: delinquency, violations, years_held, value_gap.
     Values are integers that sum exactly to distress_score.';

COMMENT ON COLUMN core.properties.score_input_hash IS
    'SHA-256 (truncated 16 chars) of scoring inputs. Used to skip re-scoring unchanged rows.';

CREATE INDEX IF NOT EXISTS idx_properties_distress_score
    ON core.properties (distress_score DESC NULLS LAST);

COMMIT;
