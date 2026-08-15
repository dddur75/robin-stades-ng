#!/usr/bin/env python3
"""Generate a deterministic, provider-free canary-shaped capture fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

FIXTURE_PATH = Path("tests/capture/fixtures/synthetic-canary-structural-equivalent-v1.json")
EVENT_COUNT = 4
BOOKMAKER_COUNT = 19
H2H_MARKET_OBJECT_COUNT = 76
TOTALS_MARKET_OBJECT_COUNT = 51
UNSUPPORTED_MARKET_OBJECT_COUNT = 8
TOTALS_BY_EVENT = (13, 13, 13, 12)
UNSUPPORTED_BY_EVENT = (2, 2, 2, 2)


def _event_id(index: int) -> str:
    return f"event-synthetic-{index + 1:03d}"


def _bookmaker_key(index: int) -> str:
    if index == 0:
        return "bookmaker_alpha"
    if index == 1:
        return "bookmaker_beta"
    return f"bookmaker_synthetic_{index + 1:03d}"


def _h2h_outcomes(seed: int) -> list[dict[str, object]]:
    base = 101 + seed * 3
    return [
        {"name": "Away Beta", "price": float(f"{base}.01")},
        {"name": "Draw", "price": float(f"{base + 1}.02")},
        {"name": "Home Alpha", "price": float(f"{base + 2}.03")},
    ]


def _totals_outcomes(seed: int) -> list[dict[str, object]]:
    base = 501 + seed * 2
    point = float(f"{900 + seed}.5")
    return [
        {"name": "Over", "point": point, "price": float(f"{base}.04")},
        {"name": "Under", "point": point, "price": float(f"{base + 1}.05")},
    ]


def _event(event_index: int, *, structural_optional_absence: bool) -> dict[str, Any]:
    bookmakers: list[dict[str, Any]] = []
    for bookmaker_index in range(BOOKMAKER_COUNT):
        seed = event_index * BOOKMAKER_COUNT + bookmaker_index
        markets: list[dict[str, Any]] = [
            {
                "key": "h2h",
                "last_update": f"2030-01-{event_index + 1:02d}T00:{bookmaker_index:02d}:00Z",
                "outcomes": _h2h_outcomes(seed),
            }
        ]
        if bookmaker_index < TOTALS_BY_EVENT[event_index]:
            markets.append(
                {
                    "key": "totals",
                    "last_update": f"2030-01-{event_index + 1:02d}T00:{bookmaker_index:02d}:30Z",
                    "outcomes": _totals_outcomes(seed),
                }
            )
        if bookmaker_index < UNSUPPORTED_BY_EVENT[event_index]:
            markets.append(
                {
                    "key": "h2h_lay",
                    "last_update": f"2030-01-{event_index + 1:02d}T00:{bookmaker_index:02d}:45Z",
                    "outcomes": _h2h_outcomes(seed + 100),
                }
            )
        bookmaker: dict[str, Any] = {
            "key": _bookmaker_key(bookmaker_index),
            "title": f"Synthetic Bookmaker {bookmaker_index + 1:03d}",
            "last_update": f"2030-01-{event_index + 1:02d}T00:{bookmaker_index:02d}:50Z",
            "markets": markets,
        }
        if structural_optional_absence and bookmaker_index == 1:
            bookmaker.pop("last_update")
            bookmaker["markets"][0].pop("last_update")
        bookmakers.append(bookmaker)
    return {
        "id": _event_id(event_index),
        "sport_key": "soccer_synthetic_alpha",
        "sport_title": "Synthetic Football",
        "commence_time": f"2030-02-{event_index + 1:02d}T20:00:00Z",
        "home_team": "Home Alpha",
        "away_team": "Away Beta",
        "bookmakers": bookmakers,
    }


def build_fixture() -> dict[str, object]:
    cardinality = [
        _event(event_index, structural_optional_absence=False) for event_index in range(EVENT_COUNT)
    ]
    structural = [
        {
            **_event(0, structural_optional_absence=True),
            "bookmakers": _event(0, structural_optional_absence=True)["bookmakers"][:2],
        },
        {
            **_event(1, structural_optional_absence=False),
            "bookmakers": _event(1, structural_optional_absence=False)["bookmakers"][:2],
        },
    ]
    return {
        "schema_version": "robin-synthetic-canary-equivalent-v1",
        "provenance": "ENTIRELY_SYNTHETIC_NO_PROVIDER_PAYLOAD",
        "identity_policy": {
            "event_prefix": "event-synthetic-",
            "teams": ["Home Alpha", "Away Beta"],
            "bookmaker_prefix": "bookmaker_",
            "timestamps": "FICTIONAL_2030",
            "prices": "ARTIFICIAL_VALUES_ABOVE_100",
        },
        "expected_cardinality": {
            "event_count": EVENT_COUNT,
            "unique_bookmaker_count": BOOKMAKER_COUNT,
            "event_bookmaker_occurrence_count": EVENT_COUNT * BOOKMAKER_COUNT,
            "h2h_market_object_count": H2H_MARKET_OBJECT_COUNT,
            "totals_market_object_count": TOTALS_MARKET_OBJECT_COUNT,
            "unsupported_market_object_count": UNSUPPORTED_MARKET_OBJECT_COUNT,
            "h2h_outcome_count": H2H_MARKET_OBJECT_COUNT * 3,
            "totals_outcome_count": TOTALS_MARKET_OBJECT_COUNT * 2,
            "supported_normalized_observation_count": (
                H2H_MARKET_OBJECT_COUNT * 3 + TOTALS_MARKET_OBJECT_COUNT * 2
            ),
            "totals_by_event": list(TOTALS_BY_EVENT),
        },
        "expected_neutral_path_type_signature_sha256": (
            "2f93a94eabce6f732cc632216fb09349afbd0387421a35823b8b5d5a6948161c"
        ),
        "responses": {
            "structural_optional_timestamp_paths": structural,
            "c0_cardinality_equivalent": cardinality,
        },
    }


def render_fixture() -> str:
    return (
        json.dumps(build_fixture(), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    destination = args.repo.resolve() / FIXTURE_PATH
    rendered = render_fixture()
    if args.check:
        if not destination.is_file() or destination.read_text(encoding="utf-8") != rendered:
            raise SystemExit("SYNTHETIC_CANARY_FIXTURE_CHECK_FAILED")
        print("SYNTHETIC_CANARY_FIXTURE_CHECK_PASS")
        return 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"SYNTHETIC_CANARY_FIXTURE_WRITTEN:{destination.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
