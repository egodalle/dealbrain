"""FastAPI TestClient tests for POST /hubspot/webhook."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# We must patch _get_conn before importing the app so the portal doesn't try
# to open a real database connection during import-time module-level code.
_mock_conn: MagicMock = MagicMock()
_mock_conn.execute.return_value = _mock_conn
_mock_conn.fetchone.return_value = None
_mock_conn.closed = False


@pytest.fixture(autouse=True)
def _patch_conn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.portal.main._get_conn", lambda: _mock_conn)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("HUBSPOT_CLIENT_SECRET", "test-secret")
    from apps.portal.main import app

    return TestClient(app, raise_server_exceptions=False)


def _make_sig(secret: str, url: str, body: bytes, ts: str) -> str:
    message = f"POST{url}{body.decode()}{ts}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


EVENTS = [
    {
        "eventId": 1,
        "objectId": "hs-001",
        "subscriptionType": "contact.propertyChange",
        "properties": {"firstname": "Alice", "lastname": "Smith", "email": "", "phone": ""},
    }
]


def test_webhook_valid_signature(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps(EVENTS).encode()
    ts = "1700000000000"
    url = "http://testserver/hubspot/webhook"
    sig = _make_sig("test-secret", url, body, ts)

    resp = client.post(
        "/hubspot/webhook",
        content=body,
        headers={
            "X-HubSpot-Signature-v3": sig,
            "X-HubSpot-Request-Timestamp": ts,
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "queued"}


def test_webhook_invalid_signature(client: TestClient) -> None:
    body = json.dumps(EVENTS).encode()
    resp = client.post(
        "/hubspot/webhook",
        content=body,
        headers={
            "X-HubSpot-Signature-v3": "invalidsignature",
            "X-HubSpot-Request-Timestamp": "1700000000000",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 403
