# Stays hotel-system readiness

Updated 2026-09-06. Fork base: `77a7558664a9a237ad4c14f1e684eb154a4b047f` (0.1.1).
The 0.2.0 changes repair acquisition fidelity for a downstream hotel optimizer;
this package does not book, cancel, or certify merchant availability.

## Implemented

- Detail dates/currency are parsed independently from the optional headline price.
- Python/CLI/MCP details and enrichment forward the same guest request.
- Unsupported rooms >1 and missing child ages fail validation before network I/O.
- Actual provider-specific room/rate variants replace synthetic Standard Room
  and cheapest-only collapsing; each rate retains its own URL and source path.
- Exact numeric nightly and stay values are exposed as decimal strings in JSON.
  No multiplication of rounded prices or inference of tax inclusion is performed.
- Unknown breakfast/tax inclusion is null. Cancellation time text, unknown timezone
  and inferred deadline year are explicit. Wrong-property detail responses fail.
- Observation metadata records UTC retrieval, a canonical decoded-response hash,
  requested dates/currency/guests, independently observed dates/currency, unknown
  observed occupancy and explicit mismatch warnings. MCP preserves those fields.
- Unsafe review extraction no longer turns booleans and avatar URLs into reviews.
- Python enrichment is bounded to the same 1–15 hotel range as MCP.
- Entity detail always uses the neutral query `hotels`. The compatibility
  `location` argument is ignored and enrichment does not forward discovery cities.
- Alternate provider quote summaries retain source display labels and links in
  `provider_summaries`, never as fabricated room/rate records. Text output separates
  them and shows nightly/stay basis and mismatched/unverified date/currency context.

## Evidence and validation

The unchanged baseline passed 345 offline tests with 73 live/browser tests skipped
on Python 3.12.13. `tests/fixtures/lisbon_detail_audit.json` is a reduced, anonymized
capture of a real September 5, 2026 response: 3 supplier-specific rooms and 10
offers, with unchanged rate/date/cancellation vectors. The original full capture
contained 38 room records and 146 offers, previously collapsed to 3 rates.

Use `uv run pytest` for the complete offline gate and
`uv run python scripts/regenerate_goldens.py` only for intentional contract updates.
Golden equality assertions remain strict. Live/browser verification is separate
and must not be inferred from passing offline fixtures.

Final offline gate: 404 passed, 73 skipped in 9.18 seconds on Python 3.12.13.
Ruff check and format passed; wheel and source distribution built as 0.2.0;
`git diff --check` passed. Live/browser suites remain opt-in; the bounded fresh
RPC observations below were run separately.

Fresh September 6 live checks made four successful HTTP calls: two searches
returned 18 results each with matching requested/observed dates and currency
(three nights/two adults and four nights/three adults plus one child). A city-query
detail returned 27 provider summaries and no room rates. The same entity/dates
using the neutral detail query returned 21 rooms, 84 rate options (42 free-until)
and 27 summaries. Exact occupancy, merchant totals and refund terms were not
independently confirmed; no booking or cancellation occurred.

## Remaining boundaries

- The wire uses child-age buckets, including inferred boundaries for ages 0–1 and
  13–17. Exact occupancy and room allocation are not response-verified.
- Same room labels across suppliers are not room equivalence; beds, occupancy,
  included benefits, payment terms and total payable cost still need verification.
- Date/currency mismatches are preserved as evidence rather than silently corrected.
  Consumers must require match flags to be true for date/currency-sensitive use.
- `total_price` is an observed stay amount, not a certified tax/fee-inclusive total.
- Cancellation cutoff timezone is unknown; inferred dates cannot authorize cancellation.
- Review snippets are not a verified recent Booking.com review feed. SPA is a broad
  source amenity and does not establish hot-tub, sauna or steam-room availability.
- RPC shape and permitted commercial data use remain upstream dependencies.
- No cache, database migration, paid service, booking or cancellation engine was added.

See `docs/hotel-system-integration.md` for downstream ingestion and eligibility rules.
