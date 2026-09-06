"""Regression coverage for evidence-preserving hotel offers and policy parsing."""

import copy
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from stays.models.google_hotels.policy import CancellationPolicyKind
from stays.search.parse.detail_parser import _parse_review_entry, parse_detail_response
from stays.search.parse.policy_parser import _parse_cancellation
from stays.search.parse.provider_parser import _cancel_from_rate_slot, _parse_cancellation_tuple, _parse_provider_rooms
from stays.search.parse.search_parser import _find_hotel_entries
from stays.search.parse.slots import safe_get

FX = Path(__file__).parent / "fixtures"


def _load(name="lisbon_detail_audit.json"):
    return json.loads((FX / name).read_text())


def _provider():
    return copy.deepcopy(_find_hotel_entries(_load())[0][6][2][2][0])


def test_captured_lisbon_room_variants_and_exact_prices_survive():
    raw = _load()
    detail = parse_detail_response(raw)
    assert len(detail.rooms) == 3
    assert sum(len(room.rates) for room in detail.rooms) == 10
    assert [room.name for room in detail.rooms] == [
        "Double Room",
        "Double Room",
        "Standard Double - Standard rate Room Only",
    ]
    first = detail.rooms[0].rates[0]
    assert first.price == 142.42
    assert first.price_exact == Decimal("142.42")
    assert first.total_price == Decimal("427.26")
    assert first.price_basis == "per_night"
    assert first.breakfast_included is None
    assert first.includes_taxes_and_fees is None
    assert detail.rooms[0].rates[1].cancellation.kind == CancellationPolicyKind.FREE_UNTIL_DATE
    assert detail.rooms[0].rates[1].cancellation.free_until == date(2026, 11, 7)


def test_all_captured_nyc_offers_retained_with_real_room_labels():
    detail = parse_detail_response(_load("detail_response_sample.json"))
    assert len(detail.rooms) == 82
    assert sum(len(room.rates) for room in detail.rooms) == 103
    assert "Standard Queen Room" in {room.name for room in detail.rooms}
    booking = next(room for room in detail.rooms if room.name == "Standard Queen Room")
    assert booking.rates[0].price_exact == Decimal("158.15")


def test_each_offer_links_to_its_own_source_and_deeplink():
    raw = _load()
    entry = _find_hotel_entries(raw)[0]
    detail = parse_detail_response(raw)
    all_urls = []
    for room in detail.rooms:
        assert safe_get(entry, *room.source_path, 0) == room.name
        for rate in room.rates:
            wire = safe_get(entry, *rate.source_path)
            assert rate.deeplink_url == wire[0]
            assert rate.price_exact == Decimal(str(wire[4][2]))
            all_urls.append(rate.deeplink_url)
    assert len(set(all_urls)) == 10


def test_header_provider_id_is_never_a_fallback_price():
    provider = _provider()
    provider[0][1] = 89
    provider[7] = []
    assert _parse_provider_rooms(provider, "USD") == []


def test_unknown_room_and_missing_rate_url_do_not_invent_facts():
    provider = _provider()
    provider[7][0][0] = None
    provider[7][0][2][0][0] = None
    rooms = _parse_provider_rooms(provider, None)
    assert rooms[0].name is None
    assert rooms[0].rates[0].deeplink_url is None
    assert rooms[0].rates[0].currency is None
    assert rooms[0].rates[0].currency_source == "unknown"


@pytest.mark.parametrize("bad", [True, False, float("nan"), float("inf"), -1, "142.42"])
def test_invalid_prices_do_not_become_bookable_rates(bad):
    provider = _provider()
    rate = provider[7][0][2][0]
    provider[7][0][2] = [rate]
    rate[4][2] = bad
    rate[4][4] = bad
    rate[5][2] = bad
    assert _parse_provider_rooms(provider, "USD") == []


