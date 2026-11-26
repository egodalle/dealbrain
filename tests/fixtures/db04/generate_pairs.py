"""Generate tests/fixtures/dedupe_pairs_200.csv with 200 labeled pairs.

Distribution:
  - 100 true positive pairs (same address, slightly varied owner name)
  - 70 true negative pairs (same house number, different street — hard negatives)
  - 30 partial match pairs (owner LLC rename with same address)

All records are synthetic. No real owner names.
Run from the repo root:
  uv run python tests/fixtures/db04/generate_pairs.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent.parent / "dedupe_pairs_200.csv"

# ---------------------------------------------------------------------------
# Synthetic street names
# ---------------------------------------------------------------------------

_STREETS = [
    "BROAD STREET",
    "MARKET STREET",
    "CHESTNUT STREET",
    "WALNUT STREET",
    "LOCUST STREET",
    "SPRUCE STREET",
    "PINE STREET",
    "ARCH STREET",
    "RACE STREET",
    "VINE STREET",
    "CALLOWHILL STREET",
    "SPRING GARDEN STREET",
    "FAIRMOUNT AVENUE",
    "GIRARD AVENUE",
    "COLUMBIA AVENUE",
    "SUSQUEHANNA AVENUE",
    "LEHIGH AVENUE",
    "ALLEGHENY AVENUE",
    "HUNTING PARK AVENUE",
    "OLNEY AVENUE",
]

# ---------------------------------------------------------------------------
# True positives (100 pairs)
# ---------------------------------------------------------------------------


def _true_positives() -> list[tuple[str, str, int]]:
    """Same address, varied owner name. is_duplicate=1."""
    pairs: list[tuple[str, str, int]] = []
    first_names = [
        "JOHN",
        "JANE",
        "ROBERT",
        "MARY",
        "WILLIAM",
        "PATRICIA",
        "JAMES",
        "LINDA",
        "DAVID",
        "BARBARA",
        "RICHARD",
        "ELIZABETH",
        "JOSEPH",
        "SUSAN",
        "THOMAS",
        "JESSICA",
        "CHARLES",
        "SARAH",
        "CHRISTOPHER",
        "KAREN",
    ]
    last_names = [
        "SMITH",
        "JOHNSON",
        "WILLIAMS",
        "BROWN",
        "JONES",
        "GARCIA",
        "MILLER",
        "DAVIS",
        "RODRIGUEZ",
        "MARTINEZ",
        "HERNANDEZ",
        "LOPEZ",
        "GONZALEZ",
        "WILSON",
        "ANDERSON",
        "THOMAS",
        "TAYLOR",
        "MOORE",
        "JACKSON",
        "MARTIN",
    ]
    streets = _STREETS[:20]
    for i in range(100):
        street = streets[i % len(streets)]
        house = 100 + i * 3
        first = first_names[i % len(first_names)]
        last = last_names[i % len(last_names)]
        addr_a = f"{house} {street}"
        addr_b = f"{house} {street}"
        # Variant: reversed name, or LLC suffix
        owner_a = f"{last} {first}"
        owner_b = f"{first} {last}"
        # Build synthetic property_id_a and property_id_b
        pid_a = f"TP-{i:04d}-A|{addr_a}|{owner_a}"
        pid_b = f"TP-{i:04d}-B|{addr_b}|{owner_b}"
        pairs.append((pid_a, pid_b, 1))
    return pairs


# ---------------------------------------------------------------------------
# True negatives (70 pairs) — same house number, different street
# ---------------------------------------------------------------------------


def _true_negatives() -> list[tuple[str, str, int]]:
    """Same house number, different street. is_duplicate=0."""
    pairs: list[tuple[str, str, int]] = []
    streets = _STREETS
    last_names = [
        "NGUYEN",
        "LEE",
        "PEREZ",
        "WHITE",
        "HARRIS",
        "SANCHEZ",
        "CLARK",
        "RAMIREZ",
        "LEWIS",
        "ROBINSON",
        "WALKER",
        "YOUNG",
        "ALLEN",
        "KING",
        "WRIGHT",
        "SCOTT",
        "TORRES",
        "HILL",
        "FLORES",
        "ADAMS",
    ]
    for i in range(70):
        house = 200 + i * 5
        street_a = streets[i % len(streets)]
        street_b = streets[(i + 7) % len(streets)]
        while street_b == street_a:
            street_b = streets[(i + 11) % len(streets)]
        last = last_names[i % len(last_names)]
        addr_a = f"{house} {street_a}"
        addr_b = f"{house} {street_b}"
        owner_a = f"SYNTHETIC {last} A"
        owner_b = f"SYNTHETIC {last} B"
        pid_a = f"TN-{i:04d}-A|{addr_a}|{owner_a}"
        pid_b = f"TN-{i:04d}-B|{addr_b}|{owner_b}"
        pairs.append((pid_a, pid_b, 0))
    return pairs


# ---------------------------------------------------------------------------
# Partial matches (30 pairs) — same address, owner LLC rename
# ---------------------------------------------------------------------------


def _partial_matches() -> list[tuple[str, str, int]]:
    """Owner LLC rename with same address. is_duplicate=1."""
    pairs: list[tuple[str, str, int]] = []
    streets = _STREETS[:15]
    corp_names = [
        "SUNRISE",
        "SUNSET",
        "HORIZON",
        "MERIDIAN",
        "CREST",
        "RIDGE",
        "VALLEY",
        "SUMMIT",
        "PEAK",
        "GROVE",
        "BROOK",
        "CREEK",
        "LAKE",
        "RIVER",
        "OCEAN",
    ]
    for i in range(30):
        house = 500 + i * 7
        street = streets[i % len(streets)]
        corp = corp_names[i % len(corp_names)]
        addr = f"{house} {street}"
        # Same entity, different registration suffix
        owner_a = f"{corp} PROPERTIES"
        owner_b = f"{corp} PROPERTIES LLC"
        pid_a = f"PM-{i:04d}-A|{addr}|{owner_a}"
        pid_b = f"PM-{i:04d}-B|{addr}|{owner_b}"
        pairs.append((pid_a, pid_b, 1))
    return pairs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    rows: list[tuple[str, str, int]] = []
    rows.extend(_true_positives())
    rows.extend(_true_negatives())
    rows.extend(_partial_matches())

    if len(rows) != 200:
        print(f"ERROR: expected 200 rows, got {len(rows)}", file=sys.stderr)
        sys.exit(1)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["property_id_a", "property_id_b", "is_duplicate"])
        writer.writerows(rows)

    print(f"Written {len(rows)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
