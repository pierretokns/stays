"""Public SearchHotels API.

Detail architecture: there is NO separate detail RPC — `AtySUc` handles
both search (entity_key absent) and detail (entity_key present at outer
slot [2][5]). get_details() builds a HotelSearchFilters with entity_key
set; the filter's format() produces the final request shape with
entity_key at outer [2][5].
"""

from __future__ import annotations

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from stays.models.google_hotels.base import Currency, DateRange, GuestInfo, Location, SortBy
from stays.models.google_hotels.detail import HotelDetail
from stays.models.google_hotels.hotels import RPC_ID, HotelSearchFilters
from stays.models.google_hotels.result import HotelResult, Observation
from stays.search.client import (
    BatchExecuteError,
    Client,
    TransientBatchExecuteError,
    get_client,
)
from stays.search.parse import parse_detail_response, parse_search_response

logger = logging.getLogger(__name__)

ErrorKind = Literal["transient", "fatal"]


def _attach_observation(result: HotelResult, filters: HotelSearchFilters, digest: str, fetched_at: datetime) -> None:
    """Keep requested context separate from response evidence, including unknown occupancy."""
    observed_dates = None
    if result.rate_dates:
        observed_dates = DateRange(check_in=result.rate_dates[0], check_out=result.rate_dates[1])
    observed_currency = result.currency if result.currency_source == "observed" else None
    dates_match = observed_dates == filters.dates if observed_dates and filters.dates else None
    currency_matches = observed_currency == filters.currency.value if observed_currency else None
    warnings = ["occupancy_not_verified", "merchant_availability_not_verified"]
    if result.amenity_flags:
        warnings.append("amenity_codes_unmapped")
    if any(place.mode is None for place in result.nearby):
        warnings.append("travel_modes_unmapped")
    if isinstance(result, HotelDetail) and not result.rooms:
        warnings.append("no_room_rate_offers_parsed")
    if dates_match is False:
        warnings.append("date_mismatch")
    elif dates_match is None:
        warnings.append("dates_not_verified")
    if currency_matches is False:
        warnings.append("currency_mismatch")
    elif currency_matches is None:
        warnings.append("currency_not_verified")
    if filters.guests.children:
        warnings.append("child_ages_sent_as_buckets")
    result.observation = Observation(
        fetched_at=fetched_at,
        response_sha256=digest,
        requested_dates=filters.dates,
        requested_guests=filters.guests.model_copy(deep=True),
        requested_currency=filters.currency.value,
        observed_dates=observed_dates,
        observed_currency=observed_currency,
        dates_match=dates_match,
        currency_matches=currency_matches,
        warnings=warnings,
    )