def test_prices_below_twenty_are_not_discarded():
    provider = _provider()
    provider[7][0][2] = [provider[7][0][2][0]]
    provider[7][0][2][0][4][2] = 9.125
    rooms = _parse_provider_rooms(provider, "KWD")
    assert rooms[0].rates[0].price_exact == Decimal("9.125")


def test_total_only_offer_keeps_its_explicit_basis():
    provider = _provider()
    rate = provider[7][0][2][0]
    provider[7][0][2] = [rate]
    rate[4] = None
    result = _parse_provider_rooms(provider, "USD")[0].rates[0]
    assert result.price_basis == "total_stay"
    assert result.price_exact == result.total_price == Decimal("427.26")


@pytest.mark.parametrize("raw", [None, [], [None], [0], [1], ["false"], ["unexpected"]])
def test_unknown_cancellation_is_not_non_refundable(raw):
    assert _cancel_from_rate_slot(raw).kind == CancellationPolicyKind.UNKNOWN


def test_unparsed_free_deadline_retains_evidence_and_does_not_invent_year():
    policy = _parse_cancellation_tuple([True, "Nov 7", "11:59 PM"])
    assert policy.kind == CancellationPolicyKind.FREE_UNTIL_DATE
    assert policy.free_until is None
    assert policy.deadline_time_text == "11:59 PM"
    assert policy.deadline_timezone is None
    assert policy.date_inferred is False
    assert "Nov 7" in policy.description
    invalid = _parse_cancellation_tuple([True, "unrecognized", "11:59 PM"])
    assert invalid.kind != CancellationPolicyKind.NON_REFUNDABLE
    assert invalid.free_until is None


def test_new_year_cancellation_uses_previous_december_and_marks_inference():
    policy = _parse_cancellation_tuple([True, "Dec 31", "11:59 PM"], requested_check_in=date(2027, 1, 2))
    assert policy.free_until == date(2026, 12, 31)
    assert policy.date_inferred is True


def test_conflicting_cutoff_does_not_jump_back_a_year():
    policy = _parse_cancellation_tuple([True, "Jul 20"], requested_check_in=date(2027, 7, 15))
    assert policy.free_until is None


def test_explicit_date_and_time_are_preserved_without_inference():
    policy = _parse_cancellation("Free cancellation until Dec 31, 2026 11:59 PM")
    assert policy.free_until == date(2026, 12, 31)
    assert policy.deadline_time_text == "11:59 PM"
    assert policy.deadline_timezone is None
    assert policy.date_inferred is False


@pytest.mark.parametrize("label", ["No free cancellation", "Free cancellation is not available"])
def test_negated_free_cancellation_is_not_marked_free(label):
    assert _parse_cancellation(label).kind == CancellationPolicyKind.UNKNOWN


def test_detail_selects_requested_entity_and_rejects_wrong_property():
    raw = _load()
    wanted = parse_detail_response(raw).entity_key
    other = _find_hotel_entries(_load("detail_response_sample.json"))[0]
    combined = [other, _find_hotel_entries(raw)[0]]
    assert parse_detail_response(combined, expected_entity_key=wanted).entity_key == wanted
    with pytest.raises(ValueError, match="requested hotel entity"):
        parse_detail_response(raw, expected_entity_key="different-hotel")


def test_observed_dates_and_currency_override_request_assumptions():
    detail = parse_detail_response(_load(), requested_currency="EUR", requested_check_in=date(2027, 1, 1))
    assert detail.currency == "USD"
    assert detail.currency_source == "observed"
    rate = detail.rooms[0].rates[1]
    assert rate.currency_source == "observed"
    assert rate.cancellation.free_until == date(2026, 11, 7)


def test_highlighted_review_snippets_do_not_become_one_star_avatar_reviews():
    snippet = [
        [["Beautiful ", False], ["spa", True], [" with clean rooms", False]],
        ["https://example.com/a-very-long-avatar-image-url-which-is-not-review-text.png", 40, 40],
        "Traveler",
    ]
    assert _parse_review_entry(snippet) is None
    assert parse_detail_response(_load("detail_response_sample.json")).recent_reviews == []


