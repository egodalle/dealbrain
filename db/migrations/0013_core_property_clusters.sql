BEGIN;

CREATE TABLE core.property_clusters (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cluster_id    UUID    NOT NULL,
    property_id   TEXT    NOT NULL REFERENCES core.properties(parcel_id),
    is_canonical  BOOL    NOT NULL DEFAULT false,
    matched_on    TEXT    NOT NULL CHECK (matched_on IN ('address', 'owner_name', 'both')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_property_clusters_property_id
    ON core.property_clusters (property_id);

CREATE INDEX idx_property_clusters_cluster_id
    ON core.property_clusters (cluster_id);

COMMENT ON TABLE core.property_clusters IS
    'One row per property per cluster. Each cluster has exactly one is_canonical=true row.';

COMMIT;
