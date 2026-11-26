BEGIN;

CREATE TABLE staging.transfers (
    document_id      TEXT PRIMARY KEY,
    parcel_id        TEXT,
    raw_id           BIGINT NOT NULL,
    row_hash         TEXT NOT NULL,
    grantee          TEXT,
    grantor          TEXT,
    recording_date   DATE,
    sale_price       NUMERIC,
    document_type    TEXT,
    _updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE staging.transfers_history (
    history_id       BIGSERIAL PRIMARY KEY,
    document_id      TEXT NOT NULL,
    parcel_id        TEXT,
    raw_id           BIGINT NOT NULL,
    row_hash         TEXT NOT NULL,
    grantee          TEXT,
    grantor          TEXT,
    recording_date   DATE,
    sale_price       NUMERIC,
    document_type    TEXT,
    _updated_at      TIMESTAMPTZ NOT NULL,
    valid_from       TIMESTAMPTZ NOT NULL,
    valid_to         TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
