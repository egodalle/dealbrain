"""Unit tests for matching, union-find, and idempotency in pipelines/dedupe.py."""

from __future__ import annotations

from decimal import Decimal

from pipelines.dedupe import (
    MERGE_THRESHOLD,
    PropertyRow,
    build_components,
    match_block,
    score_pair,
)
from pipelines.normalize import clean_owner


def _row(
    parcel_id: str,
    address: str,
    owner: str = "",
    assessed_value: str = "100000",
) -> PropertyRow:
    return PropertyRow(
        parcel_id=parcel_id,
        address_raw=address,
        address_normalized=address,
        owner=owner,
        owner_1=None,
        owner_2=None,
        assessed_value=Decimal(assessed_value),
        created_at="2020-01-01T00:00:00+00:00",
    )


class TestScorePair:
    def test_identical_addresses_score_one(self) -> None:
        """Identical address + owner should score 1.0 combined."""
        a = _row("A", "123 MAIN STREET", "SMITH JOHN")
        b = _row("B", "123 MAIN STREET", "SMITH JOHN")
        score, _ = score_pair(a, b)
        assert score == 1.0

    def test_different_addresses_score_below_threshold(self) -> None:
        """Clearly different addresses score below 0.85."""
        a = _row("A", "100 BROAD STREET", "SMITH JOHN")
        b = _row("B", "999 MARKET AVENUE", "JONES MARY")
        score, _ = score_pair(a, b)
        assert score < MERGE_THRESHOLD

    def test_reversed_name_still_matches(self) -> None:
        """'SMITH JOHN' vs 'JOHN SMITH' on same address should exceed threshold."""
        a = _row("A", "123 MAIN STREET", "SMITH JOHN")
        b = _row("B", "123 MAIN STREET", "JOHN SMITH")
        score, _ = score_pair(a, b)
        assert score >= MERGE_THRESHOLD

    def test_matched_on_both_when_both_exceed(self) -> None:
        """When both address and owner independently exceed threshold, matched_on='both'."""
        a = _row("A", "123 MAIN STREET", "SMITH JOHN")
        b = _row("B", "123 MAIN STREET", "SMITH JOHN")
        _, matched_on = score_pair(a, b)
        assert matched_on == "both"

    def test_matched_on_address_when_no_owner(self) -> None:
        """When owners are empty, matched_on='address'."""
        a = _row("A", "123 MAIN STREET", "")
        b = _row("B", "123 MAIN STREET", "")
        _, matched_on = score_pair(a, b)
        assert matched_on == "address"


class TestMatchBlock:
    def test_high_similarity_pair_returned(self) -> None:
        """Two nearly-identical records → returned as a pair."""
        block = [
            _row("A", "123 MAIN STREET", "SMITH JOHN"),
            _row("B", "123 MAIN STREET", "JOHN SMITH"),
        ]
        pairs = match_block(block)
        pair_ids = {(a, b) for a, b, _ in pairs}
        assert ("A", "B") in pair_ids or ("B", "A") in pair_ids

    def test_low_similarity_pair_not_returned(self) -> None:
        """Two clearly different records → not returned as a pair."""
        block = [
            _row("A", "100 BROAD STREET", "SMITH JOHN"),
            _row("B", "999 MARKET AVENUE", "JONES MARY"),
        ]
        pairs = match_block(block)
        assert len(pairs) == 0

    def test_single_row_block_returns_no_pairs(self) -> None:
        """A block with one row produces no pairs."""
        block = [_row("A", "123 MAIN STREET", "SMITH JOHN")]
        assert match_block(block) == []


class TestBuildComponents:
    def test_connected_pair_in_one_component(self) -> None:
        """Two directly connected nodes form one component."""
        components = build_components(["A", "B"], [("A", "B")])
        all_members = list(components.values())
        assert any(set(m) == {"A", "B"} for m in all_members)

    def test_transitive_merge_into_one_component(self) -> None:
        """A-B and B-C edges → A, B, C in one component."""
        components = build_components(["A", "B", "C"], [("A", "B"), ("B", "C")])
        all_members = list(components.values())
        assert any(set(m) == {"A", "B", "C"} for m in all_members)

    def test_no_edges_produces_singletons(self) -> None:
        """No edges → each node is its own component."""
        components = build_components(["A", "B", "C"], [])
        assert len(components) == 3

    def test_union_find_idempotent(self) -> None:
        """Running build_components twice on the same input produces the same structure."""
        parcel_ids = ["A", "B", "C"]
        edges = [("A", "B"), ("B", "C")]
        c1 = build_components(parcel_ids, edges)
        c2 = build_components(parcel_ids, edges)
        # Same number of components and same membership sets
        sets1 = {frozenset(v) for v in c1.values()}
        sets2 = {frozenset(v) for v in c2.values()}
        assert sets1 == sets2


class TestCleanOwnerInMatcher:
    def test_llc_stripped(self) -> None:
        """LLC is stripped from owner, so 'ACME LLC' and 'ACME' score identically."""
        from rapidfuzz import fuzz

        clean_a = clean_owner("ACME REALTY LLC")
        clean_b = clean_owner("ACME REALTY")
        score = fuzz.token_sort_ratio(clean_a, clean_b) / 100.0
        assert score >= 0.95

    def test_trust_stripped(self) -> None:
        """TRUST is stripped so 'SMITH FAMILY TRUST' ≈ 'SMITH FAMILY'."""
        from rapidfuzz import fuzz

        clean_a = clean_owner("SMITH FAMILY TRUST")
        clean_b = clean_owner("SMITH FAMILY")
        score = fuzz.token_sort_ratio(clean_a, clean_b) / 100.0
        assert score >= 0.95

    def test_inc_stripped(self) -> None:
        """INC is stripped."""
        result = clean_owner("HORIZON PROPERTIES INC")
        assert "INC" not in result


class TestEvalPrecisionRecall:
    """Run the eval script logic against the fixture and assert metrics >= 0.80."""

    def test_eval_precision_recall(self) -> None:
        from evals.dedupe.run_eval import FIXTURE_PATH, run_eval

        assert FIXTURE_PATH.exists(), f"Fixture not found: {FIXTURE_PATH}"
        precision, recall, f1 = run_eval(FIXTURE_PATH)
        assert precision >= 0.80, f"Precision {precision:.4f} < 0.80"
        assert recall >= 0.80, f"Recall {recall:.4f} < 0.80"
        assert f1 >= 0.80, f"F1 {f1:.4f} < 0.80"
