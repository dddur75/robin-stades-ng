import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pytest
import yaml

from robin.backtesting.oos import evaluate_walk_forward
from robin.shadow.decision import (
    DecisionJournal,
    RejectionCode,
    decide_shadow_bet,
)
from scripts.run_shadow_pipeline import (
    collect_fixtures,
    collect_odds,
    daily_health,
    post_match_settlement,
    pre_match_shadow,
)

PIT_DECIDED_AT = datetime(2026, 7, 24, 12, tzinfo=UTC)


def _pit_lineage() -> dict[str, object]:
    return {
        "cutoff_at": PIT_DECIDED_AT,
        "feature_lineage_hash": "1" * 64,
        "odds_receipt_id": "2" * 64,
        "odds_available_at": PIT_DECIDED_AT - timedelta(minutes=1),
        "model_registry_hash": "3" * 64,
        "model_available_at": PIT_DECIDED_AT - timedelta(days=1),
        "point_in_time_status": "POINT_IN_TIME_VALID",
        "decided_at": PIT_DECIDED_AT,
    }


def test_shadow_self_declared_temporal_scalars_never_enable_stake() -> None:
    decision = decide_shadow_bet(
        fixture_id="f1",
        market_key="1X2",
        selection="HOME",
        market_odds={"HOME": 2.2, "DRAW": 3.5, "AWAY": 3.8},
        model_probability=0.52,
        devig_method="PROPORTIONAL",
        strategy_version="value-1",
        quality_ok=True,
        **_pit_lineage(),
    )
    assert decision.accepted is False
    assert decision.simulation
    assert decision.suggested_stake == 0
    assert decision.primary_reason is RejectionCode.INSUFFICIENT_DATA
    assert decision.point_in_time_status == "POINT_IN_TIME_NOT_PROVEN"
    assert decision.cutoff_at == PIT_DECIDED_AT
    assert decision.feature_lineage_hash == "1" * 64
    assert decision.odds_receipt_id == "2" * 64


def test_shadow_hashes_unverified_lineage_but_never_promotes_it() -> None:
    baseline = decide_shadow_bet(
        fixture_id="f-lineage",
        market_key="1X2",
        selection="HOME",
        market_odds={"HOME": 2.2, "DRAW": 3.5, "AWAY": 3.8},
        model_probability=0.52,
        devig_method="PROPORTIONAL",
        strategy_version="value-1",
        quality_ok=True,
        **_pit_lineage(),
    )
    changed = decide_shadow_bet(
        fixture_id="f-lineage",
        market_key="1X2",
        selection="HOME",
        market_odds={"HOME": 2.2, "DRAW": 3.5, "AWAY": 3.8},
        model_probability=0.52,
        devig_method="PROPORTIONAL",
        strategy_version="value-1",
        quality_ok=True,
        **{**_pit_lineage(), "feature_lineage_hash": "9" * 64},
    )
    assert baseline.decision_input_hash != changed.decision_input_hash
    assert baseline.decision_id != changed.decision_id
    assert baseline.accepted is changed.accepted is False
    assert baseline.point_in_time_status == "POINT_IN_TIME_NOT_PROVEN"
    assert changed.point_in_time_status == "POINT_IN_TIME_NOT_PROVEN"


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        ({"market_odds": None}, RejectionCode.MISSING_ODDS),
        ({"quality_ok": False}, RejectionCode.QUALITY_BLOCKED),
        ({"stale": True}, RejectionCode.STALE_DATA),
        ({"model_disagreement": True}, RejectionCode.MODEL_DISAGREEMENT),
        ({"exposure_ok": False}, RejectionCode.EXPOSURE_LIMIT),
        (
            {
                "market_odds": {"HOME": 1.5, "DRAW": 4.0, "AWAY": 6.0},
                "model_probability": 0.5,
            },
            RejectionCode.INSUFFICIENT_EDGE,
        ),
    ],
)
def test_codes_rejet_normalises(
    arguments: dict[str, object],
    reason: RejectionCode,
) -> None:
    base: dict[str, object] = {
        "fixture_id": "f1",
        "market_key": "1X2",
        "selection": "HOME",
        "market_odds": {"HOME": 2.2, "DRAW": 3.5, "AWAY": 3.8},
        "model_probability": 0.52,
        "devig_method": "PROPORTIONAL",
        "strategy_version": "value-1",
        "quality_ok": True,
    }
    base.update(arguments)
    decision = decide_shadow_bet(**cast(Any, base))
    assert not decision.accepted
    assert reason in {decision.primary_reason, *decision.secondary_reasons}
    assert decision.suggested_stake == 0


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("model_probability", float("nan"), "SHADOW_MODEL_PROBABILITY_INVALID"),
        ("bankroll", -1.0, "SHADOW_BANKROLL_INVALID"),
        ("min_edge", -0.1, "SHADOW_EDGE_THRESHOLD_INVALID"),
        ("min_edge", 1.1, "SHADOW_EDGE_THRESHOLD_INVALID"),
    ],
)
def test_shadow_decision_rejects_invalid_numeric_inputs(
    field: str,
    value: float,
    message: str,
) -> None:
    values: dict[str, object] = {
        "fixture_id": "fixture-invalid",
        "market_key": "1X2",
        "selection": "HOME",
        "market_odds": {"HOME": 2.0, "DRAW": 3.2, "AWAY": 4.0},
        "model_probability": 0.6,
        "devig_method": "PROPORTIONAL",
        "strategy_version": "truth-kernel-v1",
        "quality_ok": True,
        "bankroll": 100.0,
    }
    values[field] = value
    with pytest.raises(ValueError, match=message):
        decide_shadow_bet(**cast(Any, values))


