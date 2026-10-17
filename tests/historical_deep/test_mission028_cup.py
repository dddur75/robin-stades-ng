from scripts.run_mission028 import LEAGUES, census_queries, match_rows, provider_league_ids


def test_census_whitelist_adds_only_two_argentine_cup_seasons():
    queries = census_queries()
    original = {(code, league, season) for code, league in LEAGUES.items()
                for season in range(2019, 2025)}
    assert len(queries) == len(set(queries)) == 200
    assert set(queries) - original == {("ARG", 1032, 2023), ("ARG", 1032, 2024)}
    assert original <= set(queries)
    assert all(2019 <= season <= 2024 for _, _, season in queries)
    assert provider_league_ids("ARG", 2024) == {128, 1032}
    assert provider_league_ids("ARG", 2022) == {128}
    assert provider_league_ids("E1", 2024) == {40}


def test_argentine_cup_matches_preserve_actual_provider_league_id():
    row = dict(ligue_fd="ARG", saison_fd="2023", date="2023-08-20", equipe_dom_fd="River Plate",
               equipe_ext_fd="Lanus", buts_dom="1", buts_ext="0")
    fixture = dict(fixture=dict(id=999, date="2023-08-20T20:00:00+00:00", status=dict(short="FT")),
        league=dict(id=1032, season=2023), goals=dict(home=1, away=0),
        teams=dict(home=dict(name="River Plate"), away=dict(name="Lanus")))
    table, rates = match_rows([row], [fixture], {})
    assert table[0]["fixture_id"] == 999 and table[0]["league_id"] == 1032
    assert rates["ARG"]["fraction"] == 1
    fixture["league"]["id"] = 1033
    assert match_rows([row], [fixture], {})[0][0]["fixture_id"] is None
