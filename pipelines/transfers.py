"""RTT deed transfers pipeline: raw.transfers → staging.transfers."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import psycopg

from pipelines.base import BasePipeline

logger = logging.getLogger(__name__)

_DEFAULT_URL = "https://data.phila.gov/resource/4iqs-r3wa.json"


def _safe_numeric(val: Any) -> str | None:
    if val is None or val == "":
        return None
    return str(val)


def _safe_date(val: Any) -> str | None:
    if not val:
        return None
    return str(val)[:10]


@dataclass
class TransfersPipeline(BasePipeline):
    dataset: str = "transfers"
    socrata_url: str = field(
        default_factory=lambda: os.environ.get("PHILLY_TRANSFERS_URL", _DEFAULT_URL)
    )
    source_id_field: str = "document_id"
    raw_table: str = "raw.transfers"
    staging_table: str = "staging.transfers"

    def upsert_staging(self, conn: psycopg.Connection[Any], raw_ids: list[int]) -> int:
        updated = 0
        for raw_id in raw_ids:
            row = conn.execute(
                "SELECT source_id, payload, row_hash FROM raw.transfers WHERE id = %s",
                (raw_id,),
            ).fetchone()
            if row is None:
                continue
            document_id: str = row[0]
            payload: dict[str, Any] = row[1] if isinstance(row[1], dict) else json.loads(row[1])
            row_hash: str = row[2]

            parcel_id: str | None = payload.get("parcel_number") or payload.get("parcel_id")

            existing = conn.execute(
                "SELECT row_hash FROM staging.transfers WHERE document_id = %s",
                (document_id,),
            ).fetchone()

            if existing is not None and existing[0] != row_hash:
                conn.execute(
                    """
                    INSERT INTO staging.transfers_history
                        (document_id, parcel_id, raw_id, row_hash, grantee, grantor,
                         recording_date, sale_price, document_type, _updated_at,
                         valid_from, valid_to)
                    SELECT document_id, parcel_id, raw_id, row_hash, grantee, grantor,
                           recording_date, sale_price, document_type, _updated_at,
                           _updated_at, now()
                    FROM staging.transfers
                    WHERE document_id = %s
                    """,
                    (document_id,),
                )

            conn.execute(
                """
                INSERT INTO staging.transfers
                    (document_id, parcel_id, raw_id, row_hash, grantee, grantor,
                     recording_date, sale_price, document_type, _updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s::date, %s::numeric, %s, now())
                ON CONFLICT (document_id) DO UPDATE SET
                    parcel_id = EXCLUDED.parcel_id,
                    raw_id = EXCLUDED.raw_id,
                    row_hash = EXCLUDED.row_hash,
                    grantee = EXCLUDED.grantee,
                    grantor = EXCLUDED.grantor,
                    recording_date = EXCLUDED.recording_date,
                    sale_price = EXCLUDED.sale_price,
                    document_type = EXCLUDED.document_type,
                    _updated_at = now()
                """,
                (
                    document_id,
                    parcel_id,
                    raw_id,
                    row_hash,
                    payload.get("grantees") or payload.get("grantee"),
                    payload.get("grantors") or payload.get("grantor"),
                    _safe_date(payload.get("recording_date")),
                    _safe_numeric(payload.get("total_consideration") or payload.get("sale_price")),
                    payload.get("document_type"),
                ),
            )
            updated += 1
        return updated

    def upsert_core(self, conn: psycopg.Connection[Any]) -> int:
        return 0
