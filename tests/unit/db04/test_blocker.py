"""Unit tests for blocking logic in pipelines/dedupe.py."""

from __future__ import annotations

from decimal import Decimal

from pipelines.dedupe import PropertyRow, build_blocks


def _make_row(
    parcel_id: str,
    address: str,
    owner: str = "",
) -> PropertyRow:
    return PropertyRow(
        parcel_id=parcel_id,
        address_raw=address,
        address_normalized=address,
        owner=owner,
        owner_1=None,
        owner_2=None,
        assessed_value=Decimal("100000"),
        created_at="2020-01-01T00:00:00+00:00",
    )


class TestBuildBlocks:
    def test_same_house_same_street_same_block(self) -> None:
        """Two addresses with same house number and first street token land in same block."""
        rows = [
            _make_row("A", "123 MAIN STREET"),
            _make_row("B", "123 MAIN STREET APARTMENT 2"),
        ]
        blocks = build_blocks(rows)
        # Both should share a block key
        for block in blocks.values():
            ids = [r.parcel_id for r in block]
            if "A" in ids:
                assert "B" in ids

    def test_different_house_numbers_different_blocks(self) -> None:
        """Two addresses with different house numbers land in different blocks."""
        rows = [
            _make_row("A", "100 MAIN STREET"),
            _make_row("B", "200 MAIN STREET"),
        ]
        blocks = build_blocks(rows)
        # Each should be in a different block (no block contains both)
        for block in blocks.values():
            ids = {r.parcel_id for r in block}
            assert not ({"A", "B"} <= ids), "A and B should not share a block"

    def test_empty_rows_produces_empty_blocks(self) -> None:
        """Empty input produces empty block dict."""
        assert build_blocks([]) == {}

    def test_single_row_produces_one_block(self) -> None:
        """A single row produces exactly one block."""
        rows = [_make_row("A", "123 ELM STREET")]
        blocks = build_blocks(rows)
        assert len(blocks) == 1
        for block in blocks.values():
            assert len(block) == 1

    def test_different_streets_same_house_different_blocks(self) -> None:
        """Same house number, different street → different blocks."""
        rows = [
            _make_row("A", "100 BROAD STREET"),
            _make_row("B", "100 MARKET STREET"),
        ]
        blocks = build_blocks(rows)
        for block in blocks.values():
            ids = {r.parcel_id for r in block}
            assert not ({"A", "B"} <= ids)

    def test_row_with_no_key_excluded(self) -> None:
        """A row with an unparseable address is excluded from blocks."""
        rows = [
            _make_row("A", "123 MAIN STREET"),
            # Empty address has no blocking key
            PropertyRow(
                parcel_id="BAD",
                address_raw="",
                address_normalized="",
                owner=None,
                owner_1=None,
                owner_2=None,
                assessed_value=Decimal("0"),
                created_at="2020-01-01T00:00:00+00:00",
            ),
        ]
        blocks = build_blocks(rows)
        for block in blocks.values():
            assert all(r.parcel_id != "BAD" for r in block)
