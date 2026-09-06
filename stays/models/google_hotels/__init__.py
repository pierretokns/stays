"""Models for interacting with the Google Hotels (Travel) API.

The filter classes here produce the request payload Google's
``batchexecute`` endpoint expects (pydantic models rendered as nested
lists).
"""

from stays.models.google_hotels.base import (
    Amenity,
    Brand,
    Currency,
    DateRange,
    GuestInfo,
    Location,
    MinGuestRating,
    PropertyType,
    SortBy,
)
from stays.models.google_hotels.detail import (
    HotelDetail,
    ProviderOfferSummary,
    RatePlan,
    Review,
    RoomType,
)
from stays.models.google_hotels.hotels import HotelSearchFilters
from stays.models.google_hotels.policy import (
    CancellationPolicy,
    CancellationPolicyKind,
)
from stays.models.google_hotels.result import (
    AmenityFlag,
    CategoryRating,
    HotelResult,
    NearbyPlace,
    NearbyTravelOption,
    Observation,
    RatingHistogram,
)

__all__ = [
    "AmenityFlag",
    "NearbyTravelOption",
    "ProviderOfferSummary",
    "Observation",
    "Amenity",
    "Brand",
    "CancellationPolicy",
    "CancellationPolicyKind",
    "CategoryRating",
    "Currency",
    "DateRange",
    "GuestInfo",
    "HotelDetail",
    "HotelResult",
    "HotelSearchFilters",
    "Location",
    "MinGuestRating",
    "NearbyPlace",
    "PropertyType",
    "RatePlan",
    "RatingHistogram",
    "Review",
    "RoomType",
    "SortBy",
]
