BEGIN;

CREATE TABLE staging.violations (
    violation_id      TEXT PRIMARY KEY,
    parcel_id         TEXT,
    raw_id            BIGINT NOT NULL,
    row_hash          TEXT NOT NULL,
    address           TEXT,
    violation_code    TEXT,
    violation_desc    TEXT,
    violation_date    DATE,
    case_opened_date  DATE,
    case_status       TEXT,
    _updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE staging.violations_history (
    history_id        BIGSERIAL PRIMARY KEY,
    violation_id      TEXT NOT NULL,
    parcel_id         TEXT,
    raw_id            BIGINT NOT NULL,
    row_hash          TEXT NOT NULL,
    address           TEXT,
    violation_code    TEXT,
    violation_desc    TEXT,
    violation_date    DATE,
    case_opened_date  DATE,
    case_status       TEXT,
    _updated_at       TIMESTAMPTZ NOT NULL,
    valid_from        TIMESTAMPTZ NOT NULL,
    valid_to          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