def test_currency_absence_stays_unknown_or_explicitly_requested():
    raw = _load()
    _find_hotel_entries(raw)[0][6][1][3] = None
    unknown = parse_detail_response(raw)
    assert unknown.currency is None
    assert unknown.rooms[0].rates[0].currency is None
    assert unknown.currency_source == "unknown"
    requested = parse_detail_response(raw, requested_currency="EUR")
    assert requested.currency == "EUR"
    assert requested.rooms[0].rates[0].currency_source == "requested"


def test_relative_offer_url_resolves_to_google_not_header():
    provider = _provider()
    provider[7][0][2][0][0] = "/travel/clk?rate=specific"
    rate = _parse_provider_rooms(provider, "USD")[0].rates[0]
    assert rate.deeplink_url == "https://www.google.com/travel/clk?rate=specific"


def test_live_provider_summary_format_preserves_27_without_promoted_duplicates():
    detail = parse_detail_response(_load("lisbon_provider_summaries.json"))
    assert detail.rooms == []
    assert len(detail.provider_summaries) == 27
    first, second = detail.provider_summaries[:2]
    assert first.provider == "Iberostar Selection Lisboa"
    assert first.nightly_price_labels == ["$118", "$145"]
    assert first.total_price_labels == ["$354", "$435"]
    assert second.provider == "Evendo"
    assert second.nightly_price_labels == ["$110", "$125"]
    assert second.total_price_labels == ["$329", "$376"]
    assert first.currency == "USD"
    assert first.currency_source == "observed"
    assert first.deeplink_url == "https://example.invalid/provider-summary/0"
    assert first.source_path == [6, 2, 21, 0]
    assert not hasattr(first, "price_exact")
    assert not hasattr(first, "cancellation")


def test_summary_source_paths_resolve_to_observed_labels():
    raw = _load("lisbon_provider_summaries.json")
    entry = _find_hotel_entries(raw)[0]
    for summary in parse_detail_response(raw).provider_summaries:
        wire = safe_get(entry, *summary.source_path)
        assert summary.provider == wire[0][0]
        assert summary.nightly_price_labels == wire[12][4]
        assert summary.total_price_labels == wire[12][5]
        assert summary.deeplink_url == wire[0][2]


def test_promoted_summaries_are_used_only_when_main_list_absent():
    raw = _load("lisbon_provider_summaries.json")
    entry = _find_hotel_entries(raw)[0]
    entry[6][2][21] = None
    detail = parse_detail_response(raw)
    assert len(detail.provider_summaries) == 2
    assert detail.provider_summaries[0].source_path == [6, 2, 22, 0]
    assert detail.rooms == []


def test_summary_requires_observed_price_labels_not_provider_id():
    raw = _load("lisbon_provider_summaries.json")
    entry = _find_hotel_entries(raw)[0]
    for provider in entry[6][2][21]:
        provider[12] = None
    assert parse_detail_response(raw).provider_summaries == []


@pytest.mark.parametrize(
    "label",
    [
        "Free cancellation; no cancellation fee",
        "Free cancellation with no cancellation fees or charges",
        "Free cancellation until Dec 31, 2026; no cancellation fee",
    ],
)
def test_no_cancellation_fee_does_not_override_explicit_free_policy(label):
    policy = _parse_cancellation(label)
    assert policy.kind in {CancellationPolicyKind.FREE_CANCELLATION, CancellationPolicyKind.FREE_UNTIL_DATE}
    assert policy.deadline_time_text is None


@pytest.mark.parametrize("label", ["Non-refundable", "Not refundable", "No cancellation", "No cancellations allowed"])
def test_explicit_non_refundable_labels_remain_recognized(label):
    assert _parse_cancellation(label).kind == CancellationPolicyKind.NON_REFUNDABLE
