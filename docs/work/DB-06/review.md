---
owner: architect
last-reviewed: 2026-11-26
stability: draft
---

# DB-06 Review

Reviewer: architect
Branch: feat/DB-06-hubspot-connector
Diff base: main

---

## Check results

### 1. `0015_pending_actions.sql` — partial unique index with payload_hash
PASS. Table created with all required columns. `payload_hash` added as a
`GENERATED ALWAYS AS (md5(payload::text)) STORED` column. Unique index
`uq_pending_actions_idempotent` on `(connector, action_type, payload_hash)
WHERE status IN ('pending', 'approved')` matches the design exactly.

### 2. `0016_crm_contacts.sql` — `hubspot_id TEXT UNIQUE`
PASS. `hubspot_id TEXT UNIQUE` is present. All story AC-4 required columns
are present (`hubspot_id`, `property_id` FK, `first_name`, `last_name`,
`email`, `phone`, `last_synced_at`, `raw_payload`). `updated_at` is a
welcome addition.

### 3. `BaseConnector` as ABC with abstract `push`, `pull_changes`
PASS. `base.py` defines `BaseConnector(ABC)` with `@abstractmethod` on
`name`, `push`, `pull_changes`, and `health_check`. `test_base_connector_is_abstract`
confirms `TypeError` on direct instantiation. The design also listed the
abstract methods by those exact names; all present.

### 4. `HubSpotConnector.push()` creates `PendingAction` objects with no HTTP calls
PASS. `push()` constructs `PendingAction` objects, calls `conn.execute()`
with an INSERT, and returns the list. No `httpx` call or `self._http` reference
anywhere in `push()`. The only network-capable attribute (`self._http`) is
untouched during `push`.

### 5. `HubSpotConnector.verify_webhook_signature()` uses HMAC-SHA256
PASS. Implementation uses `hmac.new(self._client_secret.encode(), payload_bytes,
hashlib.sha256).hexdigest()` and `hmac.compare_digest` for constant-time
comparison. Correct algorithm and timing-safe comparison.

### 6. `POST /hubspot/webhook` returns 403 on invalid signature
PASS. `_verify_hubspot_hmac` raises `HTTPException(status_code=403)` when
the computed digest does not match. `test_webhook_invalid_signature` asserts
`status_code == 403`. Verified in diff.

### 7. Tests mock HTTP calls — no live API dependencies
PASS. `pull_changes` tests use `@respx.mock` decorator. `push` tests use
`unittest.mock.MagicMock` for the connection. `test_webhook_route.py` uses
`fastapi.testclient.TestClient` with a patched `_get_conn`. No test sets a
real `HUBSPOT_API_KEY` without also mocking the transport.

### 8. `make lint` and `make test` exit 0 per impl-notes
PASS (reported). impl-notes records `ruff check`, `ruff format --check`, and
`mypy --strict` all clean, and 103 tests passing with 6 warnings. Cannot
independently execute here, but output is fully quoted and plausible given the
diff.

### 9. Approval-boundary violations
BLOCKING — see finding B-1 below.

### 10. FK is `parcel_id` not `parcel_number` in 0016 — consistent with 0011?
PASS. `0011_core_properties.sql` declares `parcel_id TEXT PRIMARY KEY`.
Migration 0016 references `core.properties(parcel_id)`. The FK column name
and target are consistent. `parcel_number` is a non-key column in 0011;
it is never used as a FK target.

---

## Blocking findings

### B-1: `respx` added as a production dependency — must be dev-only

`pyproject.toml` adds `respx>=0.23.1` to the top-level `[project]
dependencies` list (line visible in diff: `"respx>=0.23.1"`). `respx` is a
test-only HTTP mocking library. Shipping it as a production dependency:

