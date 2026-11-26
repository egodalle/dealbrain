"""Address normalization and owner-name cleaning for the DealBrain dedupe pipeline."""

from __future__ import annotations

import re
import sys

import usaddress

# ---------------------------------------------------------------------------
# Abbreviation tables
# ---------------------------------------------------------------------------

_STREET_TYPE_ABBREVS: dict[str, str] = {
    "ST": "STREET",
    "AVE": "AVENUE",
    "BLVD": "BOULEVARD",
    "DR": "DRIVE",
    "RD": "ROAD",
    "LN": "LANE",
    "CT": "COURT",
    "PL": "PLACE",
    "TER": "TERRACE",
    "TERR": "TERRACE",
}

_DIRECTIONAL_ABBREVS: dict[str, str] = {
    "N": "NORTH",
    "S": "SOUTH",
    "E": "EAST",
    "W": "WEST",
    "NE": "NORTHEAST",
    "NW": "NORTHWEST",
    "SE": "SOUTHEAST",
    "SW": "SOUTHWEST",
}

_UNIT_TYPE_ABBREVS: dict[str, str] = {
    "APT": "APARTMENT",
    "STE": "SUITE",
    "FL": "FLOOR",
    "UNIT": "UNIT",
}

# Combined lookup used when expanding a token without component context.
_ALL_ABBREVS: dict[str, str] = {
    **_STREET_TYPE_ABBREVS,
    **_DIRECTIONAL_ABBREVS,
    **_UNIT_TYPE_ABBREVS,
}

_OWNER_NOISE_TOKENS: frozenset[str] = frozenset(
    {"LLC", "INC", "TRUST", "ESTATE", "ET", "AL", "THE", "A", "AN"}
)

_NON_ALNUM_RE = re.compile(r"[^A-Z0-9 ]")


def _expand(token: str, table: dict[str, str]) -> str:
    return table.get(token, token)


def normalize_address(raw: str) -> str:
    """Return canonical address string.

    Uppercases, strips punctuation, expands abbreviations, and re-joins
    components in canonical order using usaddress.tag().
    Falls back to a simple uppercase+strip when usaddress raises RepeatedLabelError.

    Raises ValueError for empty input.
    """
    if not raw or not raw.strip():
        raise ValueError("address must not be empty")

    upper = raw.upper().strip()
    # Strip punctuation (keep alphanumeric and spaces)
    cleaned = _NON_ALNUM_RE.sub(" ", upper)
    cleaned = " ".join(cleaned.split())  # collapse whitespace

    try:
        tagged, _ = usaddress.tag(cleaned)
    except usaddress.RepeatedLabelError:
        print(f"[normalize] RepeatedLabelError on {raw!r}; using fallback", file=sys.stderr)
        return _fallback_expand(cleaned)

    parts: list[str] = []

    house = tagged.get("AddressNumber", "")
    if house:
        parts.append(house)

    pre_dir = tagged.get("StreetNamePreDirectional", "")
    if pre_dir:
        parts.append(_expand(pre_dir, _DIRECTIONAL_ABBREVS))

    street = tagged.get("StreetName", "")
    if street:
        parts.append(street)

    post_type = tagged.get("StreetNamePostType", "")
    if post_type:
        parts.append(_expand(post_type, _STREET_TYPE_ABBREVS))

    post_dir = tagged.get("StreetNamePostDirectional", "")
    if post_dir:
        parts.append(_expand(post_dir, _DIRECTIONAL_ABBREVS))

    occ_type = tagged.get("OccupancyType", "")
    if occ_type:
        parts.append(_expand(occ_type, _UNIT_TYPE_ABBREVS))

    occ_id = tagged.get("OccupancyIdentifier", "")
    if occ_id:
        parts.append(occ_id)

    result = " ".join(p for p in parts if p)
    if not result:
        return _fallback_expand(cleaned)
    return result


def _fallback_expand(cleaned: str) -> str:
    """Token-by-token expansion used when usaddress fails."""
    tokens = [_ALL_ABBREVS.get(tok, tok) for tok in cleaned.split()]
    return " ".join(tokens)


def clean_owner(raw: str) -> str:
    """Return uppercase, punctuation-stripped, noise-token-removed owner string.

    Used only for similarity scoring — never stored.
    """
    if not raw:
        return ""
    upper = raw.upper().strip()
    # Expand & → AND
    upper = upper.replace("&", " AND ")
    # Strip non-alphanumeric
    cleaned = _NON_ALNUM_RE.sub(" ", upper)
    # Remove noise tokens
    tokens = [t for t in cleaned.split() if t not in _OWNER_NOISE_TOKENS]
    return " ".join(tokens)


def blocking_key(normalized: str) -> str | None:
    """Return 'HOUSENUMBER_FIRSTSTREETTOKEN' or None if unparseable."""
    if not normalized or not normalized.strip():
        return None
    try:
        tagged, _ = usaddress.tag(normalized)
    except usaddress.RepeatedLabelError:
        return None

    house = tagged.get("AddressNumber", "").strip()
    if not house:
        return None

    street = tagged.get("StreetName", "").strip()
    if not street:
        return None

    first_street_token = street.split()[0]
    return f"{house}_{first_street_token}"
