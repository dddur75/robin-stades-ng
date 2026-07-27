from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from robin.patterns.campaign import CampaignConfig
from scripts import run_pattern_campaign as runner


def _result(*, result_hash: str, hypotheses: list[dict[str, object]]) -> dict[str, object]:
    return {
        "result_hash": result_hash,
        "dataset_hashes": ["a" * 64],
        "code_revision": "abc123",
        "data_classification": "DISCOVERY_EXPOSED",
        "verdict": "JALON_10_NO_ROBUST_PATTERN_FOUND",
        "config": {
            "live_market_point_in_time": False,
            "feature_cutoff": "HISTORICAL_PRICE_CATEGORY_NO_EXACT_CUTOFF",
            "odds_type": "HISTORICAL_CLOSING_OR_PRE_CLOSING_MARKET",
        },
        "provider_calls": 0,
        "odds_api_credits": 0,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
        "no_bet_default": True,
        "social_publishing_enabled": False,
        "demo_mode_enabled": False,
        "counts": {"hypotheses_executed": len(hypotheses)},
        "hypotheses": hypotheses,
    }


def test_config_commitee_est_chargee_sans_cle_cachee() -> None:
    config = runner.load_campaign_config(
        Path("configs/pattern-research-v1.json")
    )
    assert isinstance(config, CampaignConfig)
    assert config.provider_calls_allowed == 0
    assert config.social_publishing_enabled is False
    assert config.exposed_stability_competitions == ("Bundesliga", "Serie A")
    assert config.feature_cutoff == "HISTORICAL_PRICE_CATEGORY_NO_EXACT_CUTOFF"


def test_registre_durable_ne_contient_que_les_candidats_live() -> None:
    rejected = [
        {
            "rule_hash": f"{index:064x}",
            "status": "INSUFFICIENT_SUPPORT",
            "payload": "x" * 500,
        }
        for index in range(700)
    ]
    candidate = {
        "rule_hash": "f" * 64,
        "status": "LIVE_SHADOW_CANDIDATE",
        "market": "1X2_HOME",
        "selection": "HOME",
        "conditions": [],
    }
    compact = runner.compact_candidate_registry(
        _result(
            result_hash="b" * 64,
            hypotheses=[*rejected, candidate],
        )
    )
    serialized = json.dumps(compact).encode("utf-8")

    assert compact["candidate_count"] == 1
    assert compact["hypotheses"] == [candidate]
    assert len(serialized) < 262_144
    assert b"INSUFFICIENT_SUPPORT" not in serialized


def test_replay_non_deterministe_preserve_la_preuve_primaire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "campaign"
    output.mkdir()
    primary = {"result_hash": "a" * 64, "sentinel": "PRIMARY_PRESERVED"}
    summary = output / "campaign-summary.json"
    summary.write_text(json.dumps(primary), encoding="utf-8")
    monkeypatch.setattr(runner, "load_market_rows", lambda _path: [])
    monkeypatch.setattr(
        runner,
        "load_campaign_config",
        lambda _path: CampaignConfig(),
    )
    monkeypatch.setattr(
        runner,
        "run_campaign",
        lambda *_args, **_kwargs: _result(
            result_hash="b" * 64,
            hypotheses=[],
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_pattern_campaign.py",
            "--state",
            str(tmp_path / "historical"),
            "--output",
            str(output),
            "--code-revision",
            "abc123",
            "--replay",
        ],
    )

    with pytest.raises(
        SystemExit,
        match="NON_DETERMINISTIC_REPLAY_PRIMARY_PRESERVED",
    ):
        runner.main()

    assert json.loads(summary.read_text("utf-8")) == primary
    assert not (output / "hypothesis-registry.jsonl").exists()
    assert (output / "replay-mismatch.json").exists()
