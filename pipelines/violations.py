"""L&I violations pipeline: raw.violations → staging.violations."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import psycopg

from pipelines.base import BasePipeline

logger = logging.getLogger(__name__)

_DEFAULT_URL = "https://data.phila.gov/resource/t2h5-k7ba.json"


def _safe_date(val: Any) -> str | None:
    if not val:
        return None
    return str(val)[:10]


@dataclass
class ViolationsPipeline(BasePipeline):
    dataset: str = "violations"
    socrata_url: str = field(
        default_factory=lambda: os.environ.get("PHILLY_VIOLATIONS_URL", _DEFAULT_URL)
    )
    source_id_field: str = "violationid"
    raw_table: str = "raw.violations"
    staging_table: str = "staging.violations"

    def upsert_staging(self, conn: psycopg.Connection[Any], raw_ids: list[int]) -> int:
        updated = 0
        for raw_id in raw_ids:
            row = conn.execute(
                "SELECT source_id, payload, row_hash FROM raw.violations WHERE id = %s",
                (raw_id,),
            ).fetchone()
            if row is None:
                continue
            violation_id: str = row[0]
            payload: dict[str, Any] = row[1] if isinstance(row[1], dict) else json.loads(row[1])
            row_hash: str = row[2]

            parcel_id: str | None = payload.get("parcel_id_num") or payload.get("parcel_number")

            existing = conn.execute(
                "SELECT row_hash, _updated_at FROM staging.violations WHERE violation_id = %s",
                (violation_id,),
            ).fetchone()

            if existing is not None and existing[0] != row_hash:
                conn.execute(
                    """
                    INSERT INTO staging.violations_history
                        (violation_id, parcel_id, raw_id, row_hash, address,
                         violation_code, violation_desc, violation_date,
                         case_opened_date, case_status, _updated_at, valid_from, valid_to)
                    SELECT violation_id, parcel_id, raw_id, row_hash, address,
                           violation_code, violation_desc, violation_date,
                           case_opened_date, case_status, _updated_at, _updated_at, now()
                    FROM staging.violations
                    WHERE violation_id = %s
                    """,
                    (violation_id,),
                )

            conn.execute(
                """
                INSERT INTO staging.violations
                    (violation_id, parcel_id, raw_id, row_hash, address,
                     violation_code, violation_desc, violation_date,
                     case_opened_date, case_status, _updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::date, %s::date, %s, now())
                ON CONFLICT (violation_id) DO UPDATE SET
                    parcel_id = EXCLUDED.parcel_id,
                    raw_id = EXCLUDED.raw_id,
                    row_hash = EXCLUDED.row_hash,
                    address = EXCLUDED.address,
                    violation_code = EXCLUDED.violation_code,
                    violation_desc = EXCLUDED.violation_desc,
                    violation_date = EXCLUDED.violation_date,
                    case_opened_date = EXCLUDED.case_opened_date,
                    case_status = EXCLUDED.case_status,
                    _updated_at = now()
                """,
                (
                    violation_id,
                    parcel_id,
                    raw_id,
                    row_hash,
                    payload.get("address"),
                    payload.get("violationcode") or payload.get("violation_code"),
                    payload.get("violationdescription") or payload.get("violation_desc"),
                    _safe_date(payload.get("violationdate") or payload.get("violation_date")),
                    _safe_date(payload.get("caseopeneddate") or payload.get("case_opened_date")),
                    payload.get("casestatus") or payload.get("case_status"),
                ),
            )
            updated += 1
        return updated

    def upsert_core(self, conn: psycopg.Connection[Any]) -> int:
        # Violations do not drive core.properties; OPA is the authority.
        return 0
