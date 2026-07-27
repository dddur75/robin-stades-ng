from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from robin.patterns.ledger import (
    NO_BET_DEFAULT,
    PRODUCTION_STATUS,
    REAL_BETS,
    SOCIAL_PUBLISHING_ENABLED,
    EvidenceLedger,
)
from robin.patterns.social import (
    EXPORT_FILES,
    build_disabled_exports,
    validate_public_text,
)


def timestamps() -> tuple[datetime, datetime, datetime, datetime]:
    published = datetime(2026, 8, 1, 10, tzinfo=UTC)
    cutoff = published + timedelta(minutes=5)
    kickoff = cutoff + timedelta(hours=1)
    settled = kickoff + timedelta(hours=2)
    return published, cutoff, kickoff, settled


def append_bet(ledger: EvidenceLedger) -> object:
    published, cutoff, kickoff, _ = timestamps()
    return ledger.append_decision(
        decision_id="decision-1",
        published_at=published,
        cutoff_at=cutoff,
        fixture_id=42,
        competition="Ligue 1",
        kickoff_at=kickoff,
        market="1X2_HOME",
        selection="HOME",
        odds=2.0,
        odds_source="OBSERVED_POINT_IN_TIME_TEST",
        pattern_id="PTRN-TEST",
        pattern_version="1.0.0",
        decision="BET",
        code_revision="abc",
        dataset_hash="hash",
    )


def test_decision_is_frozen_append_only_and_replay_idempotent(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "ledger.jsonl")
    first = append_bet(ledger)
    replay = append_bet(ledger)
    assert first == replay
    assert ledger.audit()["records"] == 1
    with pytest.raises(ValueError, match="IMMUTABLE_LEDGER_RECORD_CONFLICT"):
        published, cutoff, kickoff, _ = timestamps()
        ledger.append_decision(
            decision_id="decision-1",
            published_at=published,
            cutoff_at=cutoff,
            fixture_id=42,
            competition="Ligue 1",
            kickoff_at=kickoff,
            market="1X2_HOME",
            selection="AWAY",
            odds=2.0,
            odds_source="OBSERVED_POINT_IN_TIME_TEST",
            pattern_id="PTRN-TEST",
            pattern_version="1.0.0",
            decision="BET",
            code_revision="abc",
            dataset_hash="hash",
        )


def test_no_bet_has_zero_stake_and_cannot_be_settled(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "ledger.jsonl")
    published, cutoff, kickoff, settled = timestamps()
    decision = ledger.append_decision(
        decision_id="no-bet",
        published_at=published,
        cutoff_at=cutoff,
        fixture_id=43,
        competition="Ligue 1",
        kickoff_at=kickoff,
        market="1X2_HOME",
        selection="NONE",
        odds=None,
        odds_source="DATA_UNAVAILABLE",
        pattern_id=None,
        pattern_version=None,
        decision="NO_BET_DATA_UNAVAILABLE",
        code_revision="abc",
        dataset_hash="hash",
    )
    assert decision.stake_units == 0.0
    with pytest.raises(ValueError, match="NO_BET_CANNOT_BE_SETTLED"):
        ledger.append_settlement(
            settlement_id="settlement-no-bet",
            decision_id="no-bet",
            settled_at=settled,
            result="VOID",
            profit_units=0.0,
        )


def test_settlement_is_separate_idempotent_and_bankroll_replays(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "ledger.jsonl")
    append_bet(ledger)
    _, _, _, settled = timestamps()
    first = ledger.append_settlement(
        settlement_id="settlement-1",
        decision_id="decision-1",
        settled_at=settled,
        result="WIN",
        profit_units=1.0,
    )
    replay = ledger.append_settlement(
        settlement_id="settlement-1",
        decision_id="decision-1",
        settled_at=settled,
        result="WIN",
        profit_units=1.0,
    )
    assert first == replay
    audit = ledger.audit()
    assert audit["records"] == 2
    assert audit["shadow_bankroll"] == 1001.0
    assert audit["real_bets"] is False


def test_hash_chain_detects_mutation(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = EvidenceLedger(path)
    append_bet(ledger)
    record = json.loads(path.read_text("utf-8"))
    record["selection"] = "MUTATED"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="LEDGER_HASH_MISMATCH"):
        ledger.audit()


def test_social_exports_are_fact_based_and_disabled(tmp_path: Path) -> None:
    paths = build_disabled_exports(tmp_path, ledger_url="/robin-live")
    assert {path.name for path in paths} == set(EXPORT_FILES)
    assert PRODUCTION_STATUS == "PRODUCTION_LOCKED"
    assert REAL_BETS is False
    assert NO_BET_DEFAULT is True
    assert SOCIAL_PUBLISHING_ENABLED is False
    for path in paths:
        payload = json.loads(path.read_text("utf-8"))
        assert payload["publishing_enabled"] is False
        assert payload["negative_results_included"] is True
    with pytest.raises(ValueError, match="FORBIDDEN_PUBLIC_CLAIM"):
        validate_public_text("Pari sûr garanti en shadow")