def _response_digest(response: list) -> str:
    canonical = json.dumps(response, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _apply_post_sort(results: list[HotelResult], sort_by: SortBy | None) -> list[HotelResult]:
    """Stable-sort parsed results so explicit sort_by produces monotonic output.

    Google's own response order is usually mostly-sorted but has minor
    reorderings within same-price groups (likely pre-tax base rate vs.
    display-rounded USD). Post-sorting guarantees strict monotonicity
    on the requested key. RELEVANCE / None is a no-op.

    Missing values (``None``) always fall to the end so callers reading
    the top of the list still see well-ranked hotels. Ties preserve
    Google's order via Python's stable sort.
    """
    if sort_by is None or sort_by is SortBy.RELEVANCE:
        return results
    if sort_by is SortBy.LOWEST_PRICE:
        return sorted(
            results,
            key=lambda h: (h.display_price is None, h.display_price if h.display_price is not None else 0),
        )
    if sort_by is SortBy.HIGHEST_RATING:
        return sorted(
            results,
            key=lambda h: (h.overall_rating is None, -(h.overall_rating or 0.0)),
        )
    if sort_by is SortBy.MOST_REVIEWED:
        return sorted(
            results,
            key=lambda h: (h.review_count is None, -(h.review_count or 0)),
        )
    return results


class MissingHotelIdError(ValueError):
    """Raised by get_details() when the caller passed an empty / None
    entity_key. Prevents no-op requests hitting the wire."""


@dataclass
class EnrichedResult:
    """Result of one hotel in a ``search_with_details`` call.

    Exactly one of ``detail`` or ``error`` is set:
      * ``detail`` is populated when the detail RPC succeeded for this hotel.
      * ``error`` carries a human-readable message when we skipped or
        failed this hotel. ``error_kind`` classifies the failure so
        retry-aware callers can decide whether to re-issue the request.
        ``result`` is always the list-view record (so callers still
        get name / price / rating even when details fail).
    """

    result: HotelResult
    detail: HotelDetail | None = None
    error: str | None = None
    error_kind: ErrorKind | None = None

    @property
    def ok(self) -> bool:
        return self.detail is not None

    @property
    def is_retryable(self) -> bool:
        """True iff this hotel's failure was transient (retrying may
        succeed). Returns False for fatal errors and for successful
        items — only ``error_kind == "transient"`` is retryable."""
        return self.error_kind == "transient"


class SearchHotels:
    """High-level search API.

    Example::

        from datetime import date
        from stays import HotelSearchFilters, Location, DateRange, GuestInfo, Currency
        from stays.search import SearchHotels

        s = SearchHotels()
        results = s.search(HotelSearchFilters(
            location=Location(query="new york hotels"),
            dates=DateRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4)),
        ))

        if results[0].entity_key:
            details = s.get_details(
                entity_key=results[0].entity_key,
                dates=DateRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4)),
            )
            for room in details.rooms:
                print(room.name, [(rp.provider, rp.price) for rp in room.rates])
    """

    def __init__(
        self,
        client: Client | None = None,
        detail_concurrency: int = 4,
    ) -> None:
        self._client = client or get_client()
        self._detail_concurrency = max(1, detail_concurrency)

    def search(self, filters: HotelSearchFilters) -> list[HotelResult]:
        filters = filters.model_copy(deep=True)
        inner_req = filters.format()
        inner_resp = self._client.post_rpc(RPC_ID, inner_req)
        fetched_at = datetime.now(timezone.utc)
        results = parse_search_response(inner_resp)
        digest = _response_digest(inner_resp)
        for result in results:
            _attach_observation(result, filters, digest, fetched_at)
        return _apply_post_sort(results, filters.sort_by)

    def get_details(
        self,
        entity_key: str,
        dates: DateRange,
        *,
        location: Location | None = None,
        currency: Currency = Currency.USD,
        guests: GuestInfo | None = None,
    ) -> HotelDetail:
        """Fetch full detail for one hotel.

        ``entity_key`` is the base64 identifier from
        ``HotelResult.entity_key``. ``dates`` are required because the
        response-side rate plans are computed for the date window.

        Detail requests always use the neutral query "hotels". A discovery
        city query can suppress room-rate blocks even for a valid entity key.
        ``location`` is retained as a deprecated compatibility argument and
        ignored; the entity key identifies the property.

        Returns a ``HotelDetail`` with rooms, rate plans, cancellation
        policies (when resolvable), description, amenities, reviews.
        """
        if not entity_key or not isinstance(entity_key, str):
            raise MissingHotelIdError(f"get_details: entity_key must be a non-empty str; got {entity_key!r}")
        dates = DateRange.model_validate(dates.model_dump())
        filters = HotelSearchFilters(
            location=Location(query="hotels"),
            dates=dates,
            currency=currency,
            guests=(guests or GuestInfo()).model_copy(deep=True),
            entity_key=entity_key,
        )
        inner_req = filters.format()
        inner_resp = self._client.post_rpc(RPC_ID, inner_req)
        fetched_at = datetime.now(timezone.utc)
        try:
            detail = parse_detail_response(
                inner_resp,
                requested_check_in=dates.check_in,
                requested_currency=currency.value,
                expected_entity_key=entity_key,
            )
        except ValueError as exc:
            raise BatchExecuteError(f"Invalid detail response: {exc}") from exc
        _attach_observation(detail, filters, _response_digest(inner_resp), fetched_at)
        return detail

    def search_with_details(self, filters: HotelSearchFilters, max_hotels: int = 5) -> list[EnrichedResult]:
        """Run ``search()``, then fetch detail for the first
        ``max_hotels`` results in parallel. Partial failures are reported
        per-hotel via ``EnrichedResult.error``; the batch never aborts
        on a single transient."""
        filters = filters.model_copy(deep=True)
        if filters.dates is None:
            raise ValueError(
                "search_with_details requires filters.dates so that detail "
                "responses can carry rate plans. Set dates on your HotelSearchFilters."
            )
        if not 1 <= max_hotels <= 15:
            raise ValueError("max_hotels must be between 1 and 15")
        results = self.search(filters)
        top = results[:max_hotels]
        workers = min(self._detail_concurrency, max(1, len(top)))
        logger.info("enrich count=%d concurrency=%d", len(top), workers)

        def enrich_one(r: HotelResult) -> EnrichedResult:
            if not r.entity_key:
                logger.warning(
                    "enrich error hotel=%s kind=%s msg=%s",
                    r.name,
                    "fatal",
                    "missing entity_key",
                )
                return EnrichedResult(
                    result=r,
                    error="missing entity_key",
                    error_kind="fatal",
                )
            try:
                detail = self.get_details(
                    entity_key=r.entity_key,
                    dates=filters.dates,
                    currency=filters.currency,
                    guests=filters.guests,
                )
                return EnrichedResult(result=r, detail=detail)
            except TransientBatchExecuteError as e:
                logger.warning(
                    "enrich error hotel=%s kind=%s msg=%s",
                    r.name,
                    "transient",
                    f"{type(e).__name__}: {e}",
                )
                return EnrichedResult(
                    result=r,
                    error=f"{type(e).__name__}: {e}",
                    error_kind="transient",
                )
            except (BatchExecuteError, MissingHotelIdError) as e:
                logger.warning(
                    "enrich error hotel=%s kind=%s msg=%s",
                    r.name,
                    "fatal",
                    f"{type(e).__name__}: {e}",
                )
                return EnrichedResult(
                    result=r,
                    error=f"{type(e).__name__}: {e}",
                    error_kind="fatal",
                )
            # Unknown exceptions intentionally NOT caught — they propagate
            # so parser bugs / programmer errors surface instead of being
            # silently stringified into per-hotel error fields.

        with ThreadPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(enrich_one, top))
