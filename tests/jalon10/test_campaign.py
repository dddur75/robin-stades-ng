from __future__ import annotations

from robin.patterns.campaign import CampaignConfig, run_campaign


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
    assert len(controls) == 7
    assert controls["shuffled_labels"]["passed"] is True
    assert controls["shuffled_labels"]["status"] == "REJECTED"
    assert controls["shifted_odds"]["status"] == "LEAKAGE_REJECTED"
    assert controls["trivial_market_rule"]["status"] == "REJECTED"
    assert controls["shuffled_labels"]["promoted"] is False
    assert controls["post_result_pattern"]["status"] == "LEAKAGE_REJECTED"
