---
owner: architect
last-reviewed: 2026-11-26
stability: stable
---

# ADR-0006: All outbound writes go through `pending_actions`, never directly to external APIs

## Context

DealBrain's agents, MCP tools, and pipelines can produce outbound side effects: creating
contacts in HubSpot, sending SMS via Twilio, sending email via Gmail. The system must
guarantee that no message is sent and no client-visible data is changed without a human
having explicitly approved the action.

The story flow introduces an approval boundary at DB-06 (HubSpot sync), which is the first
story that can produce an outbound write to a system outside Postgres. The pattern must be
established here and held for every subsequent connector (Twilio in DB-07, MCP outreach
in DB-10, full guardrail suite in DB-12).

The story also asks: should `pending_actions` be created by DB-06 or assumed to exist from
DB-10? The answer determines migration ordering.

## Decision

1. **`core.pending_actions` is created in migration 0015, owned by DB-06.** DB-10 and all
   later stories INSERT into this table but do not alter its schema. If a later story
   needs an additional column, it opens a new numbered migration.

2. **No connector, agent, MCP tool, or pipeline module may call an external write API
   directly.** The only permitted outbound write path is:

   ```
   connector.push() ──INSERT──► core.pending_actions (status=pending)
           ↓
   portal /approve handler ──► connector.apply_approved() ──► external API
   ```

   The portal approve handler is the sole code path that calls `apply_approved`. It is a
   human-operated surface, not an automated step.

3. **The MCP server's database role has INSERT on `core.pending_actions` and SELECT on
   read models only.** It has no UPDATE, DELETE, or access to `sent_at`. An agent that
   tries to call an external API directly would need a capability that does not exist in
   the system.

4. **`apply_approved` is a concrete method on each connector class, not an abstract
   method on `BaseConnector`.** `BaseConnector` only declares `push`, `pull_changes`,
   and `health_check`. This keeps the base class simple and avoids requiring every
   connector to implement an approval path before it needs one.

5. **Inbound webhook data (HubSpot pushing to us) is NOT subject to the approval gate.**
   It is a data import, not an outbound send. The connector upserts `core.crm_contacts`
   directly after HMAC verification. A `PendingAction` with `status='approved'` may be
   created for audit purposes, but no approval step is required.

## Consequences

Positive:
- The approval boundary is enforced architecturally, not by convention. There is no
  "send" capability to bypass.
- `pending_actions` is a full audit log of every intended outbound side effect, with
  timestamps for when it was created, approved, and sent.
- Connectors are independently testable: `push` never touches an external API, so unit
  tests run with zero live credentials.
- The guardrail suite (DB-12) can prove the invariant by asserting that no row in any
  external system exists unless a matching `pending_actions` row with `status='sent'` and
  a non-null `approved_at` exists.

Negative:
- Every new connector must implement `apply_approved` to be useful end-to-end. This is
  intentional friction, not a bug.
- Fully automated workflows (e.g., auto-send if score > 90) require an explicit override
  in the portal approve handler, not a flag on the connector. This keeps the boundary
  unambiguous.

## Alternatives rejected

**Call the external API directly in `push`, log to `pending_actions` after.** Rejected
because the log becomes ex-post-facto; a failure between the API call and the INSERT
leaves the external system modified with no record. The boundary disappears the moment an
agent can call `push` without a human in the loop.

**Use a separate `outbound_queue` table for sends and keep `pending_actions` for MCP
only.** Rejected because having two approval-gating tables creates inconsistency and
makes the guardrail suite harder to write. One table, one invariant.

**Store only approved rows in `pending_actions` (move `push` output to a separate
`proposed_actions` staging table).** Rejected as premature complexity. A `status` column
with a CHECK constraint is simpler and covers the same states without a second table.

**OAuth token introspection for HubSpot webhook verification.** Rejected because
introspection is an OAuth-only flow requiring a live token exchange. HMAC-SHA256 on the
request body (HubSpot Signature v3) works without a live OAuth session and is the method
recommended in HubSpot's documentation for all webhook consumers.
