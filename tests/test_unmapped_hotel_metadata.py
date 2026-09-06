"""Regressions from Hotel Xanadu and Platinum Residence trip observations."""

import json
from pathlib import Path

from stays import Amenity
from stays.search.parse import parse_detail_response
from stays.search.parse.slots import safe_get
from stays.serialize import serialize_hotel_detail

FIXTURE = Path(__file__).parent / "fixtures" / "unmapped_hotel_metadata.json"


def _records():
    return json.loads(FIXTURE.read_text())["observations"]


def test_response_flags_do_not_reuse_search_filter_amenity_codes():
    for record in _records():
        entry = record["hotel_entry"]
        detail = parse_detail_response([entry])
        assert Amenity.BEACH_ACCESS not in detail.amenities_available
        assert Amenity.BAR not in detail.amenities_available
        assert detail.amenities_available == set()
        assert any(flag.code == 11 and flag.enabled for flag in detail.amenity_flags)
        assert any(flag.code == 15 and flag.enabled for flag in detail.amenity_flags)
        assert any(not flag.enabled for flag in detail.amenity_flags)
        for flag in detail.amenity_flags:
            assert safe_get(entry, *flag.source_path)[:2] == [flag.enabled, flag.code]
        serialized = serialize_hotel_detail(detail)
        assert serialized["amenities"] == []
        assert serialized["amenity_flags"]


def test_airport_travel_codes_are_unmapped_and_complete_durations_survive():
    detail = parse_detail_response([_records()[0]["hotel_entry"]])
    gatwick = next(place for place in detail.nearby if place.name == "London Gatwick Airport")
    assert gatwick.mode is None
    assert gatwick.mode_code == 0
    assert gatwick.duration_text == "1 hr 9 min"
    assert gatwick.duration_minutes == 69
    assert gatwick.distance_text is None
    assert [(option.mode_code, option.duration_minutes) for option in gatwick.travel_options] == [(0, 69), (3, 99)]
    heathrow = next(place for place in detail.nearby if place.name == "Heathrow Airport")
    assert heathrow.mode is None
    assert heathrow.mode_code == 3
    assert heathrow.duration_minutes == 22
    assert heathrow.travel_options[1].duration_minutes == 30


def test_all_travel_options_remain_traceable_to_wire_codes_and_labels():
    for record in _records():
        entry = record["hotel_entry"]
        detail = parse_detail_response([entry])
        for place in detail.nearby:
            assert place.mode is None
            assert safe_get(entry, *place.source_path, 0) == place.name
            for option in place.travel_options:
                assert safe_get(entry, *option.source_path) == [option.mode_code, option.duration_text]


def test_ambiguous_duration_does_not_become_a_false_exact_travel_time():
    entry = _records()[0]["hotel_entry"]
    entry[2][1][0][2] = [[0, "20–30 min"]]
    first = parse_detail_response([entry]).nearby[0]
    assert first.duration_minutes is None
    assert first.duration_text == "20–30 min"
    assert first.travel_options[0].duration_minutes is None


def test_nearby_paths_preserve_dictionary_keys_for_evidence_replay():
    entry = _records()[0]["hotel_entry"]
    raw_place = entry[2][1][0]
    entry[2][1] = {"nearby": raw_place}
    place = parse_detail_response([entry]).nearby[0]
    assert place.source_path == [2, 1, "nearby"]
    assert safe_get(entry, *place.source_path) == raw_place
    for index, option in enumerate(place.travel_options):
        assert option.source_path == [2, 1, "nearby", 2, index]
        assert safe_get(entry, *option.source_path) == [option.mode_code, option.duration_text]
