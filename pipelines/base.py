"""Base pipeline: shared fetch, hash, raw upsert, and log logic for Philly open-data sources.

Data comes from the City of Philadelphia's Carto SQL API (phl.carto.com/api/v2/sql).
Each pipeline names a Carto table, the columns to keep, and a WHERE clause; the base
class pages through it with ORDER BY cartodb_id LIMIT/OFFSET.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx
import psycopg

logger = logging.getLogger(__name__)

PAGE_SIZE = 2000
_RETRY_DELAYS = (3.0, 10.0, 30.0, 60.0)
# Carto answers HTTP 400 for some temporary conditions; these are worth retrying.
_TRANSIENT_CARTO_ERRORS = ("query_wait_timeout", "over platform's limits")

CARTO_SQL_URL = "https://phl.carto.com/api/v2/sql"
_ZIP_RE = re.compile(r"^\d{5}$")


def request_gap() -> float:
    """Seconds to pause between Carto requests (CARTO_REQUEST_GAP, default 0.2)."""
    return float(os.environ.get("CARTO_REQUEST_GAP", "0.2"))


def carto_url() -> str:
    return os.environ.get("CARTO_SQL_URL", CARTO_SQL_URL)


def philly_zips() -> list[str]:
    """ZIP codes to ingest, from PHILLY_ZIPS (comma-separated, default 19134)."""
    raw = os.environ.get("PHILLY_ZIPS", "19134")
    zips = [z.strip() for z in raw.split(",") if z.strip()]
    bad = [z for z in zips if not _ZIP_RE.match(z)]
    if not zips or bad:
        raise ValueError(f"PHILLY_ZIPS must be 5-digit ZIP codes, got {raw!r}")
    return zips


def philly_since() -> str:
    """Earliest event date for violations/transfers, from PHILLY_SINCE (default 2023-01-01)."""
    raw = os.environ.get("PHILLY_SINCE", "2023-01-01")
    return date.fromisoformat(raw).isoformat()  # raises ValueError if not YYYY-MM-DD


def sql_in(values: list[str]) -> str:
    """Render validated values as a SQL IN list. Callers must validate values first."""
    return ", ".join(f"'{v}'" for v in values)


class SourceHTTPError(RuntimeError):
    """A non-retryable HTTP error from the data source (4xx other than 429)."""


@dataclass
class IngestResult:
    run_id: str
    dataset: str
    rows_fetched: int
    rows_inserted: int
    rows_updated_staging: int
    rows_updated_core: int
    elapsed_seconds: float
    skipped: bool = False
    error: str | None = None


@dataclass
class BasePipeline:
    dataset: str = ""
    source_url: str = field(default_factory=carto_url)
    carto_table: str = ""
    carto_columns: tuple[str, ...] = ()
    source_id_field: str = ""
    raw_table: str = ""
    staging_table: str = ""
    http_client: httpx.Client = field(default_factory=httpx.Client, repr=False)

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    def carto_where(self) -> str:
        """WHERE clause for the Carto query. Subclasses narrow it (ZIPs, dates)."""
        return "TRUE"

    def prepare(self, conn: psycopg.Connection[Any]) -> None:
        """Hook run before fetching, with DB access. Default: nothing."""
        return None

    def build_query(self, limit: int, offset: int) -> str:
        cols = ", ".join(self.carto_columns) if self.carto_columns else "*"
        return (
            f"SELECT {cols} FROM {self.carto_table} WHERE {self.carto_where()} "  # noqa: S608
            f"ORDER BY cartodb_id LIMIT {int(limit)} OFFSET {int(offset)}"
        )

    def fetch_pages(
        self, offset: int = 0, limit: int = PAGE_SIZE
    ) -> Iterator[list[dict[str, Any]]]:
        """Page through the Carto table, yielding one list[dict] per page."""
        headers: dict[str, str] = {}

        while True:
            params = {"q": self.build_query(limit, offset), "format": "json"}
            page = self._get_with_retry(params, headers)
            if not page:
                break
            yield page
            if len(page) < limit:
                break
            offset += limit
            time.sleep(request_gap())

    def _get_with_retry(
        self,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> list[dict[str, Any]]:
        last_exc: Exception | None = None
        for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
            try:
                resp = self.http_client.get(
                    self.source_url,
                    params=params,
                    headers=headers,
                    timeout=60.0,
                )
                if resp.status_code == 400 and any(m in resp.text for m in _TRANSIENT_CARTO_ERRORS):
                    raise RuntimeError(f"Carto busy (HTTP 400): {resp.text[:200]}")
                if 400 <= resp.status_code < 500 and resp.status_code != 429:
                    # Client errors won't fix themselves: fail fast with the body for diagnosis.
                    raise SourceHTTPError(
                        f"HTTP {resp.status_code} from {self.source_url}: {resp.text[:300]}"
                    )
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict):
                    if "error" in data:
                        raise SourceHTTPError(f"Carto error: {data['error']}")
                    rows: list[dict[str, Any]] = data.get("rows", [])
                    return rows
                result: list[dict[str, Any]] = data
                return result
            except SourceHTTPError:
                raise
            except Exception as exc:
                last_exc = exc
                if delay is not None:
                    logger.warning("Attempt %d failed (%s); retrying in %ss", attempt, exc, delay)
                    time.sleep(delay)
        raise RuntimeError(f"All retries exhausted for {self.source_url}") from last_exc

    # ------------------------------------------------------------------
    # Hash
    # ------------------------------------------------------------------

    def compute_hash(self, record: dict[str, Any]) -> str:
        """SHA-256 of the JSON-serialised record with sorted keys."""
        serialised = json.dumps(record, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialised.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Raw upsert
    # ------------------------------------------------------------------

    def upsert_raw(
        self,
        conn: psycopg.Connection[Any],
        table: str,
        source_id: str,
        row_hash: str,
        payload: dict[str, Any],
        run_id: str,
    ) -> bool:
        """INSERT ... ON CONFLICT DO NOTHING.  Returns True if the row was inserted."""
        result = conn.execute(
            f"""
            INSERT INTO {table} (source_id, row_hash, payload, run_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (source_id, row_hash) DO NOTHING
            RETURNING id
            """,  # noqa: S608
            (source_id, row_hash, json.dumps(payload), run_id),
        )
        return result.fetchone() is not None

    # ------------------------------------------------------------------
    # Ingest log
    # ------------------------------------------------------------------

    def log_run(
        self,
        conn: psycopg.Connection[Any],
        dataset: str,
        rows_fetched: int,
        rows_inserted: int,
        run_id: str | None = None,
        error: str | None = None,
    ) -> str:
        """Write (or update) a row in raw.ingest_log. Returns the run_id."""
        if run_id is None:
            row = conn.execute(
                """
                INSERT INTO raw.ingest_log (dataset, rows_fetched, rows_inserted, status, error,
                                            finished_at)
                VALUES (%s, %s, %s, %s, %s, now())
                RETURNING run_id
                """,
                (dataset, rows_fetched, rows_inserted, "done" if error is None else "error", error),
            ).fetchone()
            assert row is not None
            return str(row[0])
        conn.execute(
            """
            UPDATE raw.ingest_log
            SET rows_fetched = %s,
                rows_inserted = %s,
                status = %s,
                error = %s,
                finished_at = now()
            WHERE run_id = %s::uuid
            """,
            (rows_fetched, rows_inserted, "done" if error is None else "error", error, run_id),
        )
        return run_id

    # ------------------------------------------------------------------
    # Subclass hooks
    # ------------------------------------------------------------------

    def upsert_staging(
        self, conn: psycopg.Connection[Any], raw_ids: list[int]
    ) -> int:  # pragma: no cover
        raise NotImplementedError

    def upsert_core(self, conn: psycopg.Connection[Any]) -> int:  # pragma: no cover
        raise NotImplementedError

    # ------------------------------------------------------------------
    # run
    # ------------------------------------------------------------------

    def pending_raw_ids(self, conn: psycopg.Connection[Any]) -> list[int]:
        """Raw rows not yet applied to staging (their hash is in neither staging nor history).

        Staging catches up from raw on every run, so rows saved by an earlier run that failed
        before staging are not stranded. Ordered by id so older versions apply first.
        """
        rows = conn.execute(
            f"""
            SELECT r.id FROM {self.raw_table} r
            WHERE NOT EXISTS (SELECT 1 FROM {self.staging_table} s WHERE s.row_hash = r.row_hash)
              AND NOT EXISTS (
                  SELECT 1 FROM {self.staging_table}_history h WHERE h.row_hash = r.row_hash
              )
            ORDER BY r.id
            """  # noqa: S608
        ).fetchall()
        return [int(r[0]) for r in rows]

    def run(self, conn: psycopg.Connection[Any], dry_run: bool = False) -> IngestResult:
        t0 = time.monotonic()

        log_row = conn.execute(
            "INSERT INTO raw.ingest_log (dataset) VALUES (%s) RETURNING run_id",
            (self.dataset,),
        ).fetchone()
        assert log_row is not None
        run_id = str(log_row[0])
        conn.commit()

        rows_fetched = 0
        rows_inserted = 0
        rows_staged = 0
        skipped = False
        errors: list[str] = []

        # 1. Fetch into raw. Each page is committed, so a later failure keeps earlier pages.
        try:
            self.prepare(conn)
            for page in self.fetch_pages():
                rows_fetched += len(page)
                if dry_run:
                    continue
                for record in page:
                    sid = record.get(self.source_id_field)
                    if sid is None or str(sid).strip() == "":
                        logger.warning(
                            "[%s] record missing source_id field '%s' — skipping",
                            self.dataset,
                            self.source_id_field,
                        )
                        continue
                    row_hash = self.compute_hash(record)
                    if self.upsert_raw(conn, self.raw_table, str(sid), row_hash, record, run_id):
                        rows_inserted += 1
                conn.commit()
                logger.info(
                    "[%s] fetched %d rows (%d new so far)",
                    self.dataset,
                    rows_fetched,
                    rows_inserted,
                )
        except Exception as exc:
            errors.append(f"fetch: {exc}")
            logger.error("[%s] fetch error: %s", self.dataset, exc)
            try:
                conn.rollback()
            except Exception:
                pass

        # 2. Apply everything in raw that staging hasn't seen yet, even if the fetch failed.
        if dry_run:
            logger.info("[%s] dry-run: fetched %d rows, no writes", self.dataset, rows_fetched)
            skipped = True
        else:
            try:
                pending = self.pending_raw_ids(conn)
                if not pending:
                    logger.info("[%s] No new rows — skipped staging upsert", self.dataset)
                    skipped = True
                else:
                    rows_staged = self.upsert_staging(conn, pending)
                    self.upsert_core(conn)
                    conn.commit()
                    logger.info("[%s] staged %d rows", self.dataset, rows_staged)
            except Exception as exc:
                errors.append(f"staging: {exc}")
                logger.error("[%s] staging error: %s", self.dataset, exc)
                try:
                    conn.rollback()
                except Exception:
                    pass

        error_msg = "; ".join(errors) if errors else None
        self.log_run(
            conn, self.dataset, rows_fetched, rows_inserted, run_id=run_id, error=error_msg
        )
        conn.commit()

        return IngestResult(
            run_id=run_id,
            dataset=self.dataset,
            rows_fetched=rows_fetched,
            rows_inserted=rows_inserted,
            rows_updated_staging=rows_staged,
            rows_updated_core=0,
            elapsed_seconds=time.monotonic() - t0,
            skipped=skipped,
            error=error_msg,
        )
