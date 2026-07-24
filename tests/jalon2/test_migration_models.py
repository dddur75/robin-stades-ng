from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from pydantic import ValidationError

from robin.domain.enums import QualityStatus
from robin.migration.legacy import LegacyMappingStatus, migrate_legacy_frame
from robin.modeling.reference import (
    EloModel,
    MatchProbabilities,
    ShadowPrediction,
    consensus,
    estimate_expected_goals,
    market_probabilities,
    poisson_probabilities,
)


def legacy_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "match_id": ["m1", "m2"],
            "league": ["F1", "F1"],
            "season": ["2025-26", "2025-26"],
            "date": pd.to_datetime(["2025-08-01", "2025-08-08"], utc=True),
            "home": ["Paris", "Lyon"],
            "away": ["Lyon", "Paris"],
            "referee": ["Alex Martin", "Alex Martin"],
            "fthg": [2, 1],
            "ftag": [0, 1],
        }
    )


def test_migration_est_stable_non_destructive_et_collision_zero() -> None:
    frame = legacy_frame()
    before = frame.copy(deep=True)
    first, first_summary = migrate_legacy_frame(frame)
    second, second_summary = migrate_legacy_frame(frame)
    pd.testing.assert_frame_equal(frame, before)
    pd.testing.assert_frame_equal(first, second)
    assert first_summary == second_summary
    assert first_summary.collisions == 0


def test_noms_equipes_et_arbitres_restent_probables_et_exclus() -> None:
    mappings, _ = migrate_legacy_frame(legacy_frame())
    uncertain = mappings[mappings["entity_type"].isin(["team", "referee"])]
    assert set(uncertain["mapping_status"]) == {LegacyMappingStatus.PROBABLE.value}
    assert not uncertain["model_eligible_identity"].any()


def test_fixtures_et_competition_sont_resolues_par_regles_auditables() -> None:
    mappings, summary = migrate_legacy_frame(legacy_frame())
    certain = mappings[mappings["model_eligible_identity"]]
    assert set(certain["entity_type"]) == {"competition", "season", "fixture"}
    assert summary.certain_coverage > 0.4


def test_elo_reagit_au_resultat_sans_modifier_prediction_passee() -> None:
    elo = EloModel()
    before = elo.predict("Paris", "Lyon")
    elo.update("Paris", "Lyon", 3, 0)
    after = elo.predict("Paris", "Lyon")
    assert before.home < after.home
    assert before.home == elo.predict("Paris", "Lyon").model_copy(
        update={"home": before.home}
    ).home


@pytest.mark.parametrize("dixon_coles", [False, True])
def test_poisson_et_dixon_coles_sont_normalises(dixon_coles: bool) -> None:
    prediction = poisson_probabilities(1.6, 1.1, dixon_coles=dixon_coles)
    assert prediction.total == pytest.approx(1.0)
    assert prediction.home > prediction.away


def test_consensus_et_marche_sont_normalises() -> None:
    market = market_probabilities(2.0, 3.5, 4.0)
    combined = consensus(market, poisson_probabilities(1.5, 1.0))
    assert market.total == pytest.approx(1.0)
    assert combined.total == pytest.approx(1.0)


def test_estimation_buts_ignore_strictement_le_match_cible_et_le_futur() -> None:
    frame = legacy_frame()
    cutoff = datetime(2025, 8, 8, tzinfo=UTC)
    original = estimate_expected_goals(
        frame,
        home_team="Lyon",
        away_team="Paris",
        as_of_time=cutoff,
    )
    future = frame.copy()
    future.loc[len(future)] = {
        "match_id": "future",
        "league": "F1",
        "season": "2025-26",
        "date": cutoff + timedelta(days=1),
        "home": "Lyon",
        "away": "Paris",
        "referee": "Alex",
        "fthg": 20,
        "ftag": 20,
    }
    assert estimate_expected_goals(
        future,
        home_team="Lyon",
        away_team="Paris",
        as_of_time=cutoff,
    ) == original


def test_prediction_shadow_est_immuable_et_horodatee() -> None:
    prediction = ShadowPrediction(
        prediction_id="p1",
        fixture_id="f1",
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        as_of_time=datetime(2026, 8, 1, tzinfo=UTC),
        model_name="elo",
        model_version="1",
        dataset_version="d1",
        feature_version="f1",
        probability_home=0.5,
        probability_draw=0.25,
        probability_away=0.25,
        expected_home_goals=1.5,
        expected_away_goals=1.0,
        data_quality_status=QualityStatus.DERIVED,
        uncertainty_status="NORMAL",
    )
    with pytest.raises(ValidationError):
        prediction.probability_home = 0.9


def test_probabilites_hors_domaine_sont_refusees() -> None:
    with pytest.raises(ValidationError):
        MatchProbabilities(
            home=1.1,
            draw=0.0,
            away=0.0,
            expected_home_goals=1,
            expected_away_goals=1,
        )
