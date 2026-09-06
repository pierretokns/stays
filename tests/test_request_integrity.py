"""Regression tests for requests which previously changed silently in flight."""

import json
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from rich.console import Console
from typer.testing import CliRunner

from stays import DateRange, GuestInfo, HotelDetail, HotelResult, HotelSearchFilters, Location
from stays.cli import app
from stays.cli._render import render_detail, render_results
from stays.mcp._params import GetHotelDetailsParams, SearchHotelsParams
from stays.mcp.server import _execute_get_hotel_details_from_params, _serialize_hotel_result
from stays.search.hotels import SearchHotels
from stays.serialize import serialize_hotel_detail

FIXTURES = Path(__file__).parent / "fixtures"


def test_multiroom_and_missing_child_ages_are_rejected():
    with pytest.raises(ValidationError):
        GuestInfo(rooms=2)
    with pytest.raises(ValidationError):
        GuestInfo(children=1)


def test_mutated_unsupported_room_request_still_fails_before_network():
    filters = HotelSearchFilters(location=Location(query="Lisbon"))
    filters.guests.rooms = 2
    client = MagicMock()
    with pytest.raises(ValidationError):
        SearchHotels(client=client).search(filters)
    client.post_rpc.assert_not_called()


def test_observation_is_a_snapshot_of_sent_context():
    filters = HotelSearchFilters(location=Location(query="Lisbon"), guests=GuestInfo(adults=3))
    response = json.loads((FIXTURES / "search_response_nyc.json").read_text())
    client = MagicMock()

    def mutate_caller_after_request(*args):
        filters.guests.adults = 1
        return response

    client.post_rpc.side_effect = mutate_caller_after_request
    result = SearchHotels(client=client).search(filters)[0]
    assert result.observation.requested_guests.adults == 3
    assert client.post_rpc.call_args.args[1][1][1] == [[[3], [3], [3]], 1]


@pytest.mark.parametrize("dates", [{"check_in": "2026-11-10"}, {"check_out": "2026-11-13"}])
def test_mcp_rejects_half_date_request_instead_of_flexible_search(dates):
    with pytest.raises(ValidationError, match="supplied together"):
        SearchHotelsParams(query="Lisbon", **dates)


def test_mcp_empty_dates_cannot_become_flexible_search():
    with pytest.raises(ValidationError):
        SearchHotelsParams(query="Lisbon", check_in="", check_out="")


def test_enrichment_preserves_nondefault_guest_request():
    search = SearchHotels(client=MagicMock())
    search.search = MagicMock(return_value=[HotelResult(name="Test", entity_key="test")])
    search.get_details = MagicMock(return_value=HotelDetail(name="Test", entity_key="test"))
    guests = GuestInfo(adults=3, children=1, child_ages=[7])
    filters = HotelSearchFilters(
        location=Location(query="Lisbon"), dates=DateRange(check_in="2026-11-10", check_out="2026-11-13"), guests=guests
    )
    search.search_with_details(filters, max_hotels=1)
    assert search.get_details.call_args.kwargs["guests"] == guests
    assert "location" not in search.get_details.call_args.kwargs


def test_mcp_details_preserves_guests():
    params = GetHotelDetailsParams(
        entity_key="test", check_in="2026-11-10", check_out="2026-11-13", adults=3, children=1, child_ages=[7]
    )
    with patch("stays.mcp.server.SearchHotels") as search:
        search.return_value.get_details.return_value = HotelDetail(name="Test")
        assert _execute_get_hotel_details_from_params(params)["success"]
        assert search.return_value.get_details.call_args.kwargs["guests"] == GuestInfo(
            adults=3, children=1, child_ages=[7]
        )


