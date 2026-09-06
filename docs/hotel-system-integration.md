# Using Stays as a hotel-system data source

Stays acquires Google Hotels observations. The parent hotel system should own
saved trips, ranking, history, budgets and booking decisions. Stays does not
require a database, an LLM, a phone or a paid API key. Network availability and
the stability of Google's undocumented response format remain dependencies.

## A bounded first pass

```python
from datetime import date

from stays import (
    Currency, DateRange, GuestInfo, HotelSearchFilters, Location, SearchHotels,
)
from stays.serialize import serialize_hotel_detail

filters = HotelSearchFilters(
    location=Location(query="Lisbon hotels"),
    dates=DateRange(check_in=date(2027, 1, 12), check_out=date(2027, 1, 15)),
    guests=GuestInfo(adults=2),
    currency=Currency.USD,
    hotel_class=[4, 5],
    free_cancellation=True,
)

for item in SearchHotels(detail_concurrency=2).search_with_details(filters, max_hotels=3):
    if not item.ok:
        # Record the failure; use is_retryable for a bounded retry policy.
        print(item.result.name, item.error_kind, item.error)
        continue
    detail = item.detail
    observation = detail.observation
    if observation.dates_match is not True or observation.currency_matches is not True:
        continue
    candidate = serialize_hotel_detail(detail)
    # Persist as a candidate for verification. Occupancy, final payable total,
    # room equivalence and merchant availability still need confirmation.
```

This makes one search plus at most three detail RPC calls before transport
retries. The enrichment limit is 1–15 hotels. Keep retries and concurrency
bounded, and stop polling a stay at its configured end time. This controls
request volume; it does not establish an uptime or operating-cost guarantee.

Discovery uses the supplied city query. Entity-key detail calls use the neutral
`hotels` query, preserving the requested dates, party and currency. The Python
`get_details(location=...)` argument remains accepted for compatibility but is
deprecated and ignored; it no longer changes the detail request.

## What the output establishes

| Field | Meaning and use |
| --- | --- |
| `observation.requested_dates`, `requested_guests`, `requested_currency` | The actual request context. These are not proof the supplier priced that party. |
| `observed_dates`, `observed_currency` | Facts extracted independently from the response, including detail responses with no list-view price. |
| `dates_match`, `currency_matches` | Three states: true, false, or null when verification is unavailable. Only true passes that particular check. |
| `observed_guests` | Currently null. Exact occupancy has not been verified in the response. |
| `fetched_at`, `response_sha256` | UTC acquisition timestamp and SHA-256 of the decoded JSON, serialized with sorted keys, compact separators, UTF-8 and `ensure_ascii=False`. The hash is not of the raw HTTP bytes. |
| `rooms[].name` | The provider's observed room label, or null. Separate providers' identical labels do not establish equivalent rooms. |
| `provider_summaries` | Supplier-level display quotes returned by an alternate response format. `nightly_price_labels` and `total_price_labels` preserve the original strings; they do not establish room identity, exact amounts or tax semantics. |
| `rates[].price_exact`, `total_price` | Decimal strings preserving the source amount rather than rounded display prices. The stay total is read from its own source field, not calculated by multiplying nights. |
| `price_basis` | Whether `price` represents a nightly price, a total-stay price, or an unknown basis. Do not sort mixed bases together. |
| `includes_taxes_and_fees`, `breakfast_included` | Nullable facts. Null means unverified; it must not be converted to false or treated as an all-in total. |
| `cancellation` | The individual offer's observed policy. Year inference is flagged; raw deadline time text is retained. An unknown timezone prevents deriving a precise cancellation instant. |
| `deeplink_url` | The offer-specific link when present. It can expire and is not a reservation or availability guarantee. |
| Room/rate `source_path` | Integer indexes relative to the selected hotel entry in the decoded response. Pair them with the response hash and hotel entity key for auditability. |

The acquisition timestamp records when Stays received the response. It does not
establish when Google last refreshed a merchant's price. Warnings distinguish
unverified occupancy and merchant availability from dates/currency checks.
`no_room_rate_offers_parsed` means no room-level rates were parsed; the response
can still contain `provider_summaries`. It does not mean that the hotel is sold
out. Keep these summaries separate from room-level offers in the user interface
and in price comparisons.

## Ranking and price history

