"""Base pipeline: shared fetch, hash, raw upsert, and log logic for Philly open-data sources."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import psycopg

logger = logging.getLogger(__name__)

PAGE_SIZE = 1000
_RETRY_DELAYS = (2.0, 4.0, 8.0)


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
    socrata_url: str = ""
    source_id_field: str = ""
    raw_table: str = ""
    staging_table: str = ""
    app_token: str = ""
    http_client: httpx.Client = field(default_factory=httpx.Client, repr=False)

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    def fetch_pages(
        self, offset: int = 0, limit: int = PAGE_SIZE
    ) -> Iterator[list[dict[str, Any]]]:
        """Paginate the Socrata endpoint, yielding one list[dict] per page."""
        headers: dict[str, str] = {}
        if self.app_token:
            headers["X-App-Token"] = self.app_token

        while True:
            params = {"$limit": str(limit), "$offset": str(offset), "$order": ":id"}
            page = self._get_with_retry(params, headers)
            if not page:
                break
            yield page
            if len(page) < limit:
                break
            offset += limit

    def _get_with_retry(
        self,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> list[dict[str, Any]]:
        last_exc: Exception | None = None
        for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
            try:
                resp = self.http_client.get(
                    self.socrata_url,
                    params=params,
                    headers=headers,
                    timeout=30.0,
                )
                resp.raise_for_status()
                result: list[dict[str, Any]] = resp.json()
                return result
            except Exception as exc:
                last_exc = exc
                if delay is not None:
                    logger.warning("Attempt %d failed (%s); retrying in %ss", attempt, exc, delay)
                    time.sleep(delay)
        raise RuntimeError(f"All retries exhausted for {self.socrata_url}") from last_exc

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
        source: str,
        rows_fetched: int,
        rows_inserted: int,
        run_id: str | None = None,
        error: str | None = None,
    ) -> str:
        """Write (or update) a row in raw.ingest_log. Returns the run_id."""
        if run_id is None:
            row = conn.execute(
                """
                INSERT INTO raw.ingest_log (source, rows_fetched, rows_inserted, status, error,
                                            finished_at)
                VALUES (%s, %s, %s, %s, %s, now())
                RETURNING run_id
                """,
                (source, rows_fetched, rows_inserted, "done" if error is None else "error", error),
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

    def run(self, conn: psycopg.Connection[Any], dry_run: bool = False) -> IngestResult:
        t0 = time.monotonic()

        # Open ingest_log row immediately
        log_row = conn.execute(
            "INSERT INTO raw.ingest_log (source) VALUES (%s) RETURNING run_id",
            (self.dataset,),
        ).fetchone()
        assert log_row is not None
        run_id = str(log_row[0])
        conn.commit()

        rows_fetched = 0
        rows_inserted = 0
        raw_ids: list[int] = []
        skipped = False
        error_msg: str | None = None

        try:
            all_records: list[dict[str, Any]] = []
            for page in self.fetch_pages():
                all_records.extend(page)

            rows_fetched = len(all_records)

            if not dry_run:
                for record in all_records:
                    sid = record.get(self.source_id_field)
                    if not sid:
                        logger.warning(
                            "[%s] record missing source_id field '%s' — skipping",
                            self.dataset,
                            self.source_id_field,
                        )
                        continue
                    row_hash = self.compute_hash(record)
                    inserted = self.upsert_raw(
                        conn, self.raw_table, str(sid), row_hash, record, run_id
                    )
                    if inserted:
                        rows_inserted += 1
                        # retrieve the id we just inserted
                        # noqa: S608 — table name is a trusted class attribute
                        raw_sel = (
                            f"SELECT id FROM {self.raw_table}"  # noqa: S608
                            " WHERE source_id = %s AND row_hash = %s"
                        )
                        row = conn.execute(
                            raw_sel,
                            (str(sid), row_hash),
                        ).fetchone()
                        if row:
                            raw_ids.append(int(row[0]))
                conn.commit()

                if rows_inserted == 0:
                    logger.info("[%s] No new rows — skipped staging upsert", self.dataset)
                    skipped = True
                else:
                    self.upsert_staging(conn, raw_ids)
                    self.upsert_core(conn)
                    conn.commit()
            else:
                logger.info("[%s] dry-run: fetched %d rows, no writes", self.dataset, rows_fetched)
                skipped = True

        except Exception as exc:
            error_msg = str(exc)
            logger.error("[%s] pipeline error: %s", self.dataset, exc)
            try:
                conn.rollback()
            except Exception:
                pass

        self.log_run(
            conn, self.dataset, rows_fetched, rows_inserted, run_id=run_id, error=error_msg
        )
        conn.commit()

        return IngestResult(
            run_id=run_id,
            dataset=self.dataset,
            rows_fetched=rows_fetched,
            rows_inserted=rows_inserted,
            rows_updated_staging=0,
            rows_updated_core=0,
            elapsed_seconds=time.monotonic() - t0,
            skipped=skipped,
            error=error_msg,
        )
