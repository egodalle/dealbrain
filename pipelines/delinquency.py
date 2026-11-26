"""Tax delinquency pipeline: raw.delinquency → staging.delinquency.

BLOCKED: no property-level delinquency table has been confirmed on Philadelphia's Carto
API. The city's current Real Estate Tax Balances release is aggregated by ZIP code,
council district and census tract. Until a parcel-level source is confirmed, this
pipeline fails fast and is excluded from `--dataset philly`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import psycopg

from pipelines.base import PAGE_SIZE, BasePipeline

logger = logging.getLogger(__name__)

BLOCKED_REASON = "blocked: no property-level tax delinquency table confirmed on phl.carto.com"


def _safe_numeric(val: Any) -> str | None:
    if val is None or val == "":
        return None
    return str(val)


def _safe_int(val: Any) -> int | None:
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


@dataclass
class DelinquencyPipeline(BasePipeline):
    dataset: str = "delinquency"
    source_id_field: str = "account_number"
    raw_table: str = "raw.delinquency"
    staging_table: str = "staging.delinquency"

    def fetch_pages(
        self, offset: int = 0, limit: int = PAGE_SIZE
    ) -> Iterator[list[dict[str, Any]]]:
        raise RuntimeError(BLOCKED_REASON)

    def upsert_staging(self, conn: psycopg.Connection[Any], raw_ids: list[int]) -> int:
        updated = 0
        for raw_id in raw_ids:
            row = conn.execute(
                "SELECT source_id, payload, row_hash FROM raw.delinquency WHERE id = %s",
                (raw_id,),
            ).fetchone()
            if row is None:
                continue
            account_number: str = row[0]
            payload: dict[str, Any] = row[1] if isinstance(row[1], dict) else json.loads(row[1])
            row_hash: str = row[2]

            parcel_id: str | None = payload.get("parcel_number") or payload.get("parcel_id")

            existing = conn.execute(
                "SELECT row_hash FROM staging.delinquency WHERE account_number = %s",
                (account_number,),
            ).fetchone()

            if existing is not None and existing[0] != row_hash:
                conn.execute(
                    """
                    INSERT INTO staging.delinquency_history
                        (account_number, parcel_id, raw_id, row_hash, owner,
                         total_due, num_years_owed, lien_number, _updated_at,
                         valid_from, valid_to)
                    SELECT account_number, parcel_id, raw_id, row_hash, owner,
                           total_due, num_years_owed, lien_number, _updated_at,
                           _updated_at, now()
                    FROM staging.delinquency
                    WHERE account_number = %s
                    """,
                    (account_number,),
                )

            conn.execute(
                """
                INSERT INTO staging.delinquency
                    (account_number, parcel_id, raw_id, row_hash, owner,
                     total_due, num_years_owed, lien_number, _updated_at)
                VALUES (%s, %s, %s, %s, %s, %s::numeric, %s, %s, now())
                ON CONFLICT (account_number) DO UPDATE SET
                    parcel_id = EXCLUDED.parcel_id,
                    raw_id = EXCLUDED.raw_id,
                    row_hash = EXCLUDED.row_hash,
                    owner = EXCLUDED.owner,
                    total_due = EXCLUDED.total_due,
                    num_years_owed = EXCLUDED.num_years_owed,
                    lien_number = EXCLUDED.lien_number,
                    _updated_at = now()
                """,
                (
                    account_number,
                    parcel_id,
                    raw_id,
                    row_hash,
                    payload.get("owner"),
                    _safe_numeric(payload.get("total_due")),
                    _safe_int(payload.get("num_years_owed")),
                    payload.get("lien_number"),
                ),
            )
            updated += 1
        return updated

    def upsert_core(self, conn: psycopg.Connection[Any]) -> int:
        return 0
