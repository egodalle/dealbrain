---
owner: architect
last-reviewed: 2026-11-26
stability: stable
---

# DB-06 Design: Connector interface + HubSpot two-way sync

ADR cross-reference: [ADR-0006](../../adr/0006-pending-actions-approval-boundary.md)

## Scope

Establish `BaseConnector`, the `pending_actions` table, the `crm_contacts` table, and
`HubSpotConnector` with fixture-only tests. No live API calls in CI. The approval-portal
UI (DB-12) and the MCP `draft_outreach` tool (DB-10) are out of scope here but share the
same `pending_actions` table whose schema is frozen by this story.

---

## 1. `BaseConnector` interface

**File:** `pipelines/connectors/base.py`

This sits in `pipelines/connectors/` rather than a top-level `connectors/` package.
`apps/mcp` does not need to call connectors directly — it only reads `pending_actions`
and inserts into it. Moving to a shared package would create a cross-app import path
with no current consumer; deferred. See ADR-0006 for the boundary rationale.

```python
from __future__ import annotations
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

@dataclass
class PendingAction:
    connector: str                        # e.g. "hubspot"
    action_type: str                      # e.g. "hubspot_contact_upsert"
    payload: dict[str, Any]              # will be stored as JSONB
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: str = "pending"              # pending | approved | sent | failed
    created_at: datetime = field(default_factory=datetime.utcnow)

class BaseConnector(ABC):
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def push(self, records: list[dict[str, Any]]) -> list[PendingAction]: ...

    @abstractmethod
    def pull_changes(self, since: datetime | None = None) -> list[dict[str, Any]]: ...

    @abstractmethod
    def health_check(self) -> dict[str, str]: ...
```

`PendingAction` is a Python-side dataclass; the DB columns match it (see migration 0015).
Instantiating `BaseConnector` directly raises `TypeError` — standard ABC enforcement.

The story AC names `push`, `pull_changes(since)`, and `health_check`. The design prompt
also listed `pull()` as a synonym; the implementation will expose `pull_changes(since)`.

---

## 2. `pending_actions` table — migration 0015

**File:** `db/migrations/0015_pending_actions.sql`

DB-06 owns this migration. DB-10 (`draft_outreach`) will INSERT into this table but must
not alter its schema; if DB-10 needs new columns, it opens a new migration.

```sql
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
```

Idempotency design: the unique index covers only `pending` and `approved` rows. Once a
row reaches `sent` or `failed` it is no longer "in flight", so a fresh retry produces a
new row rather than silently absorbing it. This is the correct behavior for retries and
for the test in AC-5 (`test_push_is_idempotent`).

The INSERT in `HubSpotConnector.push` uses `ON CONFLICT DO NOTHING` and returns the
surviving row id; callers receive exactly one `PendingAction` per unique record.

---

## 3. `crm_contacts` table — migration 0016

**File:** `db/migrations/0016_crm_contacts.sql`

Placing `crm_contacts` in `core` keeps it on the same FK graph as `core.properties` and
avoids a second schema. The story's open question asked `core` vs `crm`; `core` is chosen
because contacts are first-class data objects with a direct FK to properties, not an
integration artifact.

```sql
BEGIN;

CREATE TABLE core.crm_contacts (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id         TEXT        REFERENCES core.properties(parcel_id),
    hubspot_id          TEXT        UNIQUE,
    first_name          TEXT,
    last_name           TEXT,
    email               TEXT,
    phone               TEXT,
    raw_payload         JSONB,
    last_synced_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_crm_contacts_property_id ON core.crm_contacts (property_id);

COMMIT;
```

Column naming follows story AC-3 and AC-4: `property_id` FK to `core.properties(parcel_id)`,
`raw_payload` for the full HubSpot object. `property_id` is nullable — contacts pulled from
HubSpot may not yet be matched to a property.

---

## 4. `HubSpotConnector`

**File:** `pipelines/connectors/hubspot.py`

### 4a. `push(records) -> list[PendingAction]`

Reads pre-assembled owner dicts (the pipeline that calls push is responsible for querying
`core.properties` and building the contact fields). For each record:

1. Build a `PendingAction(connector="hubspot", action_type="hubspot_contact_upsert", payload=record)`.
2. INSERT into `core.pending_actions` with `ON CONFLICT (connector, action_type, payload_hash) WHERE status IN ('pending','approved') DO NOTHING`.
3. Return the list of inserted (or surviving) `PendingAction` objects.

No HubSpot API call is made. The connector never holds a database connection; callers
pass a `psycopg.Connection` as a parameter (keeps the connector testable without a live DB
in unit tests via a mock connection, and testable with a real DB in integration tests).

