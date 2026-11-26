"""Entry-point: query core.properties, build contact records, push to pending_actions."""

from __future__ import annotations

import os

import psycopg

from pipelines.connectors.hubspot import HubSpotConnector

_OWNERS_SQL = """
SELECT parcel_id, parcel_number, address_normalized,
       COALESCE(owner_1, owner) AS owner
FROM core.properties
WHERE owner IS NOT NULL OR owner_1 IS NOT NULL
LIMIT 500
"""


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(_OWNERS_SQL).fetchall()
        records = [
            {
                "parcel_id": r[0],
                "parcel_number": r[1],
                "address": r[2],
                "owner": r[3],
            }
            for r in rows
        ]
        connector = HubSpotConnector()
        actions = connector.push(records, conn)
        conn.commit()
    print(f"Queued {len(actions)} pending_actions rows")


if __name__ == "__main__":
    main()
