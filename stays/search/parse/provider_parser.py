"""Parse provider-specific rooms and their individual, observed rate options.

No room equivalence is inferred across providers. Header integers can be
provider IDs, so a header without a structured price is never sold as a rate.
"""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit

from stays.models.google_hotels.detail import ProviderOfferSummary, RatePlan, RoomType
from stays.models.google_hotels.policy import CancellationPolicy, CancellationPolicyKind
from stays.search.parse.policy_parser import _resolve_cancellation_date
from stays.search.parse.slots import (
    SLOT_HEADER_PROVIDER_NAME,
    SLOT_PROVIDER_HEADER,
    SLOT_RATE_CANCEL,
    SLOT_ROOM_RATES,
    ProviderEntryRaw,
    Tree,
    safe_get,
)

__all__ = ["_parse_provider_rate", "_parse_provider_rooms", "_parse_cancellation_tuple", "_cancel_from_rate_slot"]

# Confirmed in both the one-night NYC and three-night Lisbon detail captures.
_PROVIDER_ROOMS_INDEX = 7
_NIGHTLY_PRICE_INDEX = 4
_TOTAL_PRICE_INDEX = 5
_EXACT_AMOUNT_INDEX = 2
_DISPLAY_AMOUNT_INDEX = 4


def _parse_cancellation_tuple(
    n: Tree,
    *,
    reference_year: int | None = None,
    requested_check_in: date | None = None,
) -> CancellationPolicy | None:
    """Retain explicit free-cancellation evidence even if its date is unknown."""
    if not isinstance(n, list) or not n or n[0] is not True:
        return None
    date_text = n[1].strip() if len(n) > 1 and isinstance(n[1], str) else None
    time_text = n[2].strip() if len(n) > 2 and isinstance(n[2], str) else None
    if not date_text:
        return CancellationPolicy(kind=CancellationPolicyKind.FREE_CANCELLATION, deadline_time_text=time_text)
    free_until, inferred = _resolve_cancellation_date(
        date_text, reference_year=reference_year, requested_check_in=requested_check_in
    )
    description = f"Free cancellation until {date_text}"
    if time_text:
        description += f" {time_text}"
    return CancellationPolicy(
        kind=CancellationPolicyKind.FREE_UNTIL_DATE,
        free_until=free_until,
        description=description,
        deadline_time_text=time_text,
        date_inferred=inferred,
    )


def _cancel_from_rate_slot(
    cancel_raw: Tree,
    *,
    reference_year: int | None = None,
    requested_check_in: date | None = None,
) -> CancellationPolicy:
    """Only a literal false flag establishes the wire's non-refundable state."""
    if isinstance(cancel_raw, list) and cancel_raw:
        if cancel_raw[0] is False:
            return CancellationPolicy(kind=CancellationPolicyKind.NON_REFUNDABLE)
        result = _parse_cancellation_tuple(
            cancel_raw, reference_year=reference_year, requested_check_in=requested_check_in
        )
        if result is not None:
            return result
    return CancellationPolicy()