Revised signature:
```python
def push(
    self,
    records: list[dict[str, Any]],
    conn: psycopg.Connection[Any],
) -> list[PendingAction]:
```

### 4b. `pull_changes(since) -> list[dict]`

Calls `GET /crm/v3/objects/contacts` (HubSpot CRM API v3) using `httpx`. Bearer token
read from `HUBSPOT_API_KEY` env var at call time (not at construction). Passes
`updatedAfter=since.isoformat()` when `since` is provided.

```python
def pull_changes(self, since: datetime | None = None) -> list[dict[str, Any]]:
    api_key = os.environ.get("HUBSPOT_API_KEY", "")
    if not api_key:
        raise RuntimeError("HUBSPOT_API_KEY not set")
    params = {"limit": 100}
    if since:
        params["updatedAfter"] = since.isoformat()
    resp = self._http.get(
        "https://api.hubapi.com/crm/v3/objects/contacts",
        headers={"Authorization": f"Bearer {api_key}"},
        params=params,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])
```

`self._http` is an `httpx.Client` injected at construction (default: `httpx.Client()`).
Tests replace it with `respx.MockRouter` or `httpx.MockTransport`.

### 4c. `apply_approved(pending_action_id, conn)`

Called only by the portal approve handler (DB-12). Not part of `BaseConnector`; it is a
concrete method on `HubSpotConnector` only. It:

1. Loads the `pending_actions` row, asserts `status = 'approved'`.
2. Calls the HubSpot API (`POST /crm/v3/objects/contacts` or `PATCH` for updates).
3. Upserts `core.crm_contacts` with the response.
4. Sets `pending_actions.status = 'sent'` and `sent_at = now()`.
5. All steps in one transaction.

This method is out of scope for DB-06 (the portal approve handler is DB-12). The method
signature is defined here so DB-12 has a stable calling convention:

```python
def apply_approved(
    self,
    pending_action_id: uuid.UUID,
    conn: psycopg.Connection[Any],
) -> dict[str, Any]:
    ...
```

### 4d. Webhook handler (inbound — HubSpot to Postgres)

**Route:** `POST /hubspot/webhook` on `apps/portal/main.py`

HubSpot's verification strategy: the `X-HubSpot-Signature-v3` header carries an HMAC-SHA256
of `{method}{url}{body}{timestamp}` keyed with `HUBSPOT_CLIENT_SECRET`. This is the
recommended v3 method over OAuth token introspection, which is an OAuth-only flow.
See: https://developers.hubspot.com/docs/api/webhooks/validating-requests

