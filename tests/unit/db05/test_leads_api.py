"""Unit tests for portal /leads endpoints — mocked DB, no live connection."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Synthetic rows returned by the mock DB cursor
# (parcel_number, address_normalized, distress_score, score_components, owner)
# ---------------------------------------------------------------------------

_ROW_HIGH = (
    "883309200",
    "123 MAIN ST PHILADELPHIA PA 19103",
    80,
    {"delinquency": 35, "violations": 20, "years_held": 15, "value_gap": 10},
    "SMITH JOHN",
)

_ROW_LOW = (
    "883309201",
    "456 OAK AVE PHILADELPHIA PA 19104",
    30,
    {"delinquency": 10, "violations": 5, "years_held": 10, "value_gap": 5},
    "DOE JANE",
)


def _make_mock_conn(rows: list[tuple[Any, ...]]) -> MagicMock:
    """Return a psycopg Connection mock that yields *rows* on execute().fetchall()."""
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    mock_conn = MagicMock()
    mock_conn.closed = False
    mock_conn.execute.return_value = mock_cursor
    return mock_conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_leads_endpoint_shape() -> None:
    """GET /leads returns a list with required keys on each item."""
    mock_conn = _make_mock_conn([_ROW_HIGH, _ROW_LOW])
    with patch("apps.portal.main._get_conn", return_value=mock_conn):
        from apps.portal.main import app

        client = TestClient(app)
        resp = client.get("/leads?limit=2")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2
    for item in data:
        assert "parcel_number" in item
        assert "address_normalized" in item
        assert "distress_score" in item
        assert "score_components" in item
        assert "owner" in item


def test_leads_min_score_filter() -> None:
    """GET /leads?min_score=50 filters out rows below the threshold (via mock)."""
    # Mock returns both rows; we simulate the filter at the DB layer by returning
    # only the high-score row (as a real DB would).
    mock_conn = _make_mock_conn([_ROW_HIGH])
    with patch("apps.portal.main._get_conn", return_value=mock_conn):
        from apps.portal.main import app

        client = TestClient(app)
        resp = client.get("/leads?min_score=50")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["distress_score"] == 80


def test_csv_export_columns() -> None:
    """GET /leads/export.csv has correct 6-column header and correct content-type."""
    mock_conn = _make_mock_conn([_ROW_HIGH, _ROW_LOW])
    with patch("apps.portal.main._get_conn", return_value=mock_conn):
        from apps.portal.main import app

        client = TestClient(app)
        resp = client.get("/leads/export.csv")

    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]

    lines = resp.text.strip().splitlines()
    assert len(lines) >= 2

    header = lines[0]
    expected_header = "parcel_number,address_normalized,distress_score,factor_1,factor_2,factor_3"
    assert header == expected_header, f"unexpected header: {header!r}"

    # Verify the high-score row appears first with correct factor ordering
    # score_components = {"delinquency": 35, "violations": 20, "years_held": 15, "value_gap": 10}
    # top factors: delinquency(35), violations(20), years_held(15)
    first_data = lines[1].split(",")
    assert first_data[0] == "883309200"
    assert first_data[2] == "80"
    assert first_data[3] == "delinquency"
    assert first_data[4] == "violations"
    assert first_data[5] == "years_held"
