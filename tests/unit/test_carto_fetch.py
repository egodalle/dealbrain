"""Unit tests for the Carto fetch layer: query shape, response parsing, retry policy."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from pipelines.base import BasePipeline, SourceHTTPError, philly_since, philly_zips
from pipelines.opa import OPAPipeline
from pipelines.transfers import TransfersPipeline
from pipelines.violations import ViolationsPipeline


def _client(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_carto_rows_envelope_is_unwrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rows": [{"parcel_number": "1"}], "total_rows": 1})

    p = OPAPipeline(http_client=_client(handler))
    assert list(p.fetch_pages()) == [[{"parcel_number": "1"}]]


def test_query_selects_columns_and_filters_zip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHILLY_ZIPS", "19134,19140")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["q"])
        return httpx.Response(200, json={"rows": []})

    list(OPAPipeline(http_client=_client(handler)).fetch_pages())
    q = seen[0]
    assert q.startswith("SELECT parcel_number, location")
    assert "FROM opa_properties_public" in q
    assert "left(zip_code, 5) IN ('19134', '19140')" in q
    assert "ORDER BY cartodb_id LIMIT" in q


def test_violations_and_transfers_filter_by_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHILLY_SINCE", "2024-06-01")
    v = ViolationsPipeline().build_query(10, 0)
    tp = TransfersPipeline()
    tp.current_chunk = ["881234500"]
    t = tp.build_query(10, 0)
    assert "violationdate >= '2024-06-01'" in v
    assert "display_date >= '2024-06-01'" in t
    assert "ILIKE '%DEED%'" in t


def test_403_fails_fast_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(403, text="forbidden")

    monkeypatch.setattr("pipelines.base.time.sleep", lambda s: None)
    p = BasePipeline(carto_table="x", http_client=_client(handler))
    with pytest.raises(SourceHTTPError, match="HTTP 403"):
        list(p.fetch_pages())
    assert calls == 1


def test_carto_error_body_fails_fast() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": ['column "nope" does not exist']})

    p = BasePipeline(carto_table="x", http_client=_client(handler))
    with pytest.raises(SourceHTTPError, match="nope"):
        list(p.fetch_pages())


def test_429_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [httpx.Response(429), httpx.Response(200, json={"rows": []})]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    monkeypatch.setattr("pipelines.base.time.sleep", lambda s: None)
    p = BasePipeline(carto_table="x", http_client=_client(handler))
    assert list(p.fetch_pages()) == []
    assert responses == []


@pytest.mark.parametrize("bad", ["1913", "19134; DROP TABLE x", ""])
def test_bad_zip_rejected(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("PHILLY_ZIPS", bad)
    with pytest.raises(ValueError):
        philly_zips()


def test_bad_since_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHILLY_SINCE", "2024-13-01' OR 1=1")
    with pytest.raises(ValueError):
        philly_since()


def test_transfers_queries_by_parcel_in_chunks() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["q"])
        return httpx.Response(200, json={"rows": []})

    tp = TransfersPipeline(http_client=_client(handler))
    tp.parcel_ids = [f"{n:09d}" for n in range(300)]
    list(tp.fetch_pages())
    assert len(seen) == 2
    assert "opa_account_num IN ('000000000'" in seen[0]
    assert "'000000299')" in seen[1]


def test_transfers_with_no_parcels_fetches_nothing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not call the API")

    assert list(TransfersPipeline(http_client=_client(handler)).fetch_pages()) == []


def test_query_wait_timeout_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        httpx.Response(400, json={"error": ["query_wait_timeout"]}),
        httpx.Response(200, json={"rows": []}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    monkeypatch.setattr("pipelines.base.time.sleep", lambda s: None)
    p = BasePipeline(carto_table="x", http_client=_client(handler))
    assert list(p.fetch_pages()) == []
    assert responses == []


class _FakeResult:
    def __init__(self, row: Any = None) -> None:
        self._row = row

    def fetchone(self) -> Any:
        return self._row


class _FakeConn:
    def execute(self, sql: str, params: Any = None) -> _FakeResult:
        return _FakeResult(("00000000-0000-0000-0000-000000000001",))

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


class _HalfFailingPipeline(BasePipeline):
    """Fetch yields one page, then fails — like Carto timing out mid-run."""

    staged_ids: list[int] = []

    def fetch_pages(self, offset: int = 0, limit: int = 0) -> Any:
        yield [{"id": "a"}, {"id": "b"}]
        raise RuntimeError("Carto busy")

    def upsert_raw(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def pending_raw_ids(self, conn: Any) -> list[int]:
        return [11, 12]

    def upsert_staging(self, conn: Any, raw_ids: list[int]) -> int:
        self.staged_ids = raw_ids
        return len(raw_ids)

    def upsert_core(self, conn: Any) -> int:
        return 0

    def log_run(self, *args: Any, **kwargs: Any) -> str:
        return "run"


def test_staging_catches_up_even_when_fetch_fails() -> None:
    p = _HalfFailingPipeline(dataset="t", source_id_field="id", raw_table="raw.t")
    result = p.run(_FakeConn())  # type: ignore[arg-type]
    assert result.rows_inserted == 2
    assert p.staged_ids == [11, 12], "raw rows from the failed run must still be staged"
    assert result.rows_updated_staging == 2
    assert result.error is not None and "fetch: Carto busy" in result.error
