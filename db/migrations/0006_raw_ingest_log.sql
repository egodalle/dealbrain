BEGIN;

CREATE TABLE raw.ingest_log (
    run_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source       TEXT NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    rows_fetched INT,
    rows_inserted INT,
    status       TEXT NOT NULL DEFAULT 'running',
    error        TEXT
);

COMMIT;
