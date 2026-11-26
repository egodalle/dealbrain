"""Unit tests for pipelines/normalize.py — address normalization and owner cleaning."""

from __future__ import annotations

import pytest

from pipelines.normalize import blocking_key, clean_owner, normalize_address


class TestNormalizeAddress:
    def test_street_abbreviation_st(self) -> None:
        """'123 MAIN ST' should expand ST to STREET."""
        result = normalize_address("123 MAIN ST")
        assert "STREET" in result

    def test_street_abbreviation_avenue(self) -> None:
        """'456 OAK AVE' should expand AVE to AVENUE."""
        result = normalize_address("456 OAK AVE")
        assert "AVENUE" in result

    def test_normalize_north_broad_street(self) -> None:
        """'123 N BROAD ST' → '123 NORTH BROAD STREET'."""
        result = normalize_address("123 N BROAD ST")
        assert "NORTH" in result
        assert "BROAD" in result
        assert "STREET" in result
        assert "123" in result

    def test_normalize_south_avenue_with_unit(self) -> None:
        """'456 S 10TH AVE APT 2' should expand S, AVE, and APT."""
        result = normalize_address("456 S 10TH AVE APT 2")
        assert "SOUTH" in result
        assert "AVENUE" in result
        assert "APARTMENT" in result

    def test_unit_type_apt_expansion(self) -> None:
        """APT should expand to APARTMENT."""
        result = normalize_address("100 MAIN ST APT 3B")
        assert "APARTMENT" in result

    def test_unit_type_ste_expansion(self) -> None:
        """STE should expand to SUITE."""
        result = normalize_address("200 MARKET ST STE 100")
        assert "SUITE" in result

    def test_unit_type_fl_expansion(self) -> None:
        """FL should expand to FLOOR."""
        result = normalize_address("300 WALNUT ST FL 4")
        assert "FLOOR" in result

    def test_raises_on_empty_string(self) -> None:
        """Empty string should raise ValueError."""
        with pytest.raises(ValueError):
            normalize_address("")

    def test_raises_on_whitespace_only(self) -> None:
        """Whitespace-only string should raise ValueError."""
        with pytest.raises(ValueError):
            normalize_address("   ")

    def test_lowercased_input_normalized(self) -> None:
        """Lowercase input should be uppercased in result."""
        result = normalize_address("123 main st")
        assert result == result.upper()

    def test_house_number_extracted(self) -> None:
        """House number must appear in normalized output."""
        result = normalize_address("742 EVERGREEN TERRACE")
        assert "742" in result

    def test_blvd_expansion(self) -> None:
        """BLVD should expand to BOULEVARD."""
        result = normalize_address("500 SUNSET BLVD")
        assert "BOULEVARD" in result

    def test_rd_expansion(self) -> None:
        """RD should expand to ROAD."""
        result = normalize_address("99 OLD PINE RD")
        assert "ROAD" in result

    def test_dr_expansion(self) -> None:
        """DR should expand to DRIVE."""
        result = normalize_address("12 LAKEVIEW DR")
        assert "DRIVE" in result


class TestBlockingKey:
    def test_format_house_underscore_street(self) -> None:
        """Blocking key format is HOUSENUMBER_FIRSTSTREETTOKEN."""
        key = blocking_key("123 MAIN STREET")
        assert key == "123_MAIN"

    def test_format_with_directional(self) -> None:
        """Street name token (not directional) is used for the key."""
        # usaddress will tag "BROAD" as StreetName
        key = blocking_key("123 NORTH BROAD STREET")
        assert key is not None
        assert key.startswith("123_")

    def test_none_on_empty_input(self) -> None:
        """Empty string returns None."""
        assert blocking_key("") is None

    def test_none_on_whitespace(self) -> None:
        """Whitespace-only returns None."""
        assert blocking_key("   ") is None

    def test_different_houses_produce_different_keys(self) -> None:
        """Different house numbers must produce different keys."""
        k1 = blocking_key("100 MAIN STREET")
        k2 = blocking_key("200 MAIN STREET")
        assert k1 != k2

    def test_same_house_same_street_same_key(self) -> None:
        """Same house + street → same key regardless of trailing content."""
        k1 = blocking_key("123 MAIN STREET")
        k2 = blocking_key("123 MAIN STREET APARTMENT 2")
        assert k1 == k2


class TestCleanOwner:
    def test_strips_llc(self) -> None:
        """LLC should be removed from owner string."""
        result = clean_owner("ACME REALTY LLC")
        assert "LLC" not in result
        assert "ACME" in result
        assert "REALTY" in result

    def test_strips_inc(self) -> None:
        """INC should be removed."""
        result = clean_owner("SUNRISE PROPERTIES INC")
        assert "INC" not in result

    def test_strips_trust(self) -> None:
        """TRUST should be removed."""
        result = clean_owner("SMITH FAMILY TRUST")
        assert "TRUST" not in result

    def test_strips_estate(self) -> None:
        """ESTATE should be removed."""
        result = clean_owner("ESTATE OF JOHN SMITH")
        assert "ESTATE" not in result

    def test_expands_ampersand(self) -> None:
        """& should be replaced with AND."""
        result = clean_owner("SMITH & JONES")
        assert "AND" in result

    def test_uppercase(self) -> None:
        """Result is always uppercase."""
        result = clean_owner("John Smith")
        assert result == result.upper()

    def test_empty_input_returns_empty(self) -> None:
        """Empty string returns empty string."""
        assert clean_owner("") == ""

    def test_punctuation_stripped(self) -> None:
        """Punctuation chars are stripped."""
        result = clean_owner("SMITH, JOHN")
        assert "," not in result
