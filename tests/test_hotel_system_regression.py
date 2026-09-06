"""Replay a reduced real response from the Lisbon hotel-system audit.

The fixture retains the first room from each of three providers and all ten
of those rooms' offers. Tracking links and unrelated property data are removed.
See docs/hotel-system-integration.md for provenance and interpretation limits.
"""

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from stays import Currency, DateRange, GuestInfo, SearchHotels
from stays.mcp._executors import _serialize_hotel_detail as serialize_mcp_detail
from stays.serialize import serialize_hotel_detail


def test_real_detail_retains_dated_room_offers_and_provenance():
    inner = json.loads((Path(__file__).parent / "fixtures" / "lisbon_detail_audit.json").read_text())
    entry = inner["data"][0]
    client = MagicMock()
    client.post_rpc.return_value = inner
    guests = GuestInfo(adults=3, children=1, child_ages=[7])
    detail = SearchHotels(client=client).get_details(
        entity_key=entry[20],
        dates=DateRange(check_in=date(2026, 11, 10), check_out=date(2026, 11, 13)),
        currency=Currency.USD,
        guests=guests,
    )

    # Detail dates/currency exist even when the list-view price pair is absent.
    assert entry[6][1][0] is None
    assert detail.rate_dates == (date(2026, 11, 10), date(2026, 11, 13))
    assert detail.currency == "USD"
    assert detail.currency_source == "observed"
    assert len(detail.rooms) == 3
    assert [room.name for room in detail.rooms] == [
        "Double Room",
        "Double Room",
        "Standard Double - Standard rate Room Only",
    ]
    rates = [rate for room in detail.rooms for rate in room.rates]
    assert len(rates) == 10
    assert len({rate.deeplink_url for rate in rates}) == 10
    for rate in rates:
        assert rate.source_path
        raw = entry
        for index in rate.source_path:
            raw = raw[index]
        assert rate.deeplink_url == raw[0]
        assert rate.price_exact == Decimal(str(raw[4][2]))
        assert rate.total_price == Decimal(str(raw[5][2]))
        assert rate.price_basis == "per_night"
        assert rate.includes_taxes_and_fees is None

    first, refundable = detail.rooms[0].rates[:2]
    assert first.price_exact == Decimal("142.42")
    assert first.total_price == Decimal("427.26")
    assert first.cancellation.kind.value == "non_refundable"
    assert refundable.cancellation.kind.value == "free_until"
    assert refundable.cancellation.free_until == date(2026, 11, 7)
    assert refundable.cancellation.deadline_time_text == "11:59\u202fAM"
    assert refundable.cancellation.deadline_timezone is None
    assert refundable.cancellation.date_inferred is True

    observation = detail.observation
    assert observation is not None
    assert observation.requested_guests == guests
    assert observation.observed_guests is None
    assert observation.dates_match is True
    assert observation.currency_matches is True
    assert observation.fetched_at.utcoffset() == timedelta(0)
    assert len(observation.response_sha256) == 64
    assert "occupancy_not_verified" in observation.warnings

    canonical = serialize_hotel_detail(detail)
    mcp = serialize_mcp_detail(detail)
    assert canonical["rooms"][0]["rates"][0]["price_exact"] == "142.42"
    assert canonical["rooms"][0]["rates"][0]["total_price"] == "427.26"
    assert mcp["rate_dates"] == canonical["rate_dates"]
    assert mcp["observation"] == canonical["observation"]
    mcp_refundable = mcp["rooms"][0]["rates"][1]
    assert mcp_refundable["cancellation_deadline_time_text"] == "11:59\u202fAM"
    assert mcp_refundable["cancellation_deadline_timezone"] is None
