"""Tests for BaseConnector ABC and PendingAction dataclass."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from pipelines.connectors.base import BaseConnector, PendingAction


def test_pending_action_dataclass() -> None:
    action = PendingAction(
        connector="hubspot",
        action_type="hubspot_contact_upsert",
        payload={"key": "value"},
    )
    assert action.connector == "hubspot"
    assert action.action_type == "hubspot_contact_upsert"
    assert action.payload == {"key": "value"}
    assert action.status == "pending"
    assert isinstance(action.id, uuid.UUID)
    assert isinstance(action.created_at, datetime)
    assert action.approved_at is None
    assert action.sent_at is None


def test_base_connector_is_abstract() -> None:
    with pytest.raises(TypeError):
        BaseConnector()  # type: ignore[abstract]
