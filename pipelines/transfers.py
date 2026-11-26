"""RTT deed transfers pipeline: raw.transfers → staging.transfers.

rtt_summary is very large, and filtering it by ZIP or date makes Carto scan the whole
table. Instead, after OPA has loaded core.properties, we look transfers up by parcel
number (opa_account_num), which is indexed, in batches of _ID_CHUNK parcels.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import psycopg

from pipelines.base import PAGE_SIZE, BasePipeline, philly_since, philly_zips, sql_in

logger = logging.getLogger(__name__)

_ID_CHUNK = 150
_PARCEL_RE = re.compile(r"^[0-9A-Za-z]{1,20}$")

_COLUMNS = (
    "document_id",
    "document_type",
    "display_date",
    "recording_date",
    "document_date",
    "opa_account_num",
    "street_address",
    "zip_code",
    "grantors",
    "grantees",
    "total_consideration",
    "fair_market_value",
)


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
    carto_table: str = "rtt_summary"
    carto_columns: tuple[str, ...] = _COLUMNS
    source_id_field: str = "document_id"
    raw_table: str = "raw.transfers"
    staging_table: str = "staging.transfers"
    parcel_ids: list[str] = field(default_factory=list, repr=False)
    current_chunk: list[str] = field(default_factory=list, repr=False)

    def prepare(self, conn: psycopg.Connection[Any]) -> None:
        rows = conn.execute(
            "SELECT parcel_id FROM core.properties WHERE left(zip_code, 5) = ANY(%s)"
            " ORDER BY parcel_id",
            (philly_zips(),),
        ).fetchall()
        self.parcel_ids = [str(r[0]) for r in rows if _PARCEL_RE.match(str(r[0]))]
        if not self.parcel_ids:
            logger.warning(
                "[transfers] core.properties has no parcels for PHILLY_ZIPS; run opa first"
            )

    def carto_where(self) -> str:
        # Deeds only (sales, sheriff's deeds); mortgages and satisfactions are noise here.
        return (
            f"opa_account_num IN ({sql_in(self.current_chunk)}) "
            f"AND display_date >= '{philly_since()}' "
            "AND document_type ILIKE '%DEED%'"
        )

    def fetch_pages(
        self, offset: int = 0, limit: int = PAGE_SIZE
    ) -> Iterator[list[dict[str, Any]]]:
        for i in range(0, len(self.parcel_ids), _ID_CHUNK):
            self.current_chunk = self.parcel_ids[i : i + _ID_CHUNK]
            yield from super().fetch_pages(0, limit)

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

            # opa_account_num is the OPA parcel number that core.properties is keyed on
            parcel_id: str | None = payload.get("opa_account_num")

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
