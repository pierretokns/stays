"""Nearby-place durations must preserve hours and reject ambiguous labels."""

import pytest

from stays.search.parse.duration_parser import parse_duration_minutes


@pytest.mark.parametrize(
    ("label", "minutes"),
    [
        ("1 hr 9 min", 69),
        ("2 hr", 120),
        ("22 min", 22),
        ("1 hr 59 min", 119),
        ("1 hr 0 min", 60),
        ("90 min", 90),
        ("0 min", 0),
        ("  1 hr   9 min  ", 69),
        ("1\u202fhr\u00a09\u202fmin", 69),
        ("2\u00a0hr", 120),
        ("1 hour 9 minutes", 69),
        ("2 hrs 1 minute", 121),
        ("2 HOURS", 120),
    ],
)
def test_parse_explicit_hour_and_minute_labels(label, minutes):
    assert parse_duration_minutes(label) == minutes


@pytest.mark.parametrize(
    "label",
    [
        "",
        " ",
        "22",
        "22 miles",
        "walk 22 min",
        "22 min by taxi",
        "about 22 min",
        "< 1 min",
        "20-30 min",
        "20–30 min",
        "1 hr - 2 hr",
        "-22 min",
        "+22 min",
        "1 hr -9 min",
        "1.5 hr",
        "1,5 hr",
        "30 sec",
        "1 min 30 sec",
        "1 hr 60 min",
        "9 min 1 hr",
        "1 day 2 hr",
        "1 hr 9 min 2 min",
        "1 hr 9 min away",
        "22 minutos",
    ],
)
def test_reject_ambiguous_or_unsupported_duration_labels(label):
    assert parse_duration_minutes(label) is None
