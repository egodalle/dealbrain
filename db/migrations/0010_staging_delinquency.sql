BEGIN;

CREATE TABLE staging.delinquency (
    account_number  TEXT PRIMARY KEY,
    parcel_id       TEXT,
    raw_id          BIGINT NOT NULL,
    row_hash        TEXT NOT NULL,
    owner           TEXT,
    total_due       NUMERIC,
    num_years_owed  INT,
    lien_number     TEXT,
    _updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE staging.delinquency_history (
    history_id      BIGSERIAL PRIMARY KEY,
    account_number  TEXT NOT NULL,
    parcel_id       TEXT,
    raw_id          BIGINT NOT NULL,
    row_hash        TEXT NOT NULL,
    owner           TEXT,
    total_due       NUMERIC,
    num_years_owed  INT,
    lien_number     TEXT,
    _updated_at     TIMESTAMPTZ NOT NULL,
    valid_from      TIMESTAMPTZ NOT NULL,
    valid_to        TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
