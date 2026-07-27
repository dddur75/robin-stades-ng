from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from robin.deep_football.persistence import persist_deep_football_evidence
from robin.storage.database import build_engine
from robin.storage.models import (
    Base,
    CoverageGateModel,
    DeepFeatureDefinitionModel,
    MatchupEvaluationModel,
    MatchupHypothesisModel,
)

HASH = "a" * 64


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _artifacts(root: Path) -> None:
    _write(
        root / "audit-summary.json",
        {
            "provider_calls": 0,
            "odds_api_credits": 0,
            "gates": {
                "TEAM_GATE": {
                    "status": "READY",
                    "reasons": ["exact pairing"],
                },
                "MARKET_GATE": {
                    "status": "READY",
                    "reasons": ["historical price"],
                },
                "PLAYER_GATE": {
                    "status": "BLOCKED_BY_TEMPORALITY",
                    "reasons": ["post match"],
                },
            },
            "coverage_matrix": [
                {
                    "competition": "Ligue 1",
                    "season": 2025,
                    "team_coverage": 1.0,
                    "market_fixtures": 306,
                    "player_fixture_estimate": 306,
                }
            ],
            "owner_hypotheses": [
                {
                    "hypothesis_id": f"H11-{index:03d}",
                    "eligible": False,
                    "blocking_gates": ["PLAYER_GATE"],
                }
                for index in range(1, 9)
            ],
        },
    )
    _write(
        root / "dataset-manifest.json",
        {
            "dataset_hash": HASH,
            "features": ["elo_difference", "home_form_5"],
        },
    )
    _write(
        root / "campaign-11a-summary.json",
        {
            "production_status": "PRODUCTION_LOCKED",
            "paired_1x2_rows": 200,
            "result_hash": "b" * 64,
            "folds": [],
            "models": {
                "B0_MARKET": {"log_loss": 1.0, "brier": 0.2},
                "B1_REGULARIZED_MULTINOMIAL": {
                    "log_loss": 1.1,
                    "brier": 0.21,
                    "delta_log_loss": 0.1,
                    "delta_brier": 0.01,
                },
                "B1_BOUNDED_GRADIENT_BOOSTING": {
                    "log_loss": 1.2,
                    "brier": 0.22,
                    "delta_log_loss": 0.2,
                    "delta_brier": 0.02,
                },
            },
            "statistics": {
                "sign_flip_p": 1.0,
                "family_q": 1.0,
                "global_q": 1.0,
            },
            "promotion": {"promoted": False, "status": "REJECTED"},
        },
    )


def test_compact_projection_is_idempotent_and_keeps_heavy_rows_out(
    tmp_path: Path,
) -> None:
    _artifacts(tmp_path)
    engine = build_engine(f"sqlite:///{tmp_path / 'j11.db'}")
    Base.metadata.create_all(engine)

    first = persist_deep_football_evidence(
        engine,
        tmp_path,
        code_revision="revision-1",
    )
    replay = persist_deep_football_evidence(
        engine,
        tmp_path,
        code_revision="revision-1",
    )

    assert first["inserted"] == {
        "feature_definitions": 2,
        "coverage_gates": 3,
        "hypotheses": 9,
        "evaluations": 10,
    }
    assert replay["inserted"] == {
        "feature_definitions": 0,
        "coverage_gates": 0,
        "hypotheses": 0,
        "evaluations": 0,
    }
    assert replay["feature_observations_inserted"] == 0
    with Session(engine) as session:
        assert session.scalar(
            select(func.count()).select_from(DeepFeatureDefinitionModel)
        ) == 2
        assert session.scalar(
            select(func.count()).select_from(CoverageGateModel)
        ) == 3
        assert session.scalar(
            select(func.count()).select_from(MatchupHypothesisModel)
        ) == 9
        assert session.scalar(
            select(func.count()).select_from(MatchupEvaluationModel)
        ) == 10

