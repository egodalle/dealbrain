"""Unit tests for HubSpotConnector — no live network calls."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from pipelines.connectors.base import PendingAction
from pipelines.connectors.hubspot import HubSpotConnector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RECORD_A = {"parcel_id": "PAR-001", "owner": "Alice Smith"}
RECORD_B = {"parcel_id": "PAR-002", "owner": "Bob Jones"}


def _make_mock_conn() -> MagicMock:
    conn = MagicMock()
    conn.execute.return_value = conn
    conn.fetchone.return_value = None
    return conn


# ---------------------------------------------------------------------------
# push() tests
# ---------------------------------------------------------------------------


def test_push_creates_pending_actions() -> None:
    """push() returns one PendingAction per record and writes to DB; no HTTP calls."""
    connector = HubSpotConnector()
    conn = _make_mock_conn()

    actions = connector.push([RECORD_A, RECORD_B], conn)

    assert len(actions) == 2
    assert all(isinstance(a, PendingAction) for a in actions)
    assert all(a.status == "pending" for a in actions)
    assert all(a.connector == "hubspot" for a in actions)
    assert all(a.action_type == "hubspot_contact_upsert" for a in actions)
    # DB execute was called once per record
    assert conn.execute.call_count == 2


def test_push_idempotent_hash() -> None:
    """The same record produces the same payload JSON regardless of push count."""
    connector = HubSpotConnector()
    conn1 = _make_mock_conn()
    conn2 = _make_mock_conn()

    [action1] = connector.push([RECORD_A], conn1)
    [action2] = connector.push([RECORD_A], conn2)

    # Both pushes serialize the same payload
    assert json.dumps(action1.payload, sort_keys=True) == json.dumps(
        action2.payload, sort_keys=True
    )


# ---------------------------------------------------------------------------
# pull_changes() tests
# ---------------------------------------------------------------------------

CONTACTS_URL = "https://api.hubapi.com/crm/v3/objects/contacts"


@respx.mock
def test_pull_changes_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """pull_changes() returns a list of contact dicts from HubSpot."""
    monkeypatch.setenv("HUBSPOT_API_KEY", "test-key")

    respx.get(CONTACTS_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"id": "hs-001", "properties": {"firstname": "Alice"}},
                    {"id": "hs-002", "properties": {"firstname": "Bob"}},
                ],
                "paging": {},
            },
        )
    )

    connector = HubSpotConnector()
    results = connector.pull_changes()

    assert len(results) == 2
    assert results[0]["id"] == "hs-001"
    assert results[1]["id"] == "hs-002"


@respx.mock
def test_pull_changes_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    """pull_changes() follows paging.next.after and returns combined results."""
    monkeypatch.setenv("HUBSPOT_API_KEY", "test-key")

    # First page returns a cursor; second page has no cursor
    respx.get(CONTACTS_URL, params__contains={"limit": "100"}).mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "results": [{"id": "hs-001", "properties": {}}],
                    "paging": {"next": {"after": "cursor-abc"}},
                },
            ),
            httpx.Response(
                200,
                json={
                    "results": [{"id": "hs-002", "properties": {}}],
                    "paging": {},
                },
            ),
        ]
    )

    connector = HubSpotConnector()
    results = connector.pull_changes()

    assert len(results) == 2
    assert {r["id"] for r in results} == {"hs-001", "hs-002"}


def test_pull_changes_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """pull_changes() raises RuntimeError when HUBSPOT_API_KEY is absent."""
    monkeypatch.delenv("HUBSPOT_API_KEY", raising=False)
    connector = HubSpotConnector()
    with pytest.raises(RuntimeError, match="HUBSPOT_API_KEY not set"):
        connector.pull_changes()


# ---------------------------------------------------------------------------
# verify_webhook_signature() tests
# ---------------------------------------------------------------------------


def test_webhook_signature_valid() -> None:
    secret = "super-secret"
    payload = b'{"test": true}'
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    connector = HubSpotConnector(client_secret=secret)
    assert connector.verify_webhook_signature(payload, sig) is True


def test_webhook_signature_invalid() -> None:
    connector = HubSpotConnector(client_secret="correct-secret")
    assert connector.verify_webhook_signature(b"body", "badsig") is False


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


def test_health_check_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUBSPOT_API_KEY", "any-non-empty")
    connector = HubSpotConnector()
    result = connector.health_check()
    assert result == {"status": "ok", "connector": "hubspot"}


def test_health_check_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HUBSPOT_API_KEY", raising=False)
    connector = HubSpotConnector()
    result = connector.health_check()
    assert result["status"] == "degraded"
    assert "missing credentials" in result["reason"]
