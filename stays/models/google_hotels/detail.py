"""Hotel detail-page models: rooms, rate plans, reviews.

Populated by SearchHotels.get_details() which hits AtySUc with an
entity_key in request slot [2][5]. The response carries a richer version
of the same 48-slot hotel entry that the search-list response uses.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, PositiveInt

from stays.models.google_hotels.policy import CancellationPolicy
from stays.models.google_hotels.result import HotelResult


class RatePlan(BaseModel):
    """One provider's observed rate; merchant availability and equivalence are unverified."""

    provider: str = Field(..., description='e.g. "Booking.com", "Hotels.com", "Expedia", "Direct (Marriott)"')
    price: int | float = Field(ge=0, allow_inf_nan=False)
    price_exact: Decimal | None = Field(None, ge=0, allow_inf_nan=False)
    total_price: Decimal | None = Field(None, ge=0, allow_inf_nan=False)
    price_basis: Literal["per_night", "total_stay", "unknown"] = "unknown"
    currency: str | None
    currency_source: Literal["observed", "requested", "unknown"] = "unknown"
    cancellation: CancellationPolicy = Field(default_factory=CancellationPolicy)
    breakfast_included: bool | None = None
    includes_taxes_and_fees: bool | None = None
    deeplink_url: str | None = None
    source_path: list[int] | None = None


class RoomType(BaseModel):
    """One provider's room label and rate variants; identical labels are not merged."""

    name: str | None
    source_path: list[int] | None = None
    description: str | None = None
    bed_config: str | None = Field(None, description='e.g. "1 King Bed", "2 Queen Beds"')
    max_occupancy: PositiveInt | None = None
    rates: list[RatePlan] = Field(
        default_factory=list,
        description="Provider-specific offers sorted within each price basis; room equivalence unverified.",
    )


class Review(BaseModel):
    """One user review surfaced in the detail response."""

    author_name: str | None = None
    rating: int = Field(..., ge=1, le=5)
    body: str
    review_date: date | None = None
    source: str | None = Field(None, description='e.g. "Google", "Booking.com"')


class ProviderOfferSummary(BaseModel):
    """Supplier display quotes without independently observed room or rate terms."""

    provider: str
    nightly_price_labels: list[str] = Field(default_factory=list)
    total_price_labels: list[str] = Field(default_factory=list)
    currency: str | None = None
    currency_source: Literal["observed", "requested", "unknown"] = "unknown"
    deeplink_url: str | None = None
    source_path: list[int] | None = None


class HotelDetail(HotelResult):
    """Full per-property record returned by SearchHotels.get_details().

    Extends HotelResult with fields only the detail response exposes
    (description, street address, phone, rooms + rate plans, amenity
    details, nearby attractions, sample reviews).
    """

    description: str | None = None
    address: str | None = None
    phone: str | None = None

    rooms: list[RoomType] = Field(default_factory=list)
    provider_summaries: list[ProviderOfferSummary] = Field(default_factory=list)

    amenity_details: list[str] = Field(
        default_factory=list,
        description="Human-readable amenity labels — supplements amenities_available bits.",
    )
    nearby_attractions: list[str] = Field(default_factory=list)
    recent_reviews: list[Review] = Field(
        default_factory=list,
        description="Only independently parseable reviews; chronology and source coverage are not guaranteed.",
    )
