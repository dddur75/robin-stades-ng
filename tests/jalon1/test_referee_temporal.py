from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from moteur.features import construire


def match(
    index: int,
    *,
    league: str,
    season: str,
    date: datetime,
    referee: str | None = "REF-X",
    cards: float = 3,
    target: bool = False,
) -> dict[str, object]:
    return {
        "match_id": "target" if target else f"{league}-{season}-{index}",
        "league": league,
        "season": season,
        "date": pd.Timestamp(date),
        "home": f"{league}-A",
        "away": f"{league}-B",
        "fthg": 1,
        "ftag": 0,
        "hthg": 1,
        "htag": 0,
        "referee": referee,
        "hy": cards,
        "ay": 0,
        "hr": 0,
        "ar": 0,
        "hc": 4,
        "ac": 3,
        "psh": 2.0,
        "psd": 3.2,
        "psa": 4.0,
        "psch": 2.0,
        "pscd": 3.2,
        "psca": 4.0,
        "p_o25": 2.0,
        "p_u25": 2.0,
        "pc_o25": 2.0,
        "pc_u25": 2.0,
    }


def target_features(rows: list[dict[str, object]]) -> pd.Series:
    zones = {
        "E0": {"releg_spots": 1, "promo_spots": 0, "europe_spots": 1},
        "E1": {"releg_spots": 1, "promo_spots": 0, "europe_spots": 1},
    }
    features = construire(pd.DataFrame(rows), zones_par_ligue=zones)
    return features[(features["match_id"] == "target") & (features["side"] == "home")].iloc[0]


def test_historique_global_est_separe_de_la_competition() -> None:
    start = datetime(2026, 1, 1)
    rows = [
        match(i, league="E1", season="2025-26", date=start + timedelta(days=i), cards=6)
        for i in range(15)
    ]
    rows.append(
        match(
            99,
            league="E0",
            season="2025-26",
            date=datetime(2026, 2, 1),
            target=True,
        )
    )

    row = target_features(rows)

    assert bool(row["ARBITRE_SEVERE_GLOBAL"])
    assert not bool(row["ARBITRE_SEVERE_COMPETITION"])
    assert not bool(row["ARBITRE_SEVERE_SAISON"])
    assert not bool(row["ARBITRE_SEVERE"])


def test_futur_d_une_autre_ligue_ne_contamine_pas_le_passe() -> None:
    rows = [
        match(
            99,
            league="E0",
            season="2025-26",
            date=datetime(2026, 1, 1),
            target=True,
        )
    ]
    rows.extend(
        match(
            i,
            league="E1",
            season="2025-26",
            date=datetime(2026, 2, 1) + timedelta(days=i),
            cards=9,
        )
        for i in range(20)
    )

    row = target_features(rows)

    assert row["referee_n_global"] == 0
    assert not bool(row["ARBITRE_SEVERE_GLOBAL"])


def test_match_simultane_ne_complete_pas_l_echantillon_arbitre() -> None:
    rows = [
        match(
            i,
            league="E1",
            season="2025-26",
            date=datetime(2026, 1, 1) + timedelta(days=i),
            cards=6,
        )
        for i in range(14)
    ]
    same_day = datetime(2026, 2, 1)
    rows.append(match(20, league="E1", season="2025-26", date=same_day, cards=6))
    rows.append(
        match(
            21,
            league="E0",
            season="2025-26",
            date=same_day,
            cards=6,
            target=True,
        )
    )

    row = target_features(rows)

    assert row["referee_n_global"] == 14
    assert not bool(row["ARBITRE_SEVERE_GLOBAL"])


def test_saison_et_donnees_manquantes_restent_isolees() -> None:
    rows = [
        match(
            i,
            league="E0",
            season="2024-25",
            date=datetime(2025, 1, 1) + timedelta(days=i),
            cards=6,
        )
        for i in range(15)
    ]
    rows.extend(
        match(
            50 + i,
            league="E0",
            season="2025-26",
            date=datetime(2025, 8, 1) + timedelta(days=i),
            cards=np.nan,
        )
        for i in range(15)
    )
    rows.append(
        match(
            99,
            league="E0",
            season="2025-26",
            date=datetime(2026, 2, 1),
            target=True,
        )
    )

    row = target_features(rows)

    assert bool(row["ARBITRE_SEVERE_COMPETITION"])
    assert not bool(row["ARBITRE_SEVERE_SAISON"])
    assert row["referee_n_season"] == 0


def test_arbitre_inconnu_reste_sans_signal() -> None:
    row = target_features(
        [
            match(
                1,
                league="E0",
                season="2025-26",
                date=datetime(2026, 2, 1),
                referee=None,
                target=True,
            )
        ]
    )
    assert row["referee_n_global"] == 0
    assert not bool(row["ARBITRE_SEVERE"])

