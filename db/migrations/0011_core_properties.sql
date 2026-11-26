BEGIN;

CREATE TABLE core.properties (
    parcel_id             TEXT PRIMARY KEY,
    parcel_number         TEXT,
    address               TEXT,
    address_raw           TEXT NOT NULL,
    address_normalized    TEXT,
    zip_code              TEXT,
    owner                 TEXT,
    owner_1               TEXT,
    owner_2               TEXT,
    assessed_value        NUMERIC,
    market_value          NUMERIC,
    land_area             NUMERIC,
    improvement_description TEXT,
    building_code         TEXT,
    category_code         TEXT,
    zoning                TEXT,
    sale_date             DATE,
    sale_price            NUMERIC,
    source_updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_id                BIGINT NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