Store observations in the parent's existing database. There is no need to add
another service or change databases for this integration. Use append-only
observations rather than overwriting historical prices. Preserve the requested
party, dates, currency, observation, individual offer terms and acquisition
version together. A hash without a retained response supports equality checks
but cannot reconstruct evidence; retain permitted evidence separately with an
appropriate retention policy.

Use the Google price as a discovery signal. Before applying a $100/$150 all-in
nightly ceiling, verify the merchant's payable stay total, including mandatory
fees and the exact occupancy. Before declaring a cheaper equivalent offer,
also match the room, bed, meals, payment timing, cancellation terms and customer
eligibility. Keep comparable alternatives separate from exact-room matches.

The library performs no booking or cancellation. A downstream rebooking system
needs a fresh merchant check and a confirmed replacement before releasing an
existing reservation. An inferred date and an unknown timezone are insufficient
for an automatic cancellation deadline.

## Supported scope and gaps

- Only one room is supported. `GuestInfo(rooms=2)` fails instead of silently
  pricing one room. Provide an age for every child. Requested exact ages are
  preserved, but the wire uses age buckets and does not verify exact party pricing.
- Search filters help shortlist hotels; they do not verify each returned offer's
  eligibility, refundability or payable total.
- Detail responses preserve the observed room and rate alternatives, including
  refundable offers that are not the cheapest. They do not guarantee complete
  merchant inventory or access to mobile-app, member or private rates.
- Some live detail responses contain only supplier summaries. These can direct
  the user to a merchant for a fresh quote, but cannot establish a cheaper
  equivalent room or refundable replacement on their own.
- A generic spa label is not proof of a hot tub, steam room or sauna. Verify
  specific facilities using dated hotel evidence before ranking them as present.
- Highlighted review excerpts do not establish a dated, rated, representative
  review feed. Unsupported snippets are excluded from `recent_reviews`; this
  field does not provide Booking.com's newest-review ordering.
- This reverse-engineered client provides no data license or contractual access
  guarantee. A production integration must separately establish permitted use.

## Migrating consumers from 0.1.x

Consumers must accept nullable room names, breakfast and tax facts. Room rows
are provider-specific and may contain multiple offers, so code that assumes
`rooms[0].rates` covers the property must change. Preserve decimal-string
amounts rather than converting them to binary floats for accounting. MCP
retains `rate_dates` and `observation`; it exposes cancellation fields with
the `cancellation_` prefix, while the canonical CLI serializer nests them.

## Audit fixture provenance

`tests/fixtures/lisbon_detail_audit.json` is a minimized decoded response from
the earlier hotel-system audit: Iberostar Selection Lisboa, November 10–13,
2026, USD. The original HTTP body SHA-256 was
`b2a67aeabf3c6525878c800de9f1031c5edd9249f171820bd0c7040935c8b4f0`.

The original response contained 38 provider-specific room rows and 146 rate
options. The fixture retains the first room from each of three providers and
all ten associated rates, with provider/offer URLs replaced by distinct
`example.invalid` URLs and unrelated metadata removed. Dates, currencies,
amounts and cancellation vectors are preserved. The regression demonstrates
that parsing retains evidence; it is not independent merchant confirmation of
the wire format's financial semantics or a current-price test.

## Bounded live validation, September 6, 2026

Four public, unauthenticated HTTP calls returned 200 from the cloud environment:

| Request | Observed result |
| --- | --- |
| Lisbon, November 10–13, 2026, two adults, USD | 18 search results; all 18 returned the requested dates and currency. |
| Lisbon, January 12–16, 2027, three adults and one child aged seven, USD | 18 search results; all 18 returned the requested dates and currency. Exact occupancy remains unverified. |
| Iberostar Selection Lisboa, November 10–13, using the city query | 27 supplier summaries and no room-level rates. |
| Same property and dates, using the neutral `hotels` detail query | 21 room rows, 84 rate options (42 with a free-until policy), and 27 supplier summaries; dates and currency matched. |

This supports separating discovery queries from entity-key detail requests.
It does not establish that query choice is the only cause of varying inventory.
The alternate-summary fixture `tests/fixtures/lisbon_provider_summaries.json`
preserves all 27 supplier summaries and the two promoted entries, with tracking
links removed. Promoted copies are excluded when the main summary list exists.
No browser checkout, payment, booking or cancellation was performed.
