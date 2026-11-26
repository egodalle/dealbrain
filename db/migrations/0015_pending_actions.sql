BEGIN;

CREATE TABLE core.pending_actions (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    connector    TEXT        NOT NULL,
    action_type  TEXT        NOT NULL,
    payload      JSONB       NOT NULL,
    status       TEXT        NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending','approved','sent','failed')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at  TIMESTAMPTZ,
    sent_at      TIMESTAMPTZ
);

-- Idempotency: a second push of the same logical record (same connector + action_type +
-- payload hash) must not produce a duplicate pending row.  We store the hash in a
-- generated column so the unique index is cheap and the payload can still be updated.
ALTER TABLE core.pending_actions
    ADD COLUMN payload_hash TEXT GENERATED ALWAYS AS (md5(payload::text)) STORED;

CREATE UNIQUE INDEX uq_pending_actions_idempotent
    ON core.pending_actions (connector, action_type, payload_hash)
    WHERE status IN ('pending', 'approved');

COMMIT;
