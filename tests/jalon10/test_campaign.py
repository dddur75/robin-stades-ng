from __future__ import annotations

from robin.patterns.campaign import (
    CampaignConfig,
    _historical_promotion_gate_passes,
    run_campaign,
)


def rows() -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    fixture = 0
    for season in range(2020, 2026):
        for competition in (
            "Ligue 1",
            "Premier League",
            "La Liga",
            "Bundesliga",
            "Serie A",
        ):
            for match in range(4):
                fixture += 1
                home_goals = (fixture + match) % 4
                away_goals = (fixture * 2 + match) % 3
                output.append(
                    {
                        "fixture_id": fixture,
                        "competition": competition,
                        "season": season,
                        "match_date": f"{season}-{match + 1:02d}-01",
                        "kickoff_at": f"{season}-{match + 1:02d}-01T15:00:00Z",
                        "home_goals": home_goals,
                        "away_goals": away_goals,
                        "odds_home": 1.5,
                        "odds_draw": 3.2,
                        "odds_away": 3.8,
                        "odds_over_25": 2.0,
                        "odds_under_25": 1.9,
                        "market_margin_1x2": 0.08,
                        "market_margin_totals": 0.026,
                        "price_type": "HISTORICAL_CLOSING_MARKET",
                        "totals_price_type": "HISTORICAL_CLOSING_MARKET",
                        "observed_time_status": "SOURCE_PRICE_CLASS_ONLY",
                    }
                )
    return output


def test_campaign_is_deterministic_cache_only_and_records_every_rule() -> None:
    config = CampaignConfig(
        minimum_bets=10,
        minimum_seasons=2,
        minimum_fold_bets=2,
        bootstrap_candidates_limit=3,
        permutation_candidates_limit=1,
    )
    first = run_campaign(rows(), code_revision="abc", config=config)
    replay = run_campaign(rows(), code_revision="abc", config=config)
    assert first["result_hash"] == replay["result_hash"]
    assert first["checkpoint"] == replay["checkpoint"]
    assert first["provider_calls"] == 0
    assert first["odds_api_credits"] == 0
    assert first["real_bets"] is False
    assert first["social_publishing_enabled"] is False
    assert first["demo_mode_enabled"] is False
    counts = first["counts"]
    assert counts["hypotheses_generated"] == counts["hypotheses_executed"]
    assert len(first["hypotheses"]) == counts["hypotheses_executed"]
    assert counts["shadow_candidates"] == 0
    assert first["verdict"] == "JALON_10_NO_ROBUST_PATTERN_FOUND"


def test_negative_controls_are_never_promoted() -> None:
    result = run_campaign(
        rows(),
        code_revision="abc",
        config=CampaignConfig(
            minimum_bets=10,
            minimum_seasons=2,
            bootstrap_candidates_limit=1,
            permutation_candidates_limit=1,
        ),
    )
    controls = result["negative_controls"]
    assert all(control["promoted"] is False for control in controls.values())
    assert all(control["executed"] is True for control in controls.values())
    assert all(control["passed"] is True for control in controls.values())
    assert len(controls) == 7
    assert controls["shuffled_labels"]["passed"] is True
    assert controls["shuffled_labels"]["status"] == "REJECTED"
    assert controls["shifted_odds"]["status"] == "LEAKAGE_REJECTED"
    assert (
        controls["shifted_odds"]["rejection_reason"]
        == "FIXTURE_ODDS_JOIN_MISMATCH"
    )
    assert controls["random_feature"]["rejection_reason"].startswith(
        "UNKNOWN_FEATURE_AVAILABILITY:"
    )
    assert controls["impossible_condition"]["selected"] == 0
    assert controls["trivial_market_rule"]["status"] == "REJECTED"
    assert controls["shuffled_labels"]["promoted"] is False
    assert controls["post_result_pattern"]["status"] == "LEAKAGE_REJECTED"
    assert controls["post_result_pattern"]["rejection_reason"].startswith(
        "LEAKAGE_REJECTED:"
    )


def test_historical_promotion_gate_requires_permutation_and_concentration() -> None:
    complete = {
        "metrics": {"roi": 0.08},
        "q_value": 0.01,
        "bootstrap": {"lower": 0.02},
        "permutation": {"permutations": 100, "p_value": 0.01},
        "concentration": {"passed": True},
    }
    assert _historical_promotion_gate_passes(complete, alpha=0.05) is True

    missing_permutation = {**complete, "permutation": None}
    assert (
        _historical_promotion_gate_passes(missing_permutation, alpha=0.05)
        is False
    )
    adverse_permutation = {
        **complete,
        "permutation": {"permutations": 100, "p_value": 0.06},
    }
    assert (
        _historical_promotion_gate_passes(adverse_permutation, alpha=0.05)
        is False
    )
    missing_concentration = {**complete, "concentration": None}
    assert (
        _historical_promotion_gate_passes(missing_concentration, alpha=0.05)
        is False
    )


def test_insufficient_rules_remain_in_the_frozen_fdr_denominator() -> None:
    result = run_campaign(
        rows(),
        code_revision="abc",
        config=CampaignConfig(
            minimum_bets=10_000,
            minimum_seasons=10,
            bootstrap_candidates_limit=0,
            permutation_candidates_limit=0,
        ),
    )

    hypotheses = result["hypotheses"]
    assert len(hypotheses) == 700
    assert result["counts"]["support_rejected"] == 700
    assert all(item["p_value"] == 1.0 for item in hypotheses)
    assert all(item["q_value"] == 1.0 for item in hypotheses)
    assert result["counts"]["fdr_survivors"] == 0


def test_exposed_league_stability_never_masquerades_as_external_validation() -> None:
    result = run_campaign(
        rows(),
        code_revision="abc",
        config=CampaignConfig(
            minimum_bets=10,
            minimum_seasons=2,
            minimum_fold_bets=2,
            bootstrap_candidates_limit=3,
            permutation_candidates_limit=1,
            live_market_point_in_time=True,
        ),
    )

    evidence = [
        item["exposed_league_stability"]
        for item in result["hypotheses"]
        if item.get("exposed_league_stability") is not None
    ]
    assert evidence
    assert all(item["independent"] is False for item in evidence)
    assert all(item["evidence_scope"] == "DISCOVERY_EXPOSED" for item in evidence)
    assert result["counts"]["external_league_survivors"] == 0
    assert result["counts"]["shadow_candidates"] == 0
    assert result["scope_subverdict"] == (
        "NO_ROBUST_PATTERN_FOUND_IN_PREREGISTERED_MARKET_SLICE_SEARCH_SPACE"
    )