def test_cli_details_preserves_guests_and_rejects_incomplete_party():
    args = ["details", "test", "--check-in", "2026-11-10", "--check-out", "2026-11-13", "--format", "json"]
    with patch("stays.cli.commands.details.SearchHotels") as search:
        search.return_value.get_details.return_value = HotelDetail(name="Test")
        result = CliRunner().invoke(app, [*args, "--adults", "3", "--children", "1", "--child-age", "7"])
        assert result.exit_code == 0, result.output
        assert search.return_value.get_details.call_args.kwargs["guests"] == GuestInfo(
            adults=3, children=1, child_ages=[7]
        )
        search.reset_mock()
        result = CliRunner().invoke(app, [*args, "--children", "1"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error"]["type"] == "validation_error"
        search.assert_not_called()


def test_observed_context_is_not_replaced_with_requested_dates():
    response = json.loads((FIXTURES / "search_response_nyc.json").read_text())
    client = MagicMock()
    client.post_rpc.return_value = response
    search = SearchHotels(client=client)
    dates = DateRange(check_in="2030-11-10", check_out="2030-11-13")
    results = search.search(HotelSearchFilters(location=Location(query="Lisbon"), dates=dates))
    result = next(result for result in results if result.rate_dates)
    assert result.rate_dates != (dates.check_in, dates.check_out)
    assert result.observation.requested_dates == dates
    assert result.observation.observed_dates.check_in == result.rate_dates[0]
    assert result.observation.dates_match is False
    assert result.observation.observed_guests is None
    assert "date_mismatch" in result.observation.warnings
    assert len(result.observation.response_sha256) == 64
    serialized = _serialize_hotel_result(result)
    assert serialized["rate_dates"]["check_in"] == result.rate_dates[0].isoformat()
    assert serialized["observation"]["dates_match"] is False

    output = StringIO()
    console = Console(file=output, width=160)
    render_results([result], console=console)
    assert "Unverified rate context" in output.getvalue()
    assert "2030-11-10" in output.getvalue()
    assert result.rate_dates[0].isoformat() in output.getvalue()
    output = StringIO()
    render_detail(HotelDetail(**result.model_dump()), console=Console(file=output, width=160))
    assert "Unverified rate context" in output.getvalue()
    assert "2030-11-10" in output.getvalue()


def test_details_sends_party_in_wire_request_without_claiming_verified_occupancy():
    client = MagicMock()
    client.post_rpc.return_value = []
    guests = GuestInfo(adults=3, children=1, child_ages=[7])
    detail = HotelDetail(name="Test", entity_key="test")
    with patch("stays.search.hotels.parse_detail_response", return_value=detail):
        result = SearchHotels(client=client).get_details(
            "test", DateRange(check_in=date(2026, 11, 10), check_out=date(2026, 11, 13)), guests=guests
        )
    payload = client.post_rpc.call_args.args[1]
    assert payload[1][1] == [[[3], [3], [3], [2, 12]], 1]
    assert result.observation.requested_guests == guests
    assert result.observation.observed_guests is None
    assert result.observation.observed_dates is None
    assert result.observation.dates_match is None
    assert "child_ages_sent_as_buckets" in result.observation.warnings


def test_provider_summaries_survive_serialization_and_text_without_fake_rooms():
    from stays.search.parse import parse_detail_response

    response = json.loads((FIXTURES / "lisbon_provider_summaries.json").read_text())
    detail = parse_detail_response(response)
    data = serialize_hotel_detail(detail)
    assert data["rooms"] == []
    assert len(data["provider_summaries"]) == 27
    assert data["provider_summaries"][0]["nightly_price_labels"]
    assert "price_exact" not in data["provider_summaries"][0]
    output = StringIO()
    render_detail(detail, console=Console(file=output, width=160))
    assert "Provider summaries" in output.getvalue()
    assert "tax basis and cancellation terms unavailable" in output.getvalue()


@pytest.mark.parametrize("limit", [0, -1, 16])
def test_python_enrichment_rejects_unbounded_fanout(limit):
    client = MagicMock()
    filters = HotelSearchFilters(
        location=Location(query="Lisbon"), dates=DateRange(check_in="2026-11-10", check_out="2026-11-13")
    )
    with pytest.raises(ValueError, match="max_hotels"):
        SearchHotels(client=client).search_with_details(filters, max_hotels=limit)
    client.post_rpc.assert_not_called()
