"""Detail-mode parser — turns a single-hotel AtySUc response into ``HotelDetail``.

The detail response surfaces exactly one enriched hotel entry. We reuse
the shared hotel-entry walker (``_parse_hotel_entry``) and then extend with
fields only present in detail mode: street address, phone, full description,
human-readable amenity labels, and room/rate plans per provider.
"""

from __future__ import annotations

import html
import re
from datetime import date
from typing import Any

from stays.models.google_hotels.detail import (
    HotelDetail,
    Review,
    RoomType,
)
from stays.search.parse.provider_parser import _parse_provider_rooms, _parse_provider_summary
from stays.search.parse.search_parser import _find_hotel_entries, _parse_hotel_entry
from stays.search.parse.slots import (
    SLOT_ADDRESS,
    SLOT_AMENITY_DETAILS,
    SLOT_DESCRIPTION,
    SLOT_PHONE,
    SLOT_PROVIDER_BLOCK,
    SLOT_PROVIDER_LIST,
    SLOT_REVIEWS_LIST,
    Tree,
    safe_get,
)

__all__ = ["parse_detail_response"]

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def parse_detail_response(
    inner: Tree,
    *,
    reference_year: int | None = None,
    requested_currency: str | None = None,
    requested_check_in: date | None = None,
    expected_entity_key: str | None = None,
) -> HotelDetail:
    """Parse a single-hotel AtySUc detail response into a HotelDetail.

    The detail response surfaces exactly one enriched hotel entry. We
    reuse the shared hotel-entry walker and then extend with the fields
    only present in detail mode — street address, phone, full description,
    amenity group labels, and room/rate plans.

    The hotel entry is found via `_find_hotel_entries` (same heuristic as
    search). In detail mode there's typically only one matching entry; if
    multiple, ``expected_entity_key`` selects the requested property.

    Observed currency and stay dates take precedence over requested context.
    ``requested_currency`` labels rates only when no observed currency exists;
    the accompanying currency_source makes that assumption explicit.
    """
    entries = _find_hotel_entries(inner)
    if not entries:
        raise ValueError("parse_detail_response: no hotel entry found in response")
    entry = entries[0]
    base = _parse_hotel_entry(entry)
    if expected_entity_key is not None:
        for candidate in entries:
            parsed = _parse_hotel_entry(candidate)
            if parsed is not None and parsed.entity_key == expected_entity_key:
                entry, base = candidate, parsed
                break
        else:
            raise ValueError("parse_detail_response: requested hotel entity was not found in response")
    if base is None:
        raise ValueError("parse_detail_response: hotel entry failed to parse")
    detail_currency = base.currency or requested_currency
    currency_source = "observed" if base.currency else "requested" if requested_currency else "unknown"
    # Deadline-year inference uses observed offer dates when available.
    cutoff_check_in = base.rate_dates[0] if base.rate_dates else requested_check_in

    # Address: SLOT_ADDRESS = entry[2][1][0][0][0]
    addr_node = safe_get(entry, *SLOT_ADDRESS)
    address: str | None = addr_node if isinstance(addr_node, str) else None

    # Phone: SLOT_PHONE = entry[2][2][0]
    phone_node = safe_get(entry, *SLOT_PHONE)
    phone: str | None = phone_node if isinstance(phone_node, str) else None

    # Description (short): SLOT_DESCRIPTION = entry[11][0]
    description_node = safe_get(entry, *SLOT_DESCRIPTION)
    description: str | None = description_node if isinstance(description_node, str) else None

    # Keep provider-specific room records and each rate's own policy and link.
    # An identical label across suppliers is not proof of room equivalence.
    rooms: list[RoomType] = []
    providers_block = safe_get(entry, *SLOT_PROVIDER_BLOCK)
    if isinstance(providers_block, list):
        provider_list_entry = safe_get(entry, *SLOT_PROVIDER_LIST)
        if isinstance(provider_list_entry, list):
            for provider_index, provider_entry in enumerate(provider_list_entry):
                rooms.extend(
                    _parse_provider_rooms(
                        provider_entry,
                        detail_currency,
                        currency_source=currency_source,
                        reference_year=reference_year,
                        requested_check_in=cutoff_check_in,
                        source_path=[*SLOT_PROVIDER_LIST, provider_index],
                    )
                )

    # Newer responses may expose only provider-level price summaries, without
    # room names or precise rates. Keep these distinct from bookable room rates.
    provider_summaries = []
    summary_slot = 21
    summary_entries = safe_get(providers_block, summary_slot)
    if not isinstance(summary_entries, list) or not summary_entries:
        summary_slot = 22
        summary_entries = safe_get(providers_block, summary_slot)
    if isinstance(summary_entries, list):
        for provider_index, provider_entry in enumerate(summary_entries):
            summary = _parse_provider_summary(
                provider_entry,
                detail_currency,
                currency_source=currency_source,
                source_path=[*SLOT_PROVIDER_BLOCK, summary_slot, provider_index],
            )
            if summary is not None:
                provider_summaries.append(summary)

    # Amenity details: entry[10][0] contains grouped human-readable labels.
    # Other branches contain search-result snippets and business names, so
    # parse only the documented label records instead of recursively walking
    # every string in the subtree.
    pos10 = safe_get(entry, *SLOT_AMENITY_DETAILS)
    amenity_details = _parse_amenity_details(pos10)

    # Reviews sample from SLOT_REVIEWS_LIST = entry[7][3]
    recent_reviews: list[Review] = []
    reviews_block = safe_get(entry, *SLOT_REVIEWS_LIST)
    if isinstance(reviews_block, list):
        for review_entry in reviews_block[:5]:
            rv = _parse_review_entry(review_entry)
            if rv is not None:
                recent_reviews.append(rv)

    base_data = base.model_dump()
    base_data["currency_source"] = currency_source
    if detail_currency is not None:
        base_data["currency"] = detail_currency

    return HotelDetail(
        **base_data,
        description=description,
        address=address,
        phone=phone,
        rooms=rooms,
        provider_summaries=provider_summaries,
        amenity_details=amenity_details,
        recent_reviews=recent_reviews,
    )


def _parse_amenity_details(node: Any) -> list[str]:
    """Extract canonical amenity labels from the detail amenity subtree."""
    groups = safe_get(node, 0, default=[])
    if not isinstance(groups, list):
        return []

    labels: list[str] = []
    seen: set[str] = set()
    for group in groups:
        amenity_records = safe_get(group, 1, default=[])
        if not isinstance(amenity_records, list):
            continue
        for record in amenity_records:
            raw_label = safe_get(record, 0)
            if not isinstance(raw_label, str):
                continue
            label = _HTML_TAG_RE.sub("", html.unescape(raw_label))
            label = " ".join(label.split())
            key = label.casefold()
            if not label or key in seen:
                continue
            seen.add(key)
            labels.append(label)
            if len(labels) == 40:
                return labels

    return labels


def _parse_review_entry(entry: Tree) -> Review | None:
    """Do not turn unrated highlighted excerpts into dated or rated reviews.

    The observed entry[7][3] records contain text fragments, emphasis booleans,
    an avatar image and an author label. They have no review score or date.
    A recursive integer/string walk incorrectly treated True as a one-star
    rating and avatar URLs as review text. The Review model requires an actual
    score, so these snippets are deliberately excluded until a sourced review
    record with a verified layout is available.
    """
    return None