The handler:
1. Verifies HMAC signature using `HUBSPOT_CLIENT_SECRET`.
2. Returns HTTP 403 if verification fails (AC-7 of DB-07, guardrail pattern).
3. Parses the event list (HubSpot sends a JSON array).
4. For each `contact.propertyChange` event, upserts `core.crm_contacts` via `hubspot_id`.
5. Creates a `PendingAction` with `action_type='hubspot_contact_import'` and
   `status='approved'` (this is an inbound change, not an outbound send, so it may be
   auto-approved by the portal; the exact policy is DB-12's concern).

For DB-06, the webhook handler processes fixture payloads only — no live endpoint. The
route must exist and be reachable in tests via `httpx.AsyncClient(app=app)`.

```python
@app.post("/hubspot/webhook", status_code=200)
async def hubspot_webhook(request: Request) -> dict[str, str]:
    ...
```

---

## 5. Fixture testing strategy

### Dependencies to add

```
# pyproject.toml or requirements.txt (dev)
respx>=0.21
```

`respx` mocks `httpx` transports at the router level — no monkey-patching. CI has no
`HUBSPOT_API_KEY`; tests that call `pull_changes` must set up a `respx` route or pass a
mock `httpx.Client`.

### Test layout

```
tests/
  unit/
    db06/
      test_hubspot_connector.py   # AC-1 through AC-7
      conftest.py                 # fixture payloads + mock conn
  fixtures/
    hubspot/
      contact_list.json           # mocked GET /crm/v3/objects/contacts response
      webhook_payload.json        # mocked POST /hubspot/webhook body
      webhook_payload_bad_sig.json
  integration/
    test_db06_migrations.py       # runs make db-migrate, verifies tables exist
```

### Unit test index (maps to story AC)

| Test name | AC | Verifies |
|---|---|---|
| `test_base_connector_is_abstract` | AC-1 | `TypeError` on direct instantiation |
| `test_push_writes_pending_action` | AC-2 | INSERT into `pending_actions`, no HTTP |
| `test_pull_upserts_crm_contact` | AC-3 | fixture payload upserts `crm_contacts`, prints `hubspot_id` |
| `test_crm_contacts_migration` | AC-4 | table has required columns (integration) |
| `test_push_is_idempotent` | AC-5 | second push yields COUNT=1 |
| `test_no_live_calls_in_ci` | AC-6 | `respx.mock` asserts no unmocked requests |
| `test_health_check` | AC-7 | both branches (key present / absent) |

For AC-2 and AC-5, `conn` is a mock (`unittest.mock.MagicMock`) in unit tests. For the
integration variant in `tests/integration/test_db06_migrations.py`, `conn` is a real
psycopg connection to the pgvector container.

---

## 6. Portal webhook route

Add to `apps/portal/main.py`:

```python
@app.post("/hubspot/webhook", status_code=200)
async def hubspot_webhook(request: Request) -> dict[str, str]:
    body = await request.body()
    sig  = request.headers.get("X-HubSpot-Signature-v3", "")
    ts   = request.headers.get("X-HubSpot-Request-Timestamp", "")
    _verify_hubspot_hmac(sig, ts, str(request.url), body)   # raises HTTP 403 on failure
    events = json.loads(body)
    conn = _get_conn()
    HubSpotConnector().handle_webhook_events(events, conn)
    conn.commit()
    return {"status": "ok"}
```

`_verify_hubspot_hmac` is a module-level helper in `apps/portal/main.py` — not in the
connector — because signature verification uses the request context (URL, timestamp).

---

## 7. Migration numbers

Last existing migration: `0014_core_properties_score.sql`

| Number | File | Owned by |
|---|---|---|
| 0015 | `db/migrations/0015_pending_actions.sql` | DB-06 |
| 0016 | `db/migrations/0016_crm_contacts.sql` | DB-06 |

DB-10's `draft_outreach` tool will INSERT into `core.pending_actions` using migration 0015.
DB-10 must not add columns; it must open a new migration if the schema needs extending.

---

## 8. Makefile target

Add to `Makefile`:

```makefile
sync-hubspot:
	docker compose up -d --wait db
	uv run python -m pipelines.connectors.hubspot_sync
```

`pipelines/connectors/hubspot_sync.py` is the entry-point module that queries
`core.properties`, builds contact records, and calls `HubSpotConnector().push(records, conn)`.

---

## Sequence diagram

```
HubSpot (fixture) ──pull_changes()──► HubSpotConnector ──upsert──► core.crm_contacts
                                                                      (no approval needed
                                                                       for inbound data)

portal operator ──► owner record ──push()──► HubSpotConnector ──INSERT──► core.pending_actions
                                              (no API call)                 status=pending

portal operator ──► /approve ──► apply_approved() ──POST/PATCH──► HubSpot API
                                  (DB-12)             (DB-06 defines the signature)
```

---

## Failure modes and retries

| Failure | Behavior |
|---|---|
| `HUBSPOT_API_KEY` absent | `pull_changes` raises `RuntimeError`; `health_check` returns `{"status":"degraded"}` |
| HubSpot API 429 | `httpx` raises `HTTPStatusError`; caller retries (retry policy in `hubspot_sync.py`, not in connector) |
| HubSpot API 5xx | Same; connector does not retry internally to keep it testable |
| Duplicate push | `ON CONFLICT DO NOTHING`; no error, existing row returned |
| Bad HMAC on webhook | HTTP 403 returned immediately, no DB write |
| DB unavailable during push | `psycopg` raises; transaction rolled back by caller; `pending_actions` row not created |

---

## Implementation checklist

- [ ] `pipelines/connectors/__init__.py` (empty)
- [ ] `pipelines/connectors/base.py` — `PendingAction` dataclass + `BaseConnector` ABC
- [ ] `pipelines/connectors/hubspot.py` — `HubSpotConnector` with `push`, `pull_changes`, `health_check`, `handle_webhook_events`, `apply_approved` stub
- [ ] `pipelines/connectors/hubspot_sync.py` — entry-point called by `make sync-hubspot`
- [ ] `db/migrations/0015_pending_actions.sql`
- [ ] `db/migrations/0016_crm_contacts.sql`
- [ ] `apps/portal/main.py` — add `POST /hubspot/webhook` route and `_verify_hubspot_hmac`
- [ ] `tests/unit/db06/conftest.py`
- [ ] `tests/unit/db06/test_hubspot_connector.py` — all 7 AC tests
- [ ] `tests/fixtures/hubspot/contact_list.json`
- [ ] `tests/fixtures/hubspot/webhook_payload.json`
- [ ] `tests/integration/test_db06_migrations.py`
- [ ] Add `respx>=0.21` to dev dependencies
- [ ] `Makefile` — `sync-hubspot` target
- [ ] `make lint test` passes with `HUBSPOT_API_KEY` unset
