"""Dedupe pipeline: address normalization, blocking, entity resolution, cluster formation."""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from typing import Any

import psycopg
from rapidfuzz import fuzz

from pipelines.normalize import blocking_key, clean_owner, normalize_address

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class PropertyRow:
    parcel_id: str
    address_raw: str
    address_normalized: str | None
    owner: str | None
    owner_1: str | None
    owner_2: str | None
    assessed_value: Decimal | None
    created_at: Any  # datetime from psycopg


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

MERGE_THRESHOLD = 0.85
ADDR_ONLY_THRESHOLD = 0.90


def score_pair(a: PropertyRow, b: PropertyRow) -> tuple[float, str]:
    """Return (combined_score, matched_on) for a pair of property rows.

    matched_on is 'address', 'owner_name', or 'both'.
    """
    addr_a = a.address_normalized or a.address_raw or ""
    addr_b = b.address_normalized or b.address_raw or ""
    addr_score = fuzz.token_sort_ratio(addr_a, addr_b) / 100.0

    owner_a = clean_owner(" ".join(filter(None, [a.owner, a.owner_1, a.owner_2])))
    owner_b = clean_owner(" ".join(filter(None, [b.owner, b.owner_1, b.owner_2])))

    if not owner_a or not owner_b:
        # Address-only match; raise threshold to reduce false positives
        return addr_score, "address"

    owner_score = fuzz.token_sort_ratio(owner_a, owner_b) / 100.0
    combined = 0.6 * addr_score + 0.4 * owner_score

    addr_only = addr_score >= MERGE_THRESHOLD
    owner_only = owner_score >= MERGE_THRESHOLD
    if addr_only and owner_only:
        matched_on = "both"
    elif addr_only:
        matched_on = "address"
    else:
        matched_on = "owner_name"

    return combined, matched_on


# ---------------------------------------------------------------------------
# Union-find
# ---------------------------------------------------------------------------


def _find(parent: dict[str, str], x: str) -> str:
    while parent[x] != x:
        parent[x] = parent[parent[x]]  # path compression
        x = parent[x]
    return x


def _union(parent: dict[str, str], rank: dict[str, int], x: str, y: str) -> None:
    rx, ry = _find(parent, x), _find(parent, y)
    if rx == ry:
        return
    if rank[rx] < rank[ry]:
        rx, ry = ry, rx
    parent[ry] = rx
    if rank[rx] == rank[ry]:
        rank[rx] += 1


def build_components(parcel_ids: list[str], edges: list[tuple[str, str]]) -> dict[str, list[str]]:
    """Return dict of root → [parcel_ids in component]."""
    parent = {p: p for p in parcel_ids}
    rank: dict[str, int] = {p: 0 for p in parcel_ids}
    for a, b in edges:
        _union(parent, rank, a, b)
    components: dict[str, list[str]] = {}
    for p in parcel_ids:
        root = _find(parent, p)
        components.setdefault(root, []).append(p)
    return components


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------


def _fetch_rows(conn: psycopg.Connection[Any]) -> list[PropertyRow]:
    rows = conn.execute(
        """
        SELECT parcel_id, address_raw, address_normalized, owner, owner_1, owner_2,
               assessed_value, created_at
        FROM core.properties
        ORDER BY parcel_id
        """
    ).fetchall()
    return [
        PropertyRow(
            parcel_id=str(r[0]),
            address_raw=str(r[1]) if r[1] is not None else "",
            address_normalized=str(r[2]) if r[2] is not None else None,
            owner=str(r[3]) if r[3] is not None else None,
            owner_1=str(r[4]) if r[4] is not None else None,
            owner_2=str(r[5]) if r[5] is not None else None,
            assessed_value=Decimal(str(r[6])) if r[6] is not None else None,
            created_at=r[7],
        )
        for r in rows
    ]


def run_normalization(conn: psycopg.Connection[Any], rows: list[PropertyRow]) -> int:
    """UPDATE address_normalized for rows where it is NULL. Returns count updated."""
    updated = 0
    for row in rows:
        if row.address_normalized is not None:
            continue
        try:
            normalized = normalize_address(row.address_raw)
        except ValueError:
            print(
                f"[dedupe] skipping parcel {row.parcel_id}: empty address_raw",
                file=sys.stderr,
            )
            continue
        conn.execute(
            "UPDATE core.properties"
            " SET address_normalized = %s, updated_at = now()"
            " WHERE parcel_id = %s",
            (normalized, row.parcel_id),
        )
        row.address_normalized = normalized
        updated += 1
    conn.commit()
    return updated


def build_blocks(rows: list[PropertyRow]) -> dict[str, list[PropertyRow]]:
    """Group rows by blocking key. Rows without a key are excluded."""
    blocks: dict[str, list[PropertyRow]] = {}
    for row in rows:
        norm = row.address_normalized or row.address_raw
        key = blocking_key(norm) if norm else None
        if key is None:
            continue
        blocks.setdefault(key, []).append(row)
    return blocks