def test_journal_decision_est_idempotent(tmp_path: Path) -> None:
    journal = DecisionJournal(tmp_path / "decisions.jsonl")
    decision = decide_shadow_bet(
        fixture_id="f1",
        market_key="1X2",
        selection="HOME",
        market_odds=None,
        model_probability=0.5,
        devig_method="PROPORTIONAL",
        strategy_version="value-1",
        quality_ok=False,
    )
    assert journal.append(decision)
    assert not journal.append(decision)
    assert len(journal.read_all()) == 1


def test_shadow_identity_covers_full_market_and_supersedes_business_state(
    tmp_path: Path,
) -> None:
    journal = DecisionJournal(tmp_path / "decisions.jsonl")
    base: dict[str, object] = {
        "fixture_id": "f-market",
        "market_key": "1X2",
        "selection": "HOME",
        "market_odds": {"HOME": 2.2, "DRAW": 3.5, "AWAY": 3.8},
        "model_probability": 0.52,
        "devig_method": "PROPORTIONAL",
        "strategy_version": "value-1",
        "quality_ok": True,
        "prediction_id": "prediction-market",
        **_pit_lineage(),
    }
    first = decide_shadow_bet(**cast(Any, base))
    changed = decide_shadow_bet(
        **cast(Any, {**base, "market_odds": {"HOME": 2.2, "DRAW": 10.0, "AWAY": 10.0}})
    )
    assert first.decision_id != changed.decision_id
    assert first.decision_business_key == changed.decision_business_key
    assert first.accepted is False
    assert changed.accepted is False
    assert first.point_in_time_status == "POINT_IN_TIME_NOT_PROVEN"
    assert journal.append(first) is True
    assert journal.append(changed) is True
    assert len(journal.read_all()) == 2
    assert [item["decision_id"] for item in journal.read_effective()] == [
        changed.decision_id
    ]


def test_shadow_journal_supersedes_legacy_uuid_without_double_counting(
    tmp_path: Path,
) -> None:
    journal = DecisionJournal(tmp_path / "decisions.jsonl")
    decision = decide_shadow_bet(
        fixture_id="f-legacy",
        market_key="1X2",
        selection="HOME",
        market_odds={"HOME": 2.2, "DRAW": 3.5, "AWAY": 3.8},
        model_probability=0.52,
        devig_method="PROPORTIONAL",
        strategy_version="value-1",
        quality_ok=True,
    )
    legacy = {
        "decision_id": decision.legacy_decision_id,
        "fixture_id": "f-legacy",
        "market_key": "1X2",
        "selection": "HOME",
        "odds_decimal": 2.2,
        "model_probability": 0.52,
        "implied_probability": 1.0 / 2.2,
        "edge": 0.52 - 1.0 / 2.2,
        "strategy_version": "value-1",
        "quality_status": "PASSED",
        "uncertainty_status": "NORMAL",
        "suggested_stake": 10.0,
        "accepted": True,
        "primary_reason": None,
        "secondary_reasons": [],
        "decided_at": "2026-07-24T11:34:16Z",
        "simulation": True,
    }
    journal.path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    assert journal.append(decision) is True
    assert len(journal.read_all()) == 2
    assert len(journal.read_effective()) == 1
    assert journal.read_effective()[0]["decision_id"] == decision.decision_id


