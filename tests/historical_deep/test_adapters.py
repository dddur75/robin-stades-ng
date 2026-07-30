from __future__ import annotations

from pathlib import Path

import pytest

from robin.historical_deep.adapters import (
    DirectoryObjectStore,
    assert_safety_locks,
    validate_r2_round_trip,
)


def test_directory_store_is_append_only_and_rejects_traversal(tmp_path: Path) -> None:
    store = DirectoryObjectStore(tmp_path)
    key = "historical-deep-data/schema-v1/control/sentinel.json"
    assert store.put_if_absent(key, b"first")
    assert not store.put_if_absent(key, b"second")
    assert store.get_object(key) == b"first"
    assert tuple(store.iter_keys("historical-deep-data/schema-v1")) == (key,)
    with pytest.raises(ValueError, match="OBJECT_KEY_OUTSIDE_CACHE_ROOT"):
        store.get_object("../outside.json")


def test_safety_locks_are_exact_and_fail_closed() -> None:
    valid = {
        "STORAGE_PAUSED": "true",
        "P3_P4_PAUSED": "true",
        "PRODUCTION_LOCKED": "true",
        "REAL_BETS": "false",
        "NO_BET_DEFAULT": "true",
        "PROMOTION_LOCKED": "true",
        "SOCIAL_PUBLISHING_ENABLED": "false",
        "DEMO_MODE_ENABLED": "false",
        "POSTGRESQL_PRODUCTION_DESTRUCTIVE_WRITES": "false",
        "THE_ODDS_API_HISTORICAL_CREDITS": "false",
    }
    assert_safety_locks(valid)
    with pytest.raises(RuntimeError, match="HISTORICAL_DEEP_SAFETY_LOCK_MISMATCH"):
        assert_safety_locks({**valid, "REAL_BETS": "true"})
    with pytest.raises(RuntimeError, match="THE_ODDS_API_HISTORICAL_CREDITS"):
        assert_safety_locks(
            {**valid, "THE_ODDS_API_HISTORICAL_CREDITS": "true"}
        )


def test_round_trip_sentinel_is_idempotent(tmp_path: Path) -> None:
    store = DirectoryObjectStore(tmp_path)
    key = "historical-deep-data/schema-v1/control/sentinel-v1.json"
    validate_r2_round_trip(store, key=key)
    validate_r2_round_trip(store, key=key)
