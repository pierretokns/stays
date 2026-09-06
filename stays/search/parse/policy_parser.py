"""Conservative parsing of cancellation labels and calendar dates."""

from __future__ import annotations

import re
from datetime import date, datetime

from stays.models.google_hotels.policy import CancellationPolicy, CancellationPolicyKind

__all__ = ["_parse_cancellation"]


def _resolve_cancellation_date(
    raw_date: str,
    *,
    reference_year: int | None = None,
    requested_check_in: date | None = None,
) -> tuple[date | None, bool]:
    """Resolve a displayed deadline without assuming the machine's current year.

    A supplied check-in provides a year context, not an observed deadline year.
    Only December-to-January rollover is inferred when the month/day would
    otherwise fall after check-in; other contradictory labels remain unresolved.
    """
    text = " ".join(raw_date.replace(",", " ").split())
    for fmt in ("%b %d %Y", "%B %d %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date(), False
        except ValueError:
            continue
    for fmt in ("%b %d", "%B %d"):
        try:
            # A leap reference year permits a valid yearless February 29.
            parsed = datetime.strptime(f"{text} 2000", f"{fmt} %Y")
        except ValueError:
            continue
        year = requested_check_in.year if requested_check_in else reference_year
        if year is None:
            return None, False
        if requested_check_in and (parsed.month, parsed.day) > (requested_check_in.month, requested_check_in.day):
            if requested_check_in.month == 1 and parsed.month == 12:
                year -= 1
            else:
                return None, False
        try:
            return date(year, parsed.month, parsed.day), True
        except ValueError:
            return None, False
    return None, False


def _parse_cancellation(
    text: str,
    *,
    reference_year: int | None = None,
    requested_check_in: date | None = None,
) -> CancellationPolicy | None:
    """Extract explicit policy statements; preserve unresolved deadline text."""
    t = text.strip()
    if not t:
        return None

    if re.search(
        r"\bnon[\s-]?refundable\b|\bnot refundable\b|"
        r"\bno (?:cancellations?|cancel)(?:\s+(?:allowed|permitted|accepted))?\s*[.!]?$",
        t,
        re.IGNORECASE,
    ):
        return CancellationPolicy(kind=CancellationPolicyKind.NON_REFUNDABLE, description=t)
    if re.search(r"partial(ly)? refund", t, re.IGNORECASE):
        return CancellationPolicy(kind=CancellationPolicyKind.PARTIALLY_REFUNDABLE, description=t)
    # Negated free-cancellation wording does not establish refund eligibility.
    if re.search(
        r"\b(?:no|not|without)\s+free cancellation|free cancellation\s+(?:is\s+)?(?:not|unavailable)",
        t,
        re.IGNORECASE,
    ):
        return CancellationPolicy(description=t)

    m = re.search(r"free cancellation until\s+(.+)", t, re.IGNORECASE)
    if m:
        label = m.group(1).strip()
        date_match = re.match(r"([A-Za-z]+\s+\d{1,2}(?:,?\s+\d{4})?|\d{4}-\d{2}-\d{2})\b", label)
        raw_date = date_match.group(1) if date_match else label
        free_until, inferred = _resolve_cancellation_date(
            raw_date, reference_year=reference_year, requested_check_in=requested_check_in
        )
        suffix = label[date_match.end() :].strip(" ,;") if date_match else ""
        time_match = re.match(r"(?:at\s+)?(\d{1,2}:\d{2}(?:\s*[AP]M)?)\b", suffix, re.IGNORECASE)
        time_text = time_match.group(1) if time_match else None
        return CancellationPolicy(
            kind=CancellationPolicyKind.FREE_UNTIL_DATE,
            free_until=free_until,
            description=t,
            deadline_time_text=time_text or None,
            date_inferred=inferred,
        )
    if re.search(r"\bfree cancellation\b", t, re.IGNORECASE):
        return CancellationPolicy(kind=CancellationPolicyKind.FREE_CANCELLATION, description=t)
    return None
