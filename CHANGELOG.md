# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-09-06

### Fixed

- Preserve observed dates and ISO currency in detail responses even when the headline-price slot is absent. Requested currency no longer replaces an observed different currency.
- Forward guests through Python, CLI and MCP detail calls and enrichment. Reject unsupported multiroom requests and missing child ages instead of silently changing occupancy.
- Retain provider-specific room labels and every valid rate variant, including each offer's own URL. Remove the fabricated Standard Room bucket and arbitrary header-integer price fallback.
- Preserve exact observed nightly and stay amounts; never derive totals by multiplying rounded nightly prices. Tax and breakfast inclusion remain unknown when not established by the response.
- Reject detail responses for the wrong hotel. Preserve unresolved cancellation dates, raw cutoff time, unknown timezone and explicit year-inference status; handle December-to-January deadlines conservatively.
- Stop interpreting review avatar URLs and boolean flags as one-star reviews.
- Use a neutral entity-detail query: forwarding a discovery city query was suppressing detailed room rates in live responses.
- Render nightly/stay price basis and unverified date/currency context in text output.

### Added

- Observation metadata with requested and observed dates/currency, requested guests, unknown observed occupancy, UTC fetch time and decoded-response SHA256. Mismatches remain visible as warnings and false match flags.
- MCP observed-date output, exact decimal amount strings, source paths, bounded Python enrichment and strict offline regression fixtures.
- Separate provider summaries for alternate responses with displayed quotes but no room/rate terms; these never become synthetic room offers.

### Compatibility

- Room names, breakfast and tax fields can be null. There can be many supplier-specific room/rate rows; identical names do not prove room equivalence.
- `price` is now an observed numeric amount with `price_basis`; `price_exact` and `total_price` are decimal strings in CLI/MCP JSON. Total amounts are not certified tax-inclusive payable totals.
- Response success denotes acquisition, not confirmed merchant availability or booking/rebooking eligibility. Child ages are retained but the wire still uses age buckets; only one room is supported.
- `get_details(location=...)` remains accepted for compatibility but is ignored; the entity key selects the hotel and the neutral query retains full rate data.

## [0.1.1] - 2026-04-23

### Fixed

- `search_parser._find_hotel_entries` no longer drops listings whose `entry[3]` star-class tuple is `None`. Budget, boutique, and hostel properties (5 in the NYC fixture alone) were being silently skipped. The heuristic now anchors on coordinates at `[2][0]` plus FID/entity_key instead of star class.
- `SearchHotels.search` applies a stable post-sort when `sort_by` is `LOWEST_PRICE`, `HIGHEST_RATING`, or `MOST_REVIEWED`. Google's own ordering has same-price inversions and occasional sponsored-row interleaves; the post-sort gives callers strictly monotonic output on the non-None subsequence. `RELEVANCE` / `None` remain no-ops. `None` values sort to the end on every mode.

### Tests

- New offline suite `test_search_sort_post_sort.py` covering the three sort modes, `None`-last behavior on each, `RELEVANCE`/`None` no-op, and Python-sort stability on ties.
- New regression guard `test_budget_hotels_without_star_class_are_kept` asserting the 5 known star-less NYC hotels surface by name.
- New `test_detail_finds_exactly_one_hotel_entry` confirming the relaxed heuristic still resolves exactly one entry for detail responses.
- `test_cli_live` LOWEST_PRICE scenario tightened from "≤2 inversions" to strict monotonic; added live E2E scenarios for `HIGHEST_RATING` and `MOST_REVIEWED`.

## [0.1.0] - 2026-04-23

Initial public release.

### Added

- Hotel search (`search_hotels`) with 16 filter slots: city / brand / stars / price range / amenities / dates / guests / cancellation / eco / special offers / sort.
- Hotel detail (`get_hotel_details`) via the same `AtySUc` RPC — rooms, per-OTA rate plans (Booking, Expedia, Hotels.com, Trip.com, direct), cancellation policies, deep-link URLs.
- Parallel enrichment (`search_hotels_with_details`) — search + fan-out detail fetch for the top N hotels (hard cap 15) in a single call, with per-hotel partial failure.
- `error_kind: Literal["transient", "fatal"]` and `is_retryable` property on `EnrichedResult` — CLI `enrich` output and the MCP `search_hotels_with_details` tool carry both fields per item so retry-aware callers can distinguish recoverable failures.
- Rate-limited `curl_cffi` client with Chrome TLS impersonation and tenacity retries.
- FastMCP server over stdio and streamable HTTP.
- `stays.serialize` — canonical serializers (public, consumed by both CLI and MCP) for `HotelResult`, `HotelDetail`, `RoomType`, `RatePlan`, and `CancellationPolicy`. Dict shapes guarded by golden-fixture tests.
- `SetupBackend` Protocol + `SetupReport` dataclass + `BACKENDS` registry under `stays.mcp.setup`; per-client `register(...)` / `build()` entrypoints in `stays.mcp.setup.{claude,codex,chatgpt}`.
- `stays` CLI (sole console script) with subcommands `search`, `details`, `enrich`, `mcp`, `mcp-http`.
- `stays setup` group with per-client backends: `claude` (Code + Desktop auto-detect with JSON fallback), `codex` (wraps `codex mcp add` with TOML fallback), `chatgpt` (prints remote-HTTPS + Developer Mode instructions).
- Smart-default routing: `stays "tokyo"` → `stays search "tokyo"`.
- Three output formats: `--format text` (rich tables, default), `--format json` (envelope), `--format jsonl` (line-oriented).
- 330 offline tests + live MCP E2E + golden-fixture parse/serialize/CLI-envelope regression guards + subprocess CLI live E2E (`tests/test_cli_live.py`) + pluggable browser-vs-programmatic oracle (`agent-browser` default, Playwright fallback via `STAYS_BROWSER_DRIVER=playwright`).
- Dockerfile + docker-compose.yml with `prod` / `dev` profiles.
- GitHub Actions: lint, test matrix (Python 3.10–3.13), Docker GHCR, PyPI publish via OIDC.
- `Makefile` for common uv-driven tasks.
- PEP 561 `py.typed` marker.
- `LICENSE` (MIT), `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/AI_AGENTS.md`, `CLAUDE.md`, `AGENTS.md`.

[Unreleased]: https://github.com/him229/stays/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/him229/stays/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/him229/stays/releases/tag/v0.1.0