def test_pipeline_mock_complet_ne_se_fait_jamais_passer_pour_du_live(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(root)
    output = tmp_path / "shadow"
    fixtures = collect_fixtures(output, mock=True)
    odds = collect_odds(output, mock=True)
    prediction = pre_match_shadow(output, mock=True)
    settlement = post_match_settlement(output, mock=True)
    health = daily_health(output)
    assert fixtures["origin"] == "DEMO DATA"
    assert odds["snapshots"] == 0
    assert prediction["origin"] == "DEMO DATA"
    assert settlement["settled"] == 0
    assert health["production_locked"] is True
    payload = json.loads((output / "fixtures" / "latest.json").read_text("utf-8"))
    assert payload[0]["origin"] == "DEMO DATA"


def test_settlement_ignores_forged_accepted_shadow_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "shadow"
    journal = DecisionJournal(output / "decisions" / "shadow-decisions.jsonl")
    journal.path.write_text(
        json.dumps(
            {
                "decision_id": "legacy-forged-accepted",
                "fixture_id": "fixture-forged",
                "accepted": True,
                "point_in_time_status": "POINT_IN_TIME_VALID",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    calls = 0

    def forbidden_provider(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise AssertionError("provider must not be called for unverified journal rows")

    monkeypatch.setattr("scripts.run_shadow_pipeline.provider", forbidden_provider)
    result = post_match_settlement(output, mock=False)

    assert result["status"] == "WORKFLOW_SUCCESS_NO_DATA"
    assert result["eligible_decisions"] == 0
    assert result["unverified_accepted_decisions_ignored"] == 1
    assert result["calls_consumed"] == 0
    assert calls == 0


def test_configuration_shadow_verrouille_paris_reels() -> None:
    root = Path(__file__).resolve().parents[2]
    config = yaml.safe_load((root / "configs" / "shadow_v1.yaml").read_text("utf-8"))
    assert config["mode"] == "SHADOW"
    assert config["real_bets_enabled"] is False
    assert len(config["collection_windows"]) == 9
    assert config["bankroll"]["max_daily_exposure_pct"] <= 10


@pytest.mark.parametrize(
    "workflow",
    [
        "collect-fixtures.yml",
        "collect-odds.yml",
        "pre-match-shadow.yml",
        "post-match-settlement.yml",
        "daily-health.yml",
    ],
)
def test_workflows_planifies_sont_idempotents_et_diagnosticables(workflow: str) -> None:
    root = Path(__file__).resolve().parents[2]
    content = (root / ".github" / "workflows" / workflow).read_text("utf-8")
    assert "workflow_dispatch" in content
    assert "schedule:" in content
    assert "concurrency:" in content
    assert "manage_shadow_state.py restore" in content
    assert "actions/upload-artifact@v4" in content
    assert "shadow-state-${{ github.run_id }}" in content
    assert "secrets." not in content or "ODDS_API_KEY" in content


def test_oos_walk_forward_ne_produit_pas_de_statut_production() -> None:
    dates = pd.date_range("2024-01-01", periods=12, freq="30D", tz="UTC")
    frame = pd.DataFrame(
        {
            "match_id": [f"m{i}" for i in range(12)],
            "league": ["F1"] * 12,
            "season": ["2024-25"] * 6 + ["2025-26"] * 6,
            "date": dates,
            "home": ["A", "B"] * 6,
            "away": ["B", "A"] * 6,
            "fthg": [2, 1, 2, 0, 1, 2, 1, 2, 0, 3, 1, 2],
            "ftag": [0, 1, 1, 1, 0, 1, 1, 0, 2, 1, 1, 1],
            "psch": [2.0] * 12,
            "pscd": [3.2] * 12,
            "psca": [3.8] * 12,
            "pc_o25": [1.9] * 12,
        }
    )
    results = evaluate_walk_forward(frame, devig_method="PROPORTIONAL")
    assert len(results) == 11
    assert all("PRODUCTION" not in result.status for result in results)
    assert all(result.as_dict()["devig_method"] == "PROPORTIONAL" for result in results)
    assert all("yield" in result.as_dict() for result in results)
    assert all(
        result.as_dict()["point_in_time_status"] == "POINT_IN_TIME_NOT_PROVEN"
        and result.as_dict()["promotion"] == "NO_PROMOTION"
        and result.as_dict()["production_status"] == "PRODUCTION_LOCKED"
        for result in results
    )
    assert next(item for item in results if item.strategy == "btts_value").bets == 0
