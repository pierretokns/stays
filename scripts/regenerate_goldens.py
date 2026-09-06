"""Explicitly regenerate parser, serializer and CLI contract fixtures offline.

Run with ``uv run python scripts/regenerate_goldens.py`` after reviewing an
intentional contract change; review the resulting fixture diff before commit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from typer.testing import CliRunner  # noqa: E402

from stays.cli import app  # noqa: E402
from stays.mcp._executors import _serialize_hotel_detail, _serialize_hotel_result  # noqa: E402
from stays.search.hotels import MissingHotelIdError  # noqa: E402
from stays.search.parse import parse_detail_response, parse_search_response  # noqa: E402
from stays.serialize import serialize_hotel_detail, serialize_hotel_result  # noqa: E402
from tests.fixtures.cli_hotel_sample import make_detail, make_result  # noqa: E402
from tests.test_cli_envelope_golden import _mk_enriched  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def write_json(name, value):
    (FIXTURES / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main():
    search = json.loads((FIXTURES / "search_response_nyc.json").read_text())
    detail = json.loads((FIXTURES / "detail_response_sample.json").read_text())
    write_json("parse_golden_search.json", [hotel.model_dump(mode="json") for hotel in parse_search_response(search)])
    write_json("parse_golden_detail.json", parse_detail_response(detail).model_dump(mode="json"))
    for name, value in {
        "result": serialize_hotel_result(make_result()),
        "detail": serialize_hotel_detail(make_detail()),
        "mcp_result": _serialize_hotel_result(make_result()),
        "mcp_detail": _serialize_hotel_detail(make_detail()),
    }.items():
        write_json(f"serialize_golden_{name}.json", value)

    runner = CliRunner()
    for command in ("search", "details", "enrich"):
        for scenario in ("happy", "validation_error"):
            mock = MagicMock()
            mock.return_value.search.return_value = [
                make_result(),
                make_result(
                    name="Second Hotel",
                    entity_key="CgoI_TEST_KEY_0002",
                    display_price=240,
                    star_class=5,
                    overall_rating=4.7,
                    review_count=980,
                ),
            ]
            mock.return_value.get_details.return_value = make_detail()
            mock.return_value.search_with_details.return_value = [
                _mk_enriched(True),
                _mk_enriched(False, error="hotel ID missing"),
            ]
            if command == "details":
                entity = "ChkI_key" if scenario == "happy" else "ChkI_bad"
                args = [command, entity, "--check-in", "2026-07-22", "--check-out", "2026-07-26"]
                if scenario == "validation_error":
                    mock.return_value.get_details.side_effect = MissingHotelIdError("hotel ID missing")
            else:
                args = [command, "tokyo"]
                if scenario == "validation_error":
                    args += ["--check-in", "bogus"]
                elif command == "enrich":
                    args += ["--max-hotels", "2"]
            for fmt in ("json", "jsonl", "text"):
                with patch(f"stays.cli.commands.{command}.SearchHotels", mock):
                    result = runner.invoke(app, [*args, "--format", fmt])
                assert result.exit_code == (0 if scenario == "happy" else 1), result.output
                extension = "txt" if fmt == "text" else fmt
                (FIXTURES / f"cli_envelope_{command}_{scenario}.{extension}").write_text(result.stdout)


if __name__ == "__main__":
    main()
