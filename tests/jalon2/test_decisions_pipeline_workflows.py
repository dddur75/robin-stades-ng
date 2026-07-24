import json
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


def test_decision_candidate_reste_strictement_simulee() -> None:
    decision = decide_shadow_bet(
        fixture_id="f1",
        market_key="1X2",
        selection="HOME",
        odds_decimal=2.2,
        model_probability=0.52,
        strategy_version="value-1",
        quality_ok=True,
    )
    assert decision.accepted
    assert decision.simulation
    assert decision.suggested_stake == 10
    assert decision.primary_reason is None


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        ({"odds_decimal": None}, RejectionCode.MISSING_ODDS),
        ({"quality_ok": False}, RejectionCode.QUALITY_BLOCKED),
        ({"stale": True}, RejectionCode.STALE_DATA),
        ({"model_disagreement": True}, RejectionCode.MODEL_DISAGREEMENT),
        ({"exposure_ok": False}, RejectionCode.EXPOSURE_LIMIT),
        (
            {"odds_decimal": 1.5, "model_probability": 0.5},
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
        "odds_decimal": 2.2,
        "model_probability": 0.52,
        "strategy_version": "value-1",
        "quality_ok": True,
    }
    base.update(arguments)
    decision = decide_shadow_bet(**cast(Any, base))
    assert not decision.accepted
    assert reason in {decision.primary_reason, *decision.secondary_reasons}
    assert decision.suggested_stake == 0


def test_journal_decision_est_idempotent(tmp_path: Path) -> None:
    journal = DecisionJournal(tmp_path / "decisions.jsonl")
    decision = decide_shadow_bet(
        fixture_id="f1",
        market_key="1X2",
        selection="HOME",
        odds_decimal=None,
        model_probability=0.5,
        strategy_version="value-1",
        quality_ok=False,
    )
    assert journal.append(decision)
    assert not journal.append(decision)
    assert len(journal.read_all()) == 1


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
    assert "actions/cache@v4" in content
    assert "if: always()" in content
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
    results = evaluate_walk_forward(frame)
    assert len(results) == 11
    assert all("PRODUCTION" not in result.status for result in results)
    assert next(item for item in results if item.strategy == "btts_value").bets == 0