def _amount(value: object) -> int | float | None:
    """Accept wire numbers without rounding, currency-dependent cutoffs or bools."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or (isinstance(value, float) and not math.isfinite(value)):
        return None
    return value


def _offer_url(raw: object) -> str | None:
    """Retain the rate-specific link; a generic provider link is not equivalent."""
    if not isinstance(raw, str):
        return None
    if raw.startswith("/") and not raw.startswith("//"):
        return "https://www.google.com" + raw
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    return raw if parsed.scheme in {"https", "http"} and parsed.netloc else None


def _parse_provider_rooms(
    entry: ProviderEntryRaw,
    currency: str | None,
    *,
    currency_source: Literal["observed", "requested", "unknown"] = "unknown",
    reference_year: int | None = None,
    requested_check_in: date | None = None,
    source_path: list[int] | None = None,
) -> list[RoomType]:
    """Preserve every valid rate and the provider's actual room label."""
    if not isinstance(entry, list):
        return []
    provider = safe_get(entry, *SLOT_PROVIDER_HEADER, *SLOT_HEADER_PROVIDER_NAME)
    if not isinstance(provider, str) or not provider.strip():
        return []
    rooms_block = safe_get(entry, _PROVIDER_ROOMS_INDEX)
    if not isinstance(rooms_block, list):
        return []

    rooms: list[RoomType] = []
    for room_index, room_raw in enumerate(rooms_block):
        if not isinstance(room_raw, list):
            continue
        room_name = safe_get(room_raw, 0)
        room_path = [*(source_path or []), _PROVIDER_ROOMS_INDEX, room_index]
        raw_rates = safe_get(room_raw, *SLOT_ROOM_RATES)
        if not isinstance(raw_rates, list):
            continue
        rates: list[RatePlan] = []
        for rate_index, rate_raw in enumerate(raw_rates):
            if not isinstance(rate_raw, list):
                continue
            nightly = _amount(safe_get(rate_raw, _NIGHTLY_PRICE_INDEX, _EXACT_AMOUNT_INDEX))
            total = _amount(safe_get(rate_raw, _TOTAL_PRICE_INDEX, _EXACT_AMOUNT_INDEX))
            price = nightly
            basis: Literal["per_night", "total_stay", "unknown"] = "per_night"
            if price is None:
                price = _amount(safe_get(rate_raw, _NIGHTLY_PRICE_INDEX, _DISPLAY_AMOUNT_INDEX))
            if price is None and total is not None:
                price, basis = total, "total_stay"
            if price is None:
                continue
            exact = nightly if basis == "per_night" else total
            rates.append(
                RatePlan(
                    provider=provider,
                    price=price,
                    price_exact=Decimal(str(exact)) if exact is not None else None,
                    total_price=Decimal(str(total)) if total is not None else None,
                    price_basis=basis,
                    currency=currency,
                    currency_source=currency_source,
                    cancellation=_cancel_from_rate_slot(
                        safe_get(rate_raw, *SLOT_RATE_CANCEL),
                        reference_year=reference_year,
                        requested_check_in=requested_check_in,
                    ),
                    deeplink_url=_offer_url(safe_get(rate_raw, 0)),
                    source_path=[*room_path, *SLOT_ROOM_RATES, rate_index],
                )
            )
        if rates:
            # No cross-basis comparison: total-only offers follow nightly offers.
            rates.sort(key=lambda rate: (rate.price_basis != "per_night", rate.price))
            rooms.append(
                RoomType(
                    name=room_name if isinstance(room_name, str) and room_name.strip() else None,
                    source_path=room_path,
                    rates=rates,
                )
            )
    return rooms


def _parse_provider_rate(
    entry: ProviderEntryRaw,
    currency: str | None,
    *,
    reference_year: int | None = None,
    requested_check_in: date | None = None,
) -> RatePlan | None:
    """Legacy convenience returning the cheapest observed nightly provider rate.

    Detail parsing uses ``_parse_provider_rooms`` to retain room/refund variants.
    """
    rooms = _parse_provider_rooms(entry, currency, reference_year=reference_year, requested_check_in=requested_check_in)
    rates = [rate for room in rooms for rate in room.rates if rate.price_basis == "per_night"]
    return min(rates, key=lambda rate: rate.price) if rates else None


def _parse_provider_summary(
    entry: ProviderEntryRaw,
    currency: str | None,
    *,
    currency_source: Literal["observed", "requested", "unknown"] = "unknown",
    source_path: list[int] | None = None,
) -> ProviderOfferSummary | None:
    """Preserve display-only provider quotes without inventing room-rate terms.

    The September 2026 capture supplies summary entries at hotel[6][2][21].
    Provider[12][4] and [12][5] contain formatted nightly and stay price pairs;
    no numeric precision, room identity or verified tax labels accompany them.
    """
    if not isinstance(entry, list):
        return None
    provider = safe_get(entry, *SLOT_PROVIDER_HEADER, *SLOT_HEADER_PROVIDER_NAME)
    if not isinstance(provider, str) or not provider.strip():
        return None
    nightly = safe_get(entry, 12, 4)
    total = safe_get(entry, 12, 5)
    nightly_labels = [label for label in nightly if isinstance(label, str)] if isinstance(nightly, list) else []
    total_labels = [label for label in total if isinstance(label, str)] if isinstance(total, list) else []
    if not nightly_labels and not total_labels:
        return None
    return ProviderOfferSummary(
        provider=provider,
        nightly_price_labels=nightly_labels,
        total_price_labels=total_labels,
        currency=currency,
        currency_source=currency_source,
        deeplink_url=_offer_url(safe_get(entry, 0, 2)),
        source_path=source_path,
    )
