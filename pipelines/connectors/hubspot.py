from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime
from typing import Any

import httpx

from pipelines.connectors.base import BaseConnector, PendingAction

_INSERT_PENDING_ACTION = """
INSERT INTO core.pending_actions (id, connector, action_type, payload, status, created_at)
VALUES (%s, %s, %s, %s::jsonb, %s, %s)
ON CONFLICT (connector, action_type, payload_hash)
WHERE status IN ('pending', 'approved')
DO NOTHING
RETURNING id
"""

_SELECT_PENDING_ACTION = """
SELECT id, connector, action_type, payload, status, created_at, approved_at, sent_at
FROM core.pending_actions
WHERE id = %s
"""

_UPDATE_SENT = """
UPDATE core.pending_actions
SET status = 'sent', sent_at = now()
WHERE id = %s
"""

_UPSERT_CRM_CONTACT = """
INSERT INTO core.crm_contacts
    (hubspot_id, first_name, last_name, email, phone, raw_payload, last_synced_at)
VALUES (%s, %s, %s, %s, %s, %s::jsonb, now())
ON CONFLICT (hubspot_id) DO UPDATE SET
    first_name     = EXCLUDED.first_name,
    last_name      = EXCLUDED.last_name,
    email          = EXCLUDED.email,
    phone          = EXCLUDED.phone,
    raw_payload    = EXCLUDED.raw_payload,
    last_synced_at = now(),
    updated_at     = now()
"""


class HubSpotConnector(BaseConnector):
    def __init__(
        self,
        api_key: str = "",
        client_secret: str = "",
        http_client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._client_secret = client_secret
        self._http = http_client or httpx.Client()

    def name(self) -> str:
        return "hubspot"

    def push(
        self,
        records: list[dict[str, Any]],
        conn: Any = None,
    ) -> list[PendingAction]:
        """Write pending_actions rows for each record. No HubSpot API call is made."""
        actions: list[PendingAction] = []
        for record in records:
            action = PendingAction(
                connector=self.name(),
                action_type="hubspot_contact_upsert",
                payload=record,
            )
            if conn is not None:
                conn.execute(
                    _INSERT_PENDING_ACTION,
                    (
                        str(action.id),
                        action.connector,
                        action.action_type,
                        json.dumps(record),
                        action.status,
                        action.created_at,
                    ),
                )
            actions.append(action)
        return actions

    def pull_changes(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Fetch contacts from HubSpot CRM API v3. Paginates automatically."""
        api_key = os.environ.get("HUBSPOT_API_KEY", "")
        if not api_key:
            raise RuntimeError("HUBSPOT_API_KEY not set")

        params: dict[str, Any] = {
            "limit": 100,
            "properties": "firstname,lastname,email,phone",
        }
        if since:
            params["updatedAfter"] = since.isoformat()

        results: list[dict[str, Any]] = []
        url: str | None = "https://api.hubapi.com/crm/v3/objects/contacts"

        while url:
            resp = self._http.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            results.extend(data.get("results", []))
            # Pagination: HubSpot returns paging.next.after cursor
            after = data.get("paging", {}).get("next", {}).get("after")
            if after:
                params = dict(params)
                params["after"] = after
            else:
                url = None

        return results

    def handle_webhook_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Parse a single HubSpot webhook event dict and return a contact dict for upsert.

        Pure function — no DB or HTTP calls.
        """
        hubspot_id = str(payload.get("objectId", ""))
        props = payload.get("properties", {})
        return {
            "hubspot_id": hubspot_id,
            "first_name": props.get("firstname"),
            "last_name": props.get("lastname"),
            "email": props.get("email"),
            "phone": props.get("phone"),
            "subscription_type": payload.get("subscriptionType"),
            "raw_payload": payload,
        }

    def handle_webhook_events(
        self,
        events: list[dict[str, Any]],
        conn: Any,
    ) -> None:
        """Upsert crm_contacts for each contact.propertyChange event."""
        for event in events:
            hubspot_id = str(event.get("objectId", ""))
            props = event.get("properties", {})
            conn.execute(
                _UPSERT_CRM_CONTACT,
                (
                    hubspot_id,
                    props.get("firstname"),
                    props.get("lastname"),
                    props.get("email"),
                    props.get("phone"),
                    json.dumps(event),
                ),
            )

    def apply_approved(
        self,
        pending_action_id: uuid.UUID,
        conn: Any,
    ) -> dict[str, Any]:
        """Mark a pending_action as sent. Full HubSpot API call is implemented in DB-12."""
        row = conn.execute(_SELECT_PENDING_ACTION, (str(pending_action_id),)).fetchone()
        if row is None:
            raise ValueError(f"pending_action {pending_action_id} not found")
        status = row[4]
        if status != "approved":
            raise ValueError(
                f"pending_action {pending_action_id} has status '{status}', expected 'approved'"
            )
        conn.execute(_UPDATE_SENT, (str(pending_action_id),))
        return {"id": str(pending_action_id), "status": "sent"}

    def verify_webhook_signature(self, payload_bytes: bytes, signature: str) -> bool:
        """Verify HubSpot HMAC-SHA256 signature against client_secret."""
        expected = hmac.new(
            self._client_secret.encode(),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def health_check(self) -> dict[str, str]:
        api_key = os.environ.get("HUBSPOT_API_KEY", "")
        if not api_key:
            return {"status": "degraded", "reason": "missing credentials"}
        return {"status": "ok", "connector": "hubspot"}
