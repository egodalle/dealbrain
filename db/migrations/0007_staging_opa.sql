BEGIN;

CREATE TABLE staging.opa_properties (
    parcel_id                  TEXT PRIMARY KEY,
    raw_id                     BIGINT NOT NULL,
    row_hash                   TEXT NOT NULL,
    location                   TEXT,
    unit                       TEXT,
    zip_code                   TEXT,
    owner_1                    TEXT,
    owner_2                    TEXT,
    building_code              TEXT,
    building_code_description  TEXT,
    category_code              TEXT,
    category_code_description  TEXT,
    market_value               NUMERIC,
    sale_date                  DATE,
    sale_price                 NUMERIC,
    taxable_land               NUMERIC,
    taxable_building           NUMERIC,
    exempt_land                NUMERIC,
    exempt_building            NUMERIC,
    _created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    _updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE staging.opa_properties_history (
    history_id  BIGSERIAL PRIMARY KEY,
    parcel_id                  TEXT NOT NULL,
    raw_id                     BIGINT NOT NULL,
    row_hash                   TEXT NOT NULL,
    location                   TEXT,
    unit                       TEXT,
    zip_code                   TEXT,
    owner_1                    TEXT,
    owner_2                    TEXT,
    building_code              TEXT,
    building_code_description  TEXT,
    category_code              TEXT,
    category_code_description  TEXT,
    market_value               NUMERIC,
    sale_date                  DATE,
    sale_price                 NUMERIC,
    taxable_land               NUMERIC,
    taxable_building           NUMERIC,
    exempt_land                NUMERIC,
    exempt_building            NUMERIC,
    _created_at                TIMESTAMPTZ NOT NULL,
    _updated_at                TIMESTAMPTZ NOT NULL,
    valid_from                 TIMESTAMPTZ NOT NULL,
    valid_to                   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
