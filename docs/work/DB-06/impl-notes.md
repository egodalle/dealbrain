---
owner: data-engineer
last-reviewed: 2026-11-26
stability: draft
---

# DB-06 Implementation Notes

## Status: review

## Files created

| File | Purpose |
|------|---------|
| `db/migrations/0015_pending_actions.sql` | `core.pending_actions` table with generated `payload_hash` column and idempotency index |
| `db/migrations/0016_crm_contacts.sql` | `core.crm_contacts` table with FK to `core.properties(parcel_id)` |
| `pipelines/connectors/__init__.py` | Empty package marker |
| `pipelines/connectors/base.py` | `PendingAction` dataclass and `BaseConnector` ABC |
| `pipelines/connectors/hubspot.py` | `HubSpotConnector` with `push`, `pull_changes`, `handle_webhook_events`, `apply_approved`, `verify_webhook_signature`, `health_check` |
| `pipelines/connectors/hubspot_sync.py` | Entry-point module for `make sync-hubspot` |
| `apps/portal/main.py` | Added `POST /hubspot/webhook` route and `_verify_hubspot_hmac` helper |
| `Makefile` | Added `sync-hubspot` target |
| `tests/unit/db06/__init__.py` | Package marker |
| `tests/unit/db06/test_base_connector.py` | 2 tests: PendingAction fields, ABC enforcement |
| `tests/unit/db06/test_hubspot_connector.py` | 9 tests: push, pull_changes pagination, signature, health_check |
| `tests/unit/db06/test_webhook_route.py` | 2 tests: valid signature 200, invalid 403 |
| `tests/fixtures/hubspot/contact_list.json` | Mocked GET /crm/v3/objects/contacts response |
| `tests/fixtures/hubspot/contact_list_page2.json` | First page with pagination cursor |
| `tests/fixtures/hubspot/contact_list_page3.json` | Second page (no cursor) |
| `tests/fixtures/hubspot/webhook_payload.json` | Mocked POST /hubspot/webhook body |

## Deviations from design.md

1. **`BaseConnector.push` signature**: Design specifies `push(records, conn)` with a
   `psycopg.Connection` parameter. The base class uses `Any` for `conn` to avoid a
   mandatory psycopg import in the ABC and to keep unit tests mockable without psycopg
   installed in test isolation. `HubSpotConnector` accepts `Any` and calls `.execute()`.

2. **`verify_webhook_signature` on the connector**: The design placed HMAC verification
   as a module-level helper `_verify_hubspot_hmac` in `apps/portal/main.py` (using the
   full `{method}{url}{body}{timestamp}` message per HubSpot v3 spec), and also on
   `HubSpotConnector` with a simpler `payload_bytes`-only signature for unit testability.
   Both are present. The portal uses `_verify_hubspot_hmac`; the connector method is
   the unit-testable variant.

3. **`PendingAction.payload_hash` field absent from dataclass**: The design stores
   `payload_hash` as a Postgres generated column (`md5(payload::text)`), not in the
   Python dataclass. This matches the migration and avoids duplicating the hash logic.
   The unique index on `(connector, action_type, payload_hash)` handles idempotency at
   the DB level; `ON CONFLICT DO NOTHING` in the INSERT is the Python-side contract.

4. **`apply_approved` stub**: Per the story and design, DB-12 owns the full HubSpot API
   call. The stub marks the row as `sent` without calling the API, satisfying the
   design's defined calling convention.

5. **`datetime.utcnow()` deprecation warning**: Python 3.12 deprecates `utcnow()`. The
   design uses it; changing it is out of scope for this story. The warning appears in
   test output but does not cause failures.

## How to run

```bash
# Lint
make lint

# Tests (spins up DB container locally, skipped in CI)
make test

# Apply migrations to local pgvector container
make migrate

# Queue sync (requires DATABASE_URL and running DB)
make sync-hubspot
```

## make lint output

```
uv run ruff check .
All checks passed!
uv run ruff format --check .
43 files already formatted
uv run mypy --strict .
Success: no issues found in 34 source files
```

## make test output

```
103 passed, 6 warnings in 0.48s
```

(13 new tests in tests/unit/db06/, 90 existing tests all still passing)

## Known gaps

- Integration test `tests/integration/test_db06_migrations.py` is not part of this
  story's unit test requirement. The Tester owns acceptance/integration tests.
- `respx` matching with query param `params__contains` may be order-sensitive across
  respx versions; the pagination test uses `side_effect` on a broad URL match which
  is robust.
- `datetime.utcnow()` in `PendingAction` will need migration to `datetime.now(UTC)`
  when Python 3.12 deprecation becomes a hard error.
