"""Dedupe eval: measure precision/recall/F1 against tests/fixtures/dedupe_pairs_200.csv.

Runs without a live database — constructs synthetic PropertyRow objects from the
fixture's encoded property_id field (format: 'ID|ADDRESS|OWNER').

Writes results to docs/work/DB-04/eval-results.txt.
Exits with code 1 if precision or recall < 0.80.
"""

from __future__ import annotations

import csv
import sys
from decimal import Decimal
from pathlib import Path

# Allow running from repo root or evals/dedupe/
_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from pipelines.dedupe import ADDR_ONLY_THRESHOLD, MERGE_THRESHOLD, PropertyRow, score_pair  # noqa: E402

FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "dedupe_pairs_200.csv"
RESULTS_PATH = _REPO_ROOT / "docs" / "work" / "DB-04" / "eval-results.txt"

_PLACEHOLDER_DT = "2020-01-01T00:00:00+00:00"


def _parse_row(pid: str) -> PropertyRow:
    """Parse 'ID|ADDRESS|OWNER' into a PropertyRow.

    Falls back gracefully if the owner field is missing.
    """
    parts = pid.split("|", 2)
    parcel_id = parts[0] if len(parts) > 0 else pid
    address = parts[1] if len(parts) > 1 else ""
    owner = parts[2] if len(parts) > 2 else ""
    return PropertyRow(
        parcel_id=parcel_id,
        address_raw=address,
        address_normalized=address,
        owner=owner,
        owner_1=None,
        owner_2=None,
        assessed_value=Decimal("0"),
        created_at=_PLACEHOLDER_DT,
    )


def _predict(a: PropertyRow, b: PropertyRow) -> int:
    combined, matched_on = score_pair(a, b)
    threshold = ADDR_ONLY_THRESHOLD if matched_on == "address" else MERGE_THRESHOLD
    return 1 if combined >= threshold else 0


def run_eval(fixture_path: Path = FIXTURE_PATH) -> tuple[float, float, float]:
    """Return (precision, recall, f1)."""
    tp = fp = fn = tn = 0
    with fixture_path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            a = _parse_row(row["property_id_a"])
            b = _parse_row(row["property_id_b"])
            label = int(row["is_duplicate"])
            pred = _predict(a, b)
            if pred == 1 and label == 1:
                tp += 1
            elif pred == 1 and label == 0:
                fp += 1
            elif pred == 0 and label == 1:
                fn += 1
            else:
                tn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def main() -> None:
    precision, recall, f1 = run_eval()
    result_line = f"precision={precision:.4f}  recall={recall:.4f}  f1={f1:.4f}"
    print(result_line)

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(result_line + "\n")
    print(f"Results written to {RESULTS_PATH}")

    if precision < 0.80 or recall < 0.80:
        print(
            f"FAIL: precision={precision:.4f} recall={recall:.4f} — both must be >= 0.80",
            file=sys.stderr,
        )
        sys.exit(1)
    print("PASS: precision and recall >= 0.80")


if __name__ == "__main__":
    main()
