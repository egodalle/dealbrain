"""Migration runner: applies SQL files in db/migrations/ in order, skipping already-applied ones."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).parent.parent / "db" / "migrations"

CREATE_TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _migration_key(path: Path) -> int:
    m = re.match(r"^(\d+)", path.name)
    return int(m.group(1)) if m else 0


def run_migrations(database_url: str) -> None:
    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"), key=_migration_key)
    if not sql_files:
        print("No migration files found.")
        return

    with psycopg.connect(database_url, autocommit=False) as conn:
        conn.execute(CREATE_TRACKING_TABLE)
        conn.commit()

        applied: set[str] = set()
        for row in conn.execute("SELECT filename FROM schema_migrations"):
            applied.add(row[0])

        for sql_path in sql_files:
            fname = sql_path.name
            if fname in applied:
                print(f"  skip  {fname}")
                continue
            print(f"  apply {fname}")
            sql = sql_path.read_text()
            conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)",
                (fname,),
            )
            conn.commit()

    print("Migrations complete.")


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL env var is required.", file=sys.stderr)
        sys.exit(1)
    run_migrations(database_url)


if __name__ == "__main__":
    main()
