# DB-06: Connector interface + HubSpot two-way sync

**Status:** done · **Plan day:** 4 · **Posting lines covered:** CRM, email, calendar, phone, messaging

## Story

As an **acquisitions rep** managing DealBrain contacts in HubSpot, I want property owner
contacts pushed to HubSpot automatically and any edits I make in HubSpot reflected back
in Postgres, so that I never have to manually reconcile two systems.

## Acceptance criteria

1. `BaseConnector` abstract class exists in `pipelines/connectors/base.py` and declares
   at least `push(records)`, `pull_changes(since)`, and `health_check()` as abstract
   methods. Running `python -c "from pipelines.connectors.base import BaseConnector"` exits
   0. `HubSpotConnector` inherits from it; instantiating `BaseConnector` directly raises
   `TypeError`.

2. `HubSpotConnector.push()` reads from `core.properties` owners and writes a row to
   `pending_actions` with `action_type = 'hubspot_contact_upsert'` and `payload` containing
   the contact fields. It does NOT call the HubSpot API directly. Running
   `pytest tests/unit/test_hubspot_connector.py::test_push_writes_pending_action -v`
   passes with 0 live network calls (verified via `responses` or `unittest.mock`).

3. A fixture test simulates a HubSpot webhook delivering a contact-updated event (mocked
   JSON payload, no live API key). `HubSpotConnector.pull_changes()` parses the payload and
   upserts a row into the `crm_contacts` table. Running
   `pytest tests/unit/test_hubspot_connector.py::test_pull_upserts_crm_contact -v`
   passes and prints the upserted row's `hubspot_id`.

4. `crm_contacts` migration exists under `db/migrations/` and runs cleanly against the
   local pgvector container. The table has at minimum: `hubspot_id`, `dealbrain_property_id`
   (FK to `core.properties`), `first_name`, `last_name`, `email`, `phone`, `last_synced_at`,
   `raw_payload` (jsonb). Running `make db-migrate` exits 0 on a fresh schema.

5. A second push of the same owner produces exactly 1 `pending_actions` row (upsert, not
   duplicate insert). Running
   `pytest tests/unit/test_hubspot_connector.py::test_push_is_idempotent -v`
   passes and asserts `SELECT COUNT(*) FROM pending_actions` returns 1 after two calls.

6. `make lint test` passes in CI against the pgvector container with no live HubSpot
   credentials present (the `HUBSPOT_API_KEY` env var is absent). The test suite uses only
   fixture payloads from `tests/fixtures/hubspot/`.

7. `HubSpotConnector.health_check()` returns `{"status": "ok", "connector": "hubspot"}`
   when the API key env var is set to any non-empty string, and
   `{"status": "degraded", "reason": "missing credentials"}` when it is absent. Running
   `pytest tests/unit/test_hubspot_connector.py::test_health_check -v` passes for both
   cases.

## Demo line

Show the Loom: a synthetic owner from `core.properties` appears as a new contact in a
mocked HubSpot response, then a fixture webhook fires and the updated phone number is
visible in `SELECT * FROM crm_contacts` — no real HubSpot account required.

## Out of scope

- Live HubSpot API calls or OAuth flow (no real credentials in CI)
- Syncing deal or company objects (contacts only for this story)
- Webhooks received over a live HTTPS endpoint (fixture payloads only)
- Outbound SMS or email triggered by sync events (DB-07)
- Approval-portal UI for reviewing `pending_actions` rows (DB-12)
- Other CRM connectors (Salesforce, Pipedrive)

## Open questions for Architect

- Should `crm_contacts` live in the `core` schema alongside `core.properties`, or in its
  own `crm` schema? Affects migration ordering and FK references.
- `pending_actions` already exists (or will after DB-10 — confirm whether DB-06 should
  create it, or assume it exists and add a FK constraint only).
- Preferred webhook-verification strategy for HubSpot: client secret HMAC header or
  OAuth token introspection? Affects the fixture test contract.
- Does `BaseConnector` belong in `pipelines/connectors/` or should it be a shared library
  under a top-level `connectors/` package so `apps/mcp` can import it without depending
  on `pipelines`?

---

## Amendment (2026-11-27, from the human): live HubSpot test account is available

A HubSpot developer account and a **developer test account** now exist. Credentials are in the
local `.env` only (never commit them, never print them in logs or reports):

- `HUBSPOT_ACCESS_TOKEN`: access token for the DealBrain app installed in the test account
- `HUBSPOT_PORTAL_ID`: the test account's ID
- The HubSpot CLI is signed in on this Mac (`hs accounts list`)

**Corrections**
- Replace every mention of `HUBSPOT_API_KEY` with `HUBSPOT_ACCESS_TOKEN`. HubSpot API keys were
  retired; calls use `Authorization: Bearer <access token>`.
- HubSpot legacy private apps can no longer be created (sunset 2026-10-26). Any new app is a
  developer platform app created with the HubSpot CLI (`hs project ...`). Don't design around
  "create a private app in settings".
- Fixture-only tests stay, so CI runs without credentials (AC-6). They are **not enough on
  their own** to accept this story.

**Additional acceptance criteria (live, run on this Mac against the test account)**

8. `make hubspot-health` calls a real read endpoint (e.g. `GET /crm/v3/objects/contacts?limit=1`)
   and prints `{"status": "ok", "connector": "hubspot"}`. With a wrong token it prints
   `degraded` with the HTTP status, not a crash. (AC-7's "any non-empty string = ok" is
   replaced by this real check.)
9. Approving one `hubspot_contact_upsert` row in `pending_actions` (via a `make` target or a
   script standing in for the portal approve handler) creates or updates exactly **1** contact
   in the test account. Approving the same row again doesn't create a duplicate (match on
   email or a `dealbrain_id` custom property). Evidence: the HubSpot contact ID and a
   `GET` of that contact.
10. An edit made in HubSpot to that contact (change `phone`) appears in `crm_contacts` after
    `make hubspot-pull`, with `last_synced_at` updated. Evidence: the row before and after.
11. Only **synthetic** contacts (e.g. `test+db06-001@example.com`) are ever sent. Real OPA owner
    names never leave Postgres. A unit test asserts that `push()` refuses a record without the
    synthetic marker.

**Tester rule for this story:** SKIPPED counts as FAIL. Credentials and Docker are available on
this Mac, so ACs 4 and 8–11 must actually run. If one truly can't run, set the story to
`blocked: <reason>`. Don't mark it done.
