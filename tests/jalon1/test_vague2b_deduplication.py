import numpy as np
import pandas as pd
import pytest

from agents.agent_vague2b import canonicaliser_masque_marche


def test_marche_neutre_devient_une_opportunite_par_match() -> None:
    feats = pd.DataFrame(
        [
            {"match_id": "m1", "side": "home"},
            {"match_id": "m1", "side": "away"},
            {"match_id": "m2", "side": "home"},
            {"match_id": "m2", "side": "away"},
        ]
    )
    mask = np.array([True, True, False, True])
    resultat = canonicaliser_masque_marche(feats, mask, "BTTS_Y", {"BTTS_Y"})

    assert resultat.tolist() == [True, False, True, False]
    assert feats.loc[resultat, "match_id"].is_unique


def test_marche_equipe_conserve_les_orientations_distinctes() -> None:
    feats = pd.DataFrame(
        [
            {"match_id": "m1", "side": "home"},
            {"match_id": "m1", "side": "away"},
        ]
    )
    mask = np.array([True, True])

    resultat = canonicaliser_masque_marche(
        feats,
        mask,
        "TEAM_O15_SELF",
        {"BTTS_Y"},
    )

    assert resultat.tolist() == [True, True]


def test_jointure_fournisseur_ambigue_est_rejetee() -> None:
    feats = pd.DataFrame(
        [
            {"match_id": "fixture-stable-1", "side": "home", "provider": "a"},
            {"match_id": "fixture-stable-1", "side": "away", "provider": "a"},
            {"match_id": "fixture-stable-1", "side": "home", "provider": "b"},
            {"match_id": "fixture-stable-1", "side": "away", "provider": "b"},
        ]
    )

    with pytest.raises(ValueError, match="cle metier"):
        canonicaliser_masque_marche(
            feats,
            np.ones(len(feats), dtype=bool),
            "O25",
            {"O25"},
        )

