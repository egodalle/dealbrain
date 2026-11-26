"""Distress scoring pipeline.

Computes a deterministic weighted distress score (0-100) for each canonical property.
Idempotent: rows whose scoring inputs have not changed are skipped.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from typing import Any

import psycopg

# ---------------------------------------------------------------------------
# Weights — must sum to 100 (ADR-0005)
# ---------------------------------------------------------------------------

W_DELINQUENCY = 35
W_VIOLATIONS = 25
W_YEARS_HELD = 20
W_VALUE_GAP = 20

assert W_DELINQUENCY + W_VIOLATIONS + W_YEARS_HELD + W_VALUE_GAP == 100


# ---------------------------------------------------------------------------
# Input hash
# ---------------------------------------------------------------------------


def compute_input_hash(
    parcel_id: str,
    delinquent: int,
    violation_count: int,
    years_held: float,
    assessed_value: float | None,
) -> str:
    """Return a 16-char SHA-256 hex digest of the scoring inputs."""
    payload = json.dumps(
        [parcel_id, delinquent, violation_count, years_held, str(assessed_value)],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Zip medians
# ---------------------------------------------------------------------------


def compute_zip_medians(conn: psycopg.Connection[Any]) -> dict[str, float]:
    """Return median assessed_value per zip_code (minimum 3 properties)."""
    rows = conn.execute(
        """
        SELECT zip_code,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY assessed_value)
        FROM core.properties
        WHERE assessed_value IS NOT NULL
        GROUP BY zip_code
        HAVING COUNT(*) >= 3
        """
    ).fetchall()
    return {str(r[0]): float(r[1]) for r in rows if r[0] is not None}


# ---------------------------------------------------------------------------
# Component scoring helpers
# ---------------------------------------------------------------------------


def _delinquency_component(num_years_owed: int) -> float:
    return min(num_years_owed / 10.0, 1.0) * W_DELINQUENCY


def _violations_component(violation_count: int) -> float:
    return min(violation_count / 5.0, 1.0) * W_VIOLATIONS


def _years_held_component(years_held: float) -> float:
    return min(max(years_held, 0.0) / 20.0, 1.0) * W_YEARS_HELD


def _value_gap_component(assessed_value: float | None, zip_median: float | None) -> float:
    if assessed_value is None or zip_median is None or zip_median == 0.0:
        return 0.0
    gap_ratio = (zip_median - assessed_value) / zip_median
    gap_ratio = max(0.0, min(1.0, gap_ratio))
    return gap_ratio * W_VALUE_GAP


# ---------------------------------------------------------------------------
# Floor-and-remainder rounding to guarantee sum invariant
# ---------------------------------------------------------------------------


def _distribute_to_int(floats: dict[str, float], total: int) -> dict[str, int]:
    """Assign floor() to each component, distribute remainder to highest-fractional ones.

    Guarantees sum(result.values()) == total.
    """
    floors = {k: math.floor(v) for k, v in floats.items()}
    remainder = total - sum(floors.values())
    # Sort by fractional part descending, break ties alphabetically
    by_frac = sorted(floats.keys(), key=lambda k: (-(floats[k] - math.floor(floats[k])), k))
    for k in by_frac[:remainder]:
        floors[k] += 1
    return floors


# ---------------------------------------------------------------------------
# score_property
# ---------------------------------------------------------------------------


def score_property(
    parcel_id: str,
    conn: psycopg.Connection[Any],
    zip_medians: dict[str, float],
) -> tuple[int, dict[str, int]]:
    """Compute (distress_score, score_components) for one property.

    Reads staging.delinquency, staging.violations, core.properties.
    Does not write.
    Raises ValueError if parcel_id not found in core.properties.
    Returns (score, components) where sum(components.values()) == score.
    """
    # Fetch property base data
    prop_row = conn.execute(
        """
        SELECT assessed_value, zip_code, sale_date
        FROM core.properties
        WHERE parcel_id = %s
        """,
        (parcel_id,),
    ).fetchone()
    if prop_row is None:
        raise ValueError(f"parcel_id not found: {parcel_id!r}")

    assessed_value = float(prop_row[0]) if prop_row[0] is not None else None
    zip_code = str(prop_row[1]) if prop_row[1] is not None else None
    sale_date = prop_row[2]  # datetime.date or None

    # Delinquency
    delinq_row = conn.execute(
        "SELECT COALESCE(num_years_owed, 0) FROM staging.delinquency WHERE parcel_id = %s",
        (parcel_id,),
    ).fetchone()
    num_years_owed: int = int(delinq_row[0]) if delinq_row is not None else 0

    # Open violations
    viol_row = conn.execute(
        """
        SELECT COUNT(*)
        FROM staging.violations
        WHERE parcel_id = %s
          AND case_status NOT IN ('CLOSED', 'closed', 'C')
        """,
        (parcel_id,),
    ).fetchone()
    violation_count: int = int(viol_row[0]) if viol_row is not None else 0

    # Years held
    if sale_date is not None:
        import datetime

        sale_year = sale_date.year if hasattr(sale_date, "year") else int(str(sale_date)[:4])
        current_year = datetime.date.today().year
        years_held = float(current_year - sale_year)
    else:
        years_held = 0.0

    # Zip median
    zip_median = zip_medians.get(zip_code) if zip_code else None

    # Float components
    raw: dict[str, float] = {
        "delinquency": _delinquency_component(num_years_owed),
        "violations": _violations_component(violation_count),
        "years_held": _years_held_component(years_held),
        "value_gap": _value_gap_component(assessed_value, zip_median),
    }

    raw_total = sum(raw.values())
    total_score = round(raw_total)
    total_score = max(0, min(100, total_score))

    components = _distribute_to_int(raw, total_score)
    return total_score, components


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def run(conn: psycopg.Connection[Any]) -> None:
    """Score all canonical properties. Idempotent: skips rows where inputs are unchanged."""
    print("[score] computing zip medians ...", flush=True)
    zip_medians = compute_zip_medians(conn)
    print(f"[score] {len(zip_medians)} zip medians computed", flush=True)

    canonical_rows = conn.execute(
        """
        SELECT p.parcel_id, p.assessed_value, p.zip_code, p.sale_date,
               p.score_input_hash
        FROM core.properties p
        JOIN core.property_clusters pc ON pc.property_id = p.parcel_id
        WHERE pc.is_canonical = true
        """
    ).fetchall()
    print(f"[score] {len(canonical_rows)} canonical properties to evaluate", flush=True)

    scored = 0
    skipped = 0

    for row in canonical_rows:
        parcel_id = str(row[0])
        assessed_value = float(row[1]) if row[1] is not None else None
        sale_date = row[3]
        existing_hash = str(row[4]) if row[4] is not None else None

        # Fetch staging data for hash
        delinq_row = conn.execute(
            "SELECT COALESCE(num_years_owed, 0) FROM staging.delinquency WHERE parcel_id = %s",
            (parcel_id,),
        ).fetchone()
        num_years_owed: int = int(delinq_row[0]) if delinq_row is not None else 0

        viol_row = conn.execute(
            """
            SELECT COUNT(*)
            FROM staging.violations
            WHERE parcel_id = %s
              AND case_status NOT IN ('CLOSED', 'closed', 'C')
            """,
            (parcel_id,),
        ).fetchone()
        violation_count: int = int(viol_row[0]) if viol_row is not None else 0

        if sale_date is not None:
            import datetime

            sale_year = sale_date.year if hasattr(sale_date, "year") else int(str(sale_date)[:4])
            current_year = datetime.date.today().year
            years_held_val = float(current_year - sale_year)
        else:
            years_held_val = 0.0

        new_hash = compute_input_hash(
            parcel_id, num_years_owed, violation_count, years_held_val, assessed_value
        )

        if existing_hash == new_hash:
            skipped += 1
            continue

        total_score, components = score_property(parcel_id, conn, zip_medians)

        conn.execute(
            """
            UPDATE core.properties
            SET distress_score   = %s,
                score_components = %s::jsonb,
                score_input_hash = %s,
                updated_at       = now()
            WHERE parcel_id = %s
            """,
            (total_score, json.dumps(components), new_hash, parcel_id),
        )
        scored += 1

    conn.commit()
    print(f"[score] scored {scored}, skipped {skipped} (unchanged)", flush=True)

    # Log unjoined delinquency rows
    unjoined = conn.execute(
        """
        SELECT COUNT(*)
        FROM staging.delinquency d
        WHERE NOT EXISTS (
            SELECT 1 FROM core.properties p WHERE p.parcel_id = d.parcel_id
        )
        """
    ).fetchone()
    unjoined_count = int(unjoined[0]) if unjoined else 0
    if unjoined_count:
        print(
            f"[score] WARNING: {unjoined_count} delinquency rows have no matching property",
            file=sys.stderr,
            flush=True,
        )


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL env var is required.", file=sys.stderr)
        sys.exit(1)
    with psycopg.connect(database_url) as conn:
        run(conn)


if __name__ == "__main__":
    main()
