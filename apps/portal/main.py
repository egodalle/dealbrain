from __future__ import annotations

import csv
import io
import os
from typing import Any

import psycopg
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse

app = FastAPI()

# ---------------------------------------------------------------------------
# DB connection — obtained lazily on first request via module-level cache
# ---------------------------------------------------------------------------

_conn: psycopg.Connection[Any] | None = None


def _get_conn() -> psycopg.Connection[Any]:
    global _conn
    if _conn is None or _conn.closed:
        database_url = os.environ.get("DATABASE_URL", "")
        _conn = psycopg.connect(database_url)
    return _conn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LEADS_SQL = """
SELECT
    p.parcel_number,
    p.address_normalized,
    p.distress_score,
    p.score_components,
    COALESCE(p.owner_1, p.owner) AS owner
FROM core.properties p
JOIN core.property_clusters pc ON pc.property_id = p.parcel_id
WHERE pc.is_canonical = true
  AND p.distress_score IS NOT NULL
  AND p.distress_score >= %(min_score)s
ORDER BY p.distress_score DESC
LIMIT %(limit)s
"""

_LEADS_SQL_NO_LIMIT = """
SELECT
    p.parcel_number,
    p.address_normalized,
    p.distress_score,
    p.score_components,
    COALESCE(p.owner_1, p.owner) AS owner
FROM core.properties p
JOIN core.property_clusters pc ON pc.property_id = p.parcel_id
WHERE pc.is_canonical = true
  AND p.distress_score IS NOT NULL
ORDER BY p.distress_score DESC
"""


def _top_factors(score_components: dict[str, Any] | None) -> tuple[str, str, str]:
    """Return the three factor names with highest sub-scores, desc. Ties broken alphabetically."""
    if not score_components:
        return ("", "", "")
    sorted_keys = sorted(
        score_components.keys(),
        key=lambda k: (-score_components[k], k),
    )
    padded = sorted_keys + ["", "", ""]
    return (padded[0], padded[1], padded[2])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "dealbrain-portal"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/leads")
async def get_leads(
    limit: int = Query(default=50, ge=1, le=500),
    min_score: int = Query(default=0, ge=0, le=100),
) -> list[dict[str, Any]]:
    conn = _get_conn()
    rows = conn.execute(_LEADS_SQL, {"min_score": min_score, "limit": limit}).fetchall()
    result = []
    for row in rows:
        result.append(
            {
                "parcel_number": row[0],
                "address_normalized": row[1],
                "distress_score": row[2],
                "score_components": row[3],
                "owner": row[4],
            }
        )
    return result


@app.get("/leads/export.csv")
async def export_leads_csv() -> StreamingResponse:
    conn = _get_conn()
    rows = conn.execute(_LEADS_SQL_NO_LIMIT).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "parcel_number",
            "address_normalized",
            "distress_score",
            "factor_1",
            "factor_2",
            "factor_3",
        ]
    )
    for row in rows:
        f1, f2, f3 = _top_factors(row[3])
        writer.writerow([row[0], row[1], row[2], f1, f2, f3])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="leads.csv"'},
    )
