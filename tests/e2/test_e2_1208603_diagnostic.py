from __future__ import annotations

import io

import pytest

from robin.historical_deep.e2_targeted_diagnostic import (
    _read_bounded,
    diagnose_payload,
)


class FakeClient:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.keys: list[str] = []

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        assert Bucket == "bucket"
        self.keys.append(Key)
        return {"ContentLength": len(self.payload), "Body": io.BytesIO(self.payload)}


def payload(statistic_ids: list[int | None]) -> dict[str, object]:
    return {
        "response": [
            {
                "fixture": {"id": 1208603},
                "lineups": [
                    {
                        "team": {"id": 546},
                        "formation": "4-4-2",
                        "startXI": [{"player": {"id": 1, "name": "A"}}],
                        "substitutes": [{"player": {"id": 2, "name": "B"}}],
                    }
                ],
                "players": [
                    {
                        "team": {"id": 546},
                        "players": [
                            {
                                "player": {"id": player_id, "name": f"P{index}"},
                                "statistics": [{"games": {"minutes": 1}}],
                            }
                            for index, player_id in enumerate(statistic_ids)
                        ],
                    }
                ],
                "events": [],
                "statistics": [],
            }
        ]
    }


def source_hashes() -> dict[str, object]:
    return {"receipt_hash": "a" * 64, "payload_hash": "b" * 64}


def test_missing_and_unexpected_valid_ids_are_provider_inconsistency() -> None:
    diagnostic, census = diagnose_payload(
        payload([1, 3]), fixture_id=1208603, source_hashes=source_hashes()
    )
    assert diagnostic["root_cause"] == "PROVIDER_INCONSISTENCY"
    assert diagnostic["missing_identity"] == [2]
    assert diagnostic["unexpected_identity"] == [3]
    assert diagnostic["code_fix_required"] is False
    assert diagnostic["unknown_policy"] == "missing_player_stat_row = UNKNOWN"
    assert census["scope"] == "ONE_FIXTURE_ONLY_NO_PROVIDER_GENERALIZATION"


def test_missing_source_row_and_null_identity_remain_distinct() -> None:
    missing, _ = diagnose_payload(
        payload([1]), fixture_id=1208603, source_hashes=source_hashes()
    )
    invalid, _ = diagnose_payload(
        payload([1, None]), fixture_id=1208603, source_hashes=source_hashes()
    )
    assert missing["root_cause"] == "MISSING_SOURCE_ROW"
    assert invalid["root_cause"] == "NULL_IDENTITY"


def test_field_census_contains_paths_not_raw_values() -> None:
    _, census = diagnose_payload(
        payload([1, 3]), fixture_id=1208603, source_hashes=source_hashes()
    )
    rows = census["rows"]
    assert isinstance(rows, list)
    encoded = repr(rows)
    assert "$.response[fixture].players[*].players[*].statistics" in encoded
    assert "P0" not in encoded and "P1" not in encoded
    assert any(row["mapped_status"] == "UNMAPPED_FIELD" for row in rows)


def test_exact_get_reader_enforces_content_and_stream_limits() -> None:
    allowed = FakeClient(b"1234")
    assert _read_bounded(allowed, bucket="bucket", key="exact", limit=4) == b"1234"
    assert allowed.keys == ["exact"]
    with pytest.raises(ValueError, match="CONTENT_LENGTH_INVALID"):
        _read_bounded(FakeClient(b"12345"), bucket="bucket", key="exact", limit=4)

