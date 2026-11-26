"""Unit tests for pipelines/score.py — no live DB required."""

from __future__ import annotations

import pytest

from pipelines.score import (
    W_DELINQUENCY,
    W_VALUE_GAP,
    W_VIOLATIONS,
    W_YEARS_HELD,
    _delinquency_component,
    _distribute_to_int,
    _value_gap_component,
    _violations_component,
    _years_held_component,
    compute_input_hash,
)

# ---------------------------------------------------------------------------
# Helpers used across tests
# ---------------------------------------------------------------------------


def _make_components(
    num_years_owed: int = 0,
    violation_count: int = 0,
    years_held: float = 0.0,
    assessed_value: float | None = None,
    zip_median: float | None = None,
) -> tuple[int, dict[str, int]]:
    """Compute (total_score, components) from raw inputs without a DB."""
    raw = {
        "delinquency": _delinquency_component(num_years_owed),
        "violations": _violations_component(violation_count),
        "years_held": _years_held_component(years_held),
        "value_gap": _value_gap_component(assessed_value, zip_median),
    }
    raw_total = sum(raw.values())
    total_score = max(0, min(100, round(raw_total)))
    components = _distribute_to_int(raw, total_score)
    return total_score, components


# ---------------------------------------------------------------------------
# AC-2: sum invariant
# ---------------------------------------------------------------------------


def test_components_sum_equals_total() -> None:
    """sum(components.values()) must equal distress_score for any input combination."""
    cases = [
        # (num_years_owed, violation_count, years_held, assessed_value, zip_median)
        (0, 0, 0.0, None, None),
        (10, 5, 20.0, 50_000.0, 200_000.0),
        (3, 2, 7.0, 180_000.0, 200_000.0),
        (1, 0, 15.0, 250_000.0, 200_000.0),
        (20, 10, 40.0, 10_000.0, 300_000.0),
    ]
    for args in cases:
        total, components = _make_components(*args)
        assert sum(components.values()) == total, (
            f"sum invariant failed for inputs {args}: "
            f"total={total}, sum={sum(components.values())}, components={components}"
        )


# ---------------------------------------------------------------------------
# Score range tests
# ---------------------------------------------------------------------------


def test_score_range_low() -> None:
    """All-zero inputs must yield score == 0."""
    total, components = _make_components(0, 0, 0.0, None, None)
    assert total == 0
    assert sum(components.values()) == 0


def test_score_range_high() -> None:
    """Max inputs must yield score == 100."""
    # 10+ years delinquency (cap), 5+ violations (cap), 20+ years held (cap),
    # assessed_value near 0 vs large median (cap)
    total, components = _make_components(
        num_years_owed=10,
        violation_count=5,
        years_held=20.0,
        assessed_value=0.0,
        zip_median=200_000.0,
    )
    assert total == 100
    assert sum(components.values()) == 100


def test_score_range_clamped() -> None:
    """Score never exceeds 100 or drops below 0 regardless of extreme inputs."""
    extremes = [
        (100, 100, 1000.0, 0.0, 1_000_000.0),
        (0, 0, 0.0, 999_999.0, 50_000.0),
        (50, 50, 50.0, 1.0, 1_000_000.0),
    ]
    for args in extremes:
        total, _ = _make_components(*args)
        assert 0 <= total <= 100, f"score {total} out of range for inputs {args}"


# ---------------------------------------------------------------------------
# Input hash tests
# ---------------------------------------------------------------------------


def test_input_hash_deterministic() -> None:
    """Same inputs always yield the same hash."""
    h1 = compute_input_hash("P-001", 3, 2, 10.0, 150_000.0)
    h2 = compute_input_hash("P-001", 3, 2, 10.0, 150_000.0)
    assert h1 == h2


def test_input_hash_changes() -> None:
    """Changing any input changes the hash."""
    base = compute_input_hash("P-001", 3, 2, 10.0, 150_000.0)
    assert compute_input_hash("P-002", 3, 2, 10.0, 150_000.0) != base
    assert compute_input_hash("P-001", 4, 2, 10.0, 150_000.0) != base
    assert compute_input_hash("P-001", 3, 3, 10.0, 150_000.0) != base
    assert compute_input_hash("P-001", 3, 2, 11.0, 150_000.0) != base
    assert compute_input_hash("P-001", 3, 2, 10.0, 160_000.0) != base


# ---------------------------------------------------------------------------
# _distribute_to_int
# ---------------------------------------------------------------------------


def test_distribute_maintains_sum() -> None:
    """_distribute_to_int must always produce sum == total."""
    import random

    rng = random.Random(42)
    for _ in range(50):
        vals = {k: rng.uniform(0, w) for k, w in zip("abcd", [35, 25, 20, 20])}
        total = max(0, min(100, round(sum(vals.values()))))
        result = _distribute_to_int(vals, total)
        assert sum(result.values()) == total


# ---------------------------------------------------------------------------
# Individual factor component ranges
# ---------------------------------------------------------------------------


def test_delinquency_cap() -> None:
    assert _delinquency_component(10) == W_DELINQUENCY
    assert _delinquency_component(100) == W_DELINQUENCY
    assert _delinquency_component(0) == 0.0


def test_violations_cap() -> None:
    assert _violations_component(5) == W_VIOLATIONS
    assert _violations_component(50) == W_VIOLATIONS
    assert _violations_component(0) == 0.0


def test_years_held_cap() -> None:
    assert _years_held_component(20.0) == W_YEARS_HELD
    assert _years_held_component(100.0) == W_YEARS_HELD
    assert _years_held_component(0.0) == 0.0
    assert _years_held_component(-5.0) == 0.0


def test_value_gap_below_median() -> None:
    assert _value_gap_component(0.0, 100_000.0) == pytest.approx(W_VALUE_GAP)


def test_value_gap_above_median() -> None:
    assert _value_gap_component(200_000.0, 100_000.0) == 0.0


def test_value_gap_no_data() -> None:
    assert _value_gap_component(None, 100_000.0) == 0.0
    assert _value_gap_component(100_000.0, None) == 0.0
    assert _value_gap_component(None, None) == 0.0
