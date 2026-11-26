"""OPA assessments pipeline: raw.opa_assessments → staging.opa_properties → core.properties."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import psycopg

from pipelines.base import BasePipeline

logger = logging.getLogger(__name__)

_DEFAULT_URL = "https://data.phila.gov/resource/w7rb-qrn8.json"


def _safe_numeric(val: Any) -> str | None:
    """Return val as string for psycopg numeric cast, or None."""
    if val is None or val == "":
        return None
    return str(val)


def _safe_date(val: Any) -> str | None:
    if not val:
        return None
    # Socrata returns ISO date strings; take the date part only
    return str(val)[:10]


def require_parcel_id(parcel_number: Any) -> str:
    """Raise ValueError if parcel_number is None or empty; return it as str otherwise."""
    if parcel_number is None or str(parcel_number).strip() == "":
        raise ValueError(f"parcel_number must not be null or empty, got {parcel_number!r}")
    return str(parcel_number)


@dataclass
class OPAPipeline(BasePipeline):
    dataset: str = "opa"
    socrata_url: str = field(default_factory=lambda: os.environ.get("PHILLY_OPA_URL", _DEFAULT_URL))
    source_id_field: str = "parcel_number"
    raw_table: str = "raw.opa_assessments"
    staging_table: str = "staging.opa_properties"

    def upsert_staging(self, conn: psycopg.Connection[Any], raw_ids: list[int]) -> int:
        updated = 0
        for raw_id in raw_ids:
            row = conn.execute(
                "SELECT source_id, payload FROM raw.opa_assessments WHERE id = %s",
                (raw_id,),
            ).fetchone()
            if row is None:
                continue
            parcel_id: str = require_parcel_id(row[0])
            payload: dict[str, Any] = row[1] if isinstance(row[1], dict) else json.loads(row[1])
            row_hash_row = conn.execute(
                "SELECT row_hash FROM raw.opa_assessments WHERE id = %s",
                (raw_id,),
            ).fetchone()
            row_hash = row_hash_row[0] if row_hash_row else ""

            existing = conn.execute(
                "SELECT row_hash, _updated_at FROM staging.opa_properties WHERE parcel_id = %s",
                (parcel_id,),
            ).fetchone()

            if existing is not None and existing[0] != row_hash:
                # Archive current version to history
                conn.execute(
                    """
                    INSERT INTO staging.opa_properties_history
                        (parcel_id, raw_id, row_hash, location, unit, zip_code,
                         owner_1, owner_2, building_code, building_code_description,
                         category_code, category_code_description, market_value,
                         sale_date, sale_price, taxable_land, taxable_building,
                         exempt_land, exempt_building, _created_at, _updated_at,
                         valid_from, valid_to)
                    SELECT parcel_id, raw_id, row_hash, location, unit, zip_code,
                           owner_1, owner_2, building_code, building_code_description,
                           category_code, category_code_description, market_value,
                           sale_date, sale_price, taxable_land, taxable_building,
                           exempt_land, exempt_building, _created_at, _updated_at,
                           _updated_at, now()
                    FROM staging.opa_properties
                    WHERE parcel_id = %s
                    """,
                    (parcel_id,),
                )

            conn.execute(
                """
                INSERT INTO staging.opa_properties
                    (parcel_id, raw_id, row_hash, location, unit, zip_code,
                     owner_1, owner_2, building_code, building_code_description,
                     category_code, category_code_description, market_value,
                     sale_date, sale_price, taxable_land, taxable_building,
                     exempt_land, exempt_building, _updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::numeric, %s::date, %s::numeric, %s::numeric, %s::numeric,
                        %s::numeric, %s::numeric, now())
                ON CONFLICT (parcel_id) DO UPDATE SET
                    raw_id = EXCLUDED.raw_id,
                    row_hash = EXCLUDED.row_hash,
                    location = EXCLUDED.location,
                    unit = EXCLUDED.unit,
                    zip_code = EXCLUDED.zip_code,
                    owner_1 = EXCLUDED.owner_1,
                    owner_2 = EXCLUDED.owner_2,
                    building_code = EXCLUDED.building_code,
                    building_code_description = EXCLUDED.building_code_description,
                    category_code = EXCLUDED.category_code,
                    category_code_description = EXCLUDED.category_code_description,
                    market_value = EXCLUDED.market_value,
                    sale_date = EXCLUDED.sale_date,
                    sale_price = EXCLUDED.sale_price,
                    taxable_land = EXCLUDED.taxable_land,
                    taxable_building = EXCLUDED.taxable_building,
                    exempt_land = EXCLUDED.exempt_land,
                    exempt_building = EXCLUDED.exempt_building,
                    _updated_at = now()
                """,
                (
                    parcel_id,
                    raw_id,
                    row_hash,
                    payload.get("location"),
                    payload.get("unit"),
                    payload.get("zip_code"),
                    payload.get("owner_1"),
                    payload.get("owner_2"),
                    payload.get("building_code"),
                    payload.get("building_code_description"),
                    payload.get("category_code"),
                    payload.get("category_code_description"),
                    _safe_numeric(payload.get("market_value")),
                    _safe_date(payload.get("sale_date")),
                    _safe_numeric(payload.get("sale_price")),
                    _safe_numeric(payload.get("taxable_land")),
                    _safe_numeric(payload.get("taxable_building")),
                    _safe_numeric(payload.get("exempt_land")),
                    _safe_numeric(payload.get("exempt_building")),
                ),
            )
            updated += 1
        return updated

    def upsert_core(self, conn: psycopg.Connection[Any]) -> int:
        result = conn.execute(
            """
            INSERT INTO core.properties
                (parcel_id, parcel_number, address_raw, zip_code,
                 owner_1, owner_2, market_value, building_code, category_code,
                 sale_date, sale_price, source_updated_at, raw_id,
                 updated_at)
            SELECT
                s.parcel_id,
                s.parcel_id,
                COALESCE(s.location, ''),
                s.zip_code,
                s.owner_1,
                s.owner_2,
                s.market_value,
                s.building_code,
                s.category_code,
                s.sale_date,
                s.sale_price,
                s._updated_at,
                s.raw_id,
                now()
            FROM staging.opa_properties s
            ON CONFLICT (parcel_id) DO UPDATE SET
                parcel_number = EXCLUDED.parcel_number,
                address_raw = EXCLUDED.address_raw,
                zip_code = EXCLUDED.zip_code,
                owner_1 = EXCLUDED.owner_1,
                owner_2 = EXCLUDED.owner_2,
                market_value = EXCLUDED.market_value,
                building_code = EXCLUDED.building_code,
                category_code = EXCLUDED.category_code,
                sale_date = EXCLUDED.sale_date,
                sale_price = EXCLUDED.sale_price,
                source_updated_at = EXCLUDED.source_updated_at,
                raw_id = EXCLUDED.raw_id,
                updated_at = now()
            """
        )
        return result.rowcount if result.rowcount >= 0 else 0
