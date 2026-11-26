"""Unit tests for pipelines/base.py — no live DB, no live network."""

from __future__ import annotations

import json
from dataclasses import field
from pathlib import Path
from typing import Any

import httpx
import pytest

from pipelines.base import BasePipeline
from pipelines.opa import require_parcel_id

FIXTURES = Path(__file__).parent.parent / "fixtures" / "db03"

_STUB_URL = "https://stub.example.com/resource/stub.json"


# ---------------------------------------------------------------------------
# Minimal concrete subclass for testing BasePipeline directly
# ---------------------------------------------------------------------------


class _StubPipeline(BasePipeline):
    dataset: str = field(default="stub")
    source_url: str = field(default=_STUB_URL)
    source_id_field: str = field(default="parcel_number")
    raw_table: str = field(default="raw.opa_assessments")
    staging_table: str = field(default="staging.opa_properties")

    def upsert_staging(self, conn: Any, raw_ids: list[int]) -> int:
        return 0

    def upsert_core(self, conn: Any) -> int:
        return 0


def _stub() -> _StubPipeline:
    """Return a stub pipeline with correct defaults."""
    return _StubPipeline(
        dataset="stub",
        source_url=_STUB_URL,
        source_id_field="parcel_number",
        raw_table="raw.opa_assessments",
        staging_table="staging.opa_properties",
    )


def _stub_with_transport(transport: httpx.MockTransport) -> _StubPipeline:
    return _StubPipeline(
        dataset="stub",
        source_url=_STUB_URL,
        source_id_field="parcel_number",
        raw_table="raw.opa_assessments",
        staging_table="staging.opa_properties",
        http_client=httpx.Client(transport=transport),
    )


# ---------------------------------------------------------------------------
# Hash tests
# ---------------------------------------------------------------------------


def test_compute_hash_deterministic() -> None:
    """The same dict always produces the same SHA-256 hex string."""
    record = {"parcel_number": "001000000", "market_value": "250000", "owner": "TEST"}
    pipeline = _stub()
    h1 = pipeline.compute_hash(record)
    h2 = pipeline.compute_hash(record)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_compute_hash_different() -> None:
    """Different dicts produce different hashes."""
    pipeline = _stub()
    r1 = {"parcel_number": "001000000", "market_value": "250000"}
    r2 = {"parcel_number": "001000000", "market_value": "250001"}
    assert pipeline.compute_hash(r1) != pipeline.compute_hash(r2)


def test_compute_hash_key_order_independent() -> None:
    """Hash is the same regardless of key insertion order."""
    pipeline = _stub()
    r1 = {"a": 1, "b": 2, "c": 3}
    r2 = {"c": 3, "a": 1, "b": 2}
    assert pipeline.compute_hash(r1) == pipeline.compute_hash(r2)


# ---------------------------------------------------------------------------
# Idempotency fixture test (httpx MockTransport, in-memory mock)
# ---------------------------------------------------------------------------


def _make_transport(pages: list[list[dict[str, Any]]]) -> httpx.MockTransport:
    """Return a MockTransport that serves pages in sequence, then empty."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        idx = call_count
        call_count += 1
        if idx < len(pages):
            return httpx.Response(200, json=pages[idx])
        return httpx.Response(200, json=[])

    return httpx.MockTransport(handler)


def test_idempotency_fixture() -> None:
    """
    Two identical API responses: first call rows_inserted > 0, second rows_inserted == 0.
    Uses httpx MockTransport; DB interactions are mocked.
    """
    page = json.loads((FIXTURES / "opa_page1.json").read_text())

    pipeline = _stub_with_transport(_make_transport([page]))

    inserted_set: set[tuple[str, str]] = set()

    def mock_upsert_raw(
        conn: Any,
        table: str,
        source_id: str,
        row_hash: str,
        payload: dict[str, Any],
        run_id: str,
    ) -> bool:
        key = (source_id, row_hash)
        if key in inserted_set:
            return False
        inserted_set.add(key)
        return True

    # First call — all 5 records inserted
    rows_inserted_first = 0
    for record in page:
        rh = pipeline.compute_hash(record)
        sid = str(record[pipeline.source_id_field])
        result = mock_upsert_raw(None, pipeline.raw_table, sid, rh, record, "run-1")
        if result:
            rows_inserted_first += 1

    assert rows_inserted_first > 0, "First pass should insert rows"

    # Second call — identical page, nothing new
    rows_inserted_second = 0
    for record in page:
        rh = pipeline.compute_hash(record)
        sid = str(record[pipeline.source_id_field])
        result = mock_upsert_raw(None, pipeline.raw_table, sid, rh, record, "run-2")
        if result:
            rows_inserted_second += 1

    assert rows_inserted_second == 0, "Second identical pass must insert 0 rows"


def test_changed_row_fixture() -> None:
    """
    First pass inserts 5 records; second pass sends same records with one field changed
    — exactly 1 new raw row should be inserted.
    """
    page_original = json.loads((FIXTURES / "opa_page1.json").read_text())
    page_changed = json.loads((FIXTURES / "opa_page1_changed.json").read_text())

    pipeline = _stub()
    inserted_set: set[tuple[str, str]] = set()

    def mock_upsert_raw(source_id: str, row_hash: str) -> bool:
        key = (source_id, row_hash)
        if key in inserted_set:
            return False
        inserted_set.add(key)
        return True

    # First pass with original data
    for record in page_original:
        rh = pipeline.compute_hash(record)
        sid = str(record[pipeline.source_id_field])
        mock_upsert_raw(sid, rh)

    # Second pass with changed data
    rows_inserted_second = 0
    for record in page_changed:
        rh = pipeline.compute_hash(record)
        sid = str(record[pipeline.source_id_field])
        if mock_upsert_raw(sid, rh):
            rows_inserted_second += 1

    assert rows_inserted_second == 1, (
        f"Expected exactly 1 new raw row for the changed record, got {rows_inserted_second}"
    )


# ---------------------------------------------------------------------------
# fetch_pages test with MockTransport
# ---------------------------------------------------------------------------


def test_fetch_pages_paginates() -> None:
    """fetch_pages yields all pages and stops when a short page is received."""
    page1 = [{"parcel_number": f"P{i:04d}", "value": str(i)} for i in range(5)]
    page2 = [{"parcel_number": f"P{i:04d}", "value": str(i)} for i in range(5, 8)]

    pipeline = _stub_with_transport(_make_transport([page1, page2]))

    all_records: list[dict[str, Any]] = []
    for page in pipeline.fetch_pages(limit=5):
        all_records.extend(page)

    assert len(all_records) == 8  # 5 + 3 (second page shorter than limit → stop)


def test_fetch_pages_stops_on_empty() -> None:
    """fetch_pages stops immediately when the first page is empty."""
    pipeline = _stub_with_transport(_make_transport([[]]))
    pages = list(pipeline.fetch_pages())
    assert pages == []


# ---------------------------------------------------------------------------
# Null parcel_id rejection (AC-6)
# ---------------------------------------------------------------------------


def test_null_parcel_id_rejected() -> None:
    """require_parcel_id raises ValueError for None or empty string."""
    with pytest.raises(ValueError, match="parcel_number must not be null"):
        require_parcel_id(None)

    with pytest.raises(ValueError, match="parcel_number must not be null"):
        require_parcel_id("")

    with pytest.raises(ValueError, match="parcel_number must not be null"):
        require_parcel_id("   ")


def test_valid_parcel_id_passes() -> None:
    """require_parcel_id returns the string for a non-empty value."""
    assert require_parcel_id("001000000") == "001000000"
    assert require_parcel_id(123) == "123"