- expands the production image with a test-only package,
- violates the design's statement that `respx` goes in `# pyproject.toml or
  requirements.txt (dev)`, and
- means `respx` is imported in a production context if anything triggers the
  httpx route — this has caused subtle bugs in other projects when test
  transports leak into prod.

Required fix: move `respx>=0.23.1` to `[dependency-groups] dev` (or
equivalent `[project.optional-dependencies] dev` group) and ensure the CI
test step installs with `uv sync --group dev` while the production Docker
image does not.

---

## Nits (non-blocking)

### N-1: Story AC test names are not present — different names shipped

The story specifies these exact pytest node IDs in AC-2, AC-3, AC-5:

- `test_push_writes_pending_action`
- `test_pull_upserts_crm_contact`
- `test_push_is_idempotent`

The implementation ships `test_push_creates_pending_actions`,
`test_push_idempotent_hash`, and no `test_pull_upserts_crm_contact` in the
connector test file. The webhook route test does exercise a pull+upsert path
indirectly, but the named test for AC-3 is absent and the named test for AC-5
is renamed.

The Tester will run the story AC node IDs verbatim and hit `ERROR: not found`.
Recommend adding thin wrapper tests with the story names, or renaming the
existing tests. This does not block architecture review (the behaviour is
tested) but will cause the tester's acceptance run to fail on exact names, so
it is flagged here to avoid a return loop from the tester.

### N-2: `datetime.utcnow()` deprecation acknowledged but left unresolved

impl-notes notes the deprecation. Python 3.12 emits `DeprecationWarning`;
Python 3.14 will make this a `RuntimeError`. The design itself used
`utcnow()`, so the engineer correctly deferred it. The fix
(`datetime.now(timezone.utc)`) is a one-line change — recommend doing it in
this story rather than carrying the warning forward.

### N-3: `respx` version pinned higher than design requires

Design specifies `respx>=0.21`; implementation pins `>=0.23.1`. No objection
to using the newer version, but the uv.lock records 0.23.1 specifically.
Fine as-is; just noting it differs from the design spec.

### N-4: Webhook handler inserts a summary `pending_action` for inbound events

`hubspot_webhook` in `main.py` inserts a row into `core.pending_actions` with
`action_type='hubspot_contact_pull'` and `status='approved'` as an audit trail
for inbound webhook events. This was not in the design. The design says inbound
events auto-upsert `crm_contacts` and the approval policy for inbound rows is
DB-12's concern. The extra INSERT is harmless and arguably useful, but it is an
undocumented deviation. The impl-notes do not mention it. Worth noting so DB-12
does not get confused by rows it did not create.

---

## Overall verdict

BLOCKED on B-1. `respx` must move to a dev-only dependency group before this
story advances to the tester. All structural and boundary requirements are
otherwise satisfied.

---

## Re-review — loop 2

Reviewer: architect
Date: 2026-11-26

### B-1: `respx` placement — RESOLVED

`pyproject.toml` diff (line +614 in the diff):

```
+    "respx>=0.23.1",
```

This line appears inside `[dependency-groups] dev`, not under `[project.dependencies]`.
The surrounding context confirms: the hunk header is `@@ -35,6 +35,7 @@ dev = [` and the
neighbours are `pytest`, `ruff`, and `uvicorn` — all dev dependencies. The production
dependency list is not touched.

`uv.lock` corroborates: `respx` appears only under the `dev` extras stanzas
(`dev = [ ... { name = "respx" } ...]`), not in the default resolution set.

B-1 is RESOLVED.

### N-1: Story AC pytest node IDs — RESOLVED

All four node IDs required by the story now exist in
`tests/unit/db06/test_hubspot_connector.py`:

- `test_push_writes_pending_action` — present (line 942 of diff)
- `test_pull_upserts_crm_contact` — present (line 954 of diff)
- `test_push_is_idempotent` — present (line 967 of diff)
- `test_health_check` — present (line 977 of diff)

All four are concrete test functions, not aliases. N-1 is RESOLVED.

### No new findings

No new blocking or nit-level issues were introduced by the fixes. The previously
noted nits N-2, N-3, N-4 remain as recorded (non-blocking; no change in status).

### Overall verdict — loop 2

APPROVED. No blocking findings remain. Story may advance to the tester.