def match_block(block: list[PropertyRow]) -> list[tuple[str, str, str]]:
    """Return list of (parcel_id_a, parcel_id_b, matched_on) for pairs above threshold."""
    matched: list[tuple[str, str, str]] = []
    for a, b in combinations(block, 2):
        combined, matched_on = score_pair(a, b)
        threshold = ADDR_ONLY_THRESHOLD if matched_on == "address" else MERGE_THRESHOLD
        if combined >= threshold:
            matched.append((a.parcel_id, b.parcel_id, matched_on))
    return matched


def assign_clusters(
    conn: psycopg.Connection[Any],
    rows: list[PropertyRow],
    matched_pairs: list[tuple[str, str, str]],
) -> int:
    """Build clusters via union-find, pick canonical, INSERT into core.property_clusters.

    Returns number of rows inserted.
    """
    all_ids = [r.parcel_id for r in rows]
    edges = [(a, b) for a, b, _ in matched_pairs]
    components = build_components(all_ids, edges)

    # Map parcel_id → matched_on signal (take 'both' > 'address' > 'owner_name')
    signal_rank = {"both": 2, "address": 1, "owner_name": 0}
    pair_signal: dict[tuple[str, str], str] = {}
    for a, b, matched_on in matched_pairs:
        key_ab = (min(a, b), max(a, b))
        existing = pair_signal.get(key_ab, "owner_name")
        if signal_rank[matched_on] > signal_rank[existing]:
            pair_signal[key_ab] = matched_on

    # Build lookup: parcel_id → row
    row_lookup = {r.parcel_id: r for r in rows}

    # Determine the matched_on signal per member within a cluster (from edges)
    def _cluster_signal(component: list[str]) -> str:
        """Pick the highest signal among all pairs in the component."""
        best = "address"
        for i, a in enumerate(component):
            for b in component[i + 1 :]:
                k = (min(a, b), max(a, b))
                s = pair_signal.get(k, "address")
                if signal_rank[s] > signal_rank[best]:
                    best = s
        return best

    # Fetch existing property_ids in clusters to enforce idempotency
    existing_property_ids: set[str] = set()
    for existing_row in conn.execute("SELECT property_id FROM core.property_clusters").fetchall():
        existing_property_ids.add(str(existing_row[0]))

    inserted = 0
    for _root, component in components.items():
        # Sort component for determinism
        component_sorted = sorted(component)

        # Assign deterministic cluster UUID seeded by sorted parcel_ids
        cluster_seed = "_".join(component_sorted)
        cluster_id = uuid.uuid5(uuid.NAMESPACE_DNS, cluster_seed)

        # Choose canonical: highest assessed_value, then earliest created_at
        def _sort_key(pid: str) -> tuple[Decimal, Any]:
            r = row_lookup[pid]
            av = r.assessed_value if r.assessed_value is not None else Decimal("0")
            return (-av, r.created_at)

        component_sorted_by_value = sorted(component_sorted, key=_sort_key)
        canonical_id = component_sorted_by_value[0]

        is_singleton = len(component_sorted) == 1
        matched_on = "address" if is_singleton else _cluster_signal(component_sorted)

        for pid in component_sorted:
            if pid in existing_property_ids:
                continue
            is_canonical = pid == canonical_id
            conn.execute(
                """
                INSERT INTO core.property_clusters
                    (cluster_id, property_id, is_canonical, matched_on)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (property_id) DO NOTHING
                """,
                (str(cluster_id), pid, is_canonical, matched_on),
            )
            inserted += 1

    conn.commit()
    return inserted


def run(conn: psycopg.Connection[Any]) -> None:
    """Orchestrate the full dedupe pipeline."""
    print("[dedupe] fetching properties ...", flush=True)
    rows = _fetch_rows(conn)
    print(f"[dedupe] {len(rows)} properties loaded", flush=True)

    updated = run_normalization(conn, rows)
    print(f"[dedupe] {updated} addresses normalized", flush=True)

    blocks = build_blocks(rows)
    print(f"[dedupe] {len(blocks)} blocking keys", flush=True)

    all_pairs: list[tuple[str, str, str]] = []
    for block in blocks.values():
        if len(block) >= 2:
            all_pairs.extend(match_block(block))
    print(f"[dedupe] {len(all_pairs)} matched pairs above threshold", flush=True)

    inserted = assign_clusters(conn, rows, all_pairs)
    print(f"[dedupe] {inserted} cluster rows inserted", flush=True)

    # Verify AC-1: check for NULL address_normalized
    null_count = conn.execute(
        "SELECT COUNT(*) FROM core.properties WHERE address_normalized IS NULL"
    ).fetchone()
    null_val = null_count[0] if null_count else -1
    print(f"[dedupe] properties with NULL address_normalized: {null_val}", flush=True)
    if null_val != 0:
        print(
            f"[dedupe] WARNING: {null_val} rows still have NULL address_normalized",
            file=sys.stderr,
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
