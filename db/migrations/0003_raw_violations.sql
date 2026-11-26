BEGIN;

CREATE TABLE raw.violations (
    id          BIGSERIAL PRIMARY KEY,
    source_id   TEXT NOT NULL,
    row_hash    TEXT NOT NULL,
    payload     JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id      UUID NOT NULL,
    UNIQUE (source_id, row_hash)
);

COMMIT;
