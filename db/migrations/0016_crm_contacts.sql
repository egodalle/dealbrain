BEGIN;

CREATE TABLE core.crm_contacts (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id    TEXT        REFERENCES core.properties(parcel_id),
    hubspot_id     TEXT        UNIQUE,
    first_name     TEXT,
    last_name      TEXT,
    email          TEXT,
    phone          TEXT,
    raw_payload    JSONB,
    last_synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_crm_contacts_property_id ON core.crm_contacts (property_id);

COMMIT;
