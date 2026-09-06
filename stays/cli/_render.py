"""Rich-table renderers for human-readable CLI output."""

from __future__ import annotations

from collections.abc import Iterable

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from stays.cli._console import console as _default_console
from stays.models.google_hotels.base import Amenity
from stays.models.google_hotels.detail import HotelDetail
from stays.models.google_hotels.result import HotelResult
from stays.search.hotels import EnrichedResult


def _amenity_short(values: set[Amenity] | None, limit: int = 4) -> str:
    if not values:
        return "—"
    # Amenities are Amenity enum members; sort by integer value for stability.
    sorted_amenities = sorted(values, key=lambda a: a.value)
    names = [a.name.lower().replace("_", " ") for a in sorted_amenities]
    head = names[:limit]
    suffix = f" +{len(names) - limit}" if len(names) > limit else ""
    return ", ".join(head) + suffix


def _fmt_price(hotel: HotelResult) -> str:
    if hotel.display_price is None:
        return "—"
    cur = hotel.currency or ""
    return f"{cur} {hotel.display_price}".strip()


def _fmt_rating(hotel: HotelResult) -> str:
    if hotel.overall_rating is None:
        return "—"
    return f"{hotel.overall_rating:.1f} ({hotel.review_count or 0})"


def _rate_context_warning(hotel: HotelResult) -> str | None:
    observation = hotel.observation
    if observation is None:
        return None
    concerns = []
    if observation.dates_match is not True:
        requested = observation.requested_dates
        observed = observation.observed_dates
        req = f"{requested.check_in} to {requested.check_out}" if requested else "flexible"
        obs = f"{observed.check_in} to {observed.check_out}" if observed else "unknown"
        concerns.append(f"dates requested {req}; observed {obs}")
    if observation.currency_matches is not True:
        concerns.append(
            f"currency requested {observation.requested_currency}; "
            f"observed {observation.observed_currency or 'unknown'}"
        )
    return "; ".join(concerns) if concerns else None


def render_results(results: list[HotelResult], *, console: Console | None = None) -> None:
    console = console or _default_console
    if not results:
        console.print(Panel("No hotels found matching your criteria.", border_style="red"))
        return

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right", style="dim", width=3)
    table.add_column("Name", overflow="fold", style="green")
    table.add_column("★", justify="center", width=3)
    table.add_column("Rating", justify="right", width=12)
    table.add_column("Price", justify="right", width=12)
    table.add_column("Amenities", overflow="fold")
    table.add_column("Entity Key", overflow="crop", width=14)

    for i, r in enumerate(results, 1):
        table.add_row(
            str(i),
            r.name or "—",
            str(r.star_class) if r.star_class else "—",
            _fmt_rating(r),
            _fmt_price(r),
            _amenity_short(r.amenities_available),
            (r.entity_key[:12] + "…") if r.entity_key else "—",
        )
    console.print(table)
    warnings = [f"{hotel.name}: {warning}" for hotel in results if (warning := _rate_context_warning(hotel))]
    if warnings:
        console.print(Panel(Text("\n".join(warnings)), title="Unverified rate context", border_style="yellow"))


def render_detail(detail: HotelDetail, *, console: Console | None = None) -> None:
    console = console or _default_console

    summary = Table(box=box.SIMPLE, show_header=False)
    summary.add_column(style="bold cyan")
    summary.add_column()
    summary.add_row("Name", detail.name or "—")
    summary.add_row("Address", detail.address or "—")
    summary.add_row("Phone", detail.phone or "—")
    summary.add_row("Stars", str(detail.star_class) if detail.star_class else "—")
    summary.add_row("Rating", _fmt_rating(detail))
    summary.add_row("Check-in / out", f"{detail.check_in_time or '—'} / {detail.check_out_time or '—'}")
    console.print(Panel(summary, title="Hotel", border_style="cyan"))
    warning = _rate_context_warning(detail)
    if warning:
        console.print(Panel(Text(warning), title="Unverified rate context", border_style="yellow"))

    if detail.provider_summaries:
        quotes = Table(box=box.SIMPLE_HEAVY, show_header=True)
        quotes.add_column("Provider")
        quotes.add_column("Nightly labels")
        quotes.add_column("Stay labels")
        for offer in detail.provider_summaries:
            quotes.add_row(offer.provider, " / ".join(offer.nightly_price_labels), " / ".join(offer.total_price_labels))
        console.print(
            Panel(
                quotes,
                title="Provider summaries",
                subtitle="Source display labels; room, tax basis and cancellation terms unavailable",
                border_style="yellow",
            )
        )

    if not detail.rooms:
        console.print(
            Panel("No detailed room rates returned; this does not establish availability.", border_style="yellow")
        )
        return

    for room in detail.rooms:
        rt = Table(box=box.SIMPLE_HEAVY, show_header=True)
        rt.add_column("Provider", style="green")
        rt.add_column("Price", justify="right")
        rt.add_column("Cancellation")
        rt.add_column("Breakfast", justify="center")
        rt.add_column("Taxes", justify="center")
        for rate in room.rates:
            basis = {"per_night": "/night", "total_stay": "/stay", "unknown": "(basis unknown)"}[rate.price_basis]
            rt.add_row(
                rate.provider or "—",
                f"{rate.currency or ''} {rate.price} {basis}".strip(),
                rate.cancellation.kind.value.replace("_", " ").title(),
                "?" if rate.breakfast_included is None else ("✓" if rate.breakfast_included else "No"),
                "?" if rate.includes_taxes_and_fees is None else ("✓" if rate.includes_taxes_and_fees else "No"),
            )
        subtitle = f"{room.bed_config or ''} · sleeps {room.max_occupancy or '?'}".strip(" ·")
        console.print(Panel(rt, title=room.name or "Room name unavailable", subtitle=subtitle, border_style="green"))


def render_enriched(items: Iterable[EnrichedResult], *, console: Console | None = None) -> None:
    console = console or _default_console
    any_rendered = False
    for item in items:
        any_rendered = True
        if item.ok and item.detail is not None:
            render_detail(item.detail, console=console)
        else:
            console.print(
                Panel(
                    f"[red]Error: {item.error}[/red]\n[dim]{item.result.name}[/dim]",
                    border_style="red",
                )
            )
    if not any_rendered:
        console.print(Panel("No results.", border_style="red"))
