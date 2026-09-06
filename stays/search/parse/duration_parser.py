"""Conservative conversion of English nearby-place duration labels."""

from __future__ import annotations

import re

_DURATION = re.compile(
    r"(?:(?P<hours>[0-9]+)\s+(?:hr|hrs|hour|hours)"
    r"(?:\s+(?P<minutes>[0-9]+)\s+(?:min|mins|minute|minutes))?"
    r"|(?P<minutes_only>[0-9]+)\s+(?:min|mins|minute|minutes))",
    re.IGNORECASE,
)


def parse_duration_minutes(text: str) -> int | None:
    """Parse a complete hour/minute label, leaving ambiguous durations unknown.

    Accept English hour and minute labels with ordinary or Unicode whitespace.
    Do not turn ranges, approximate labels, seconds, or unrelated numeric text
    into a precise number of minutes. A minutes-only label may exceed 59; a
    minute component following hours must be below 60.
    """
    if not isinstance(text, str):
        return None
    match = _DURATION.fullmatch(" ".join(text.split()))
    if match is None:
        return None
    if match["minutes_only"] is not None:
        return int(match["minutes_only"])
    minutes = int(match["minutes"] or 0)
    if minutes >= 60:
        return None
    return int(match["hours"]) * 60 + minutes
