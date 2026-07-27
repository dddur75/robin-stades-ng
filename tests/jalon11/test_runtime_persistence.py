from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from robin.deep_football.contracts import canonical_hash
from robin.deep_football.persistence import (
    AUTHORITATIVE_EVIDENCE_PUBLISHED_AT,
    AUTHORITATIVE_EVIDENCE_SOURCE_COMMIT,
    DATASET_VERSION,
    FROZEN_AT,
    PROTOCOL_AMENDMENT_HASH,
    PROTOCOL_AMENDMENT_PUBLISHED_AT,
    PROTOCOL_AMENDMENT_SOURCE_COMMIT,
    TEAM_HYPOTHESIS_VERSION,
    persist_deep_football_evidence,
)
from robin.storage.database import build_engine
from robin.storage.models import (
    Base,
    CoverageGateModel,
    DeepFeatureDefinitionModel,
    MatchupEvaluationModel,
    MatchupHypothesisModel,
)

HASH = "a" * 64
AMENDMENT_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "deep-football-v1-amendment-1.json"
)


def _protocol_amendment() -> dict[str, object]:
    value: object = json.loads(AMENDMENT_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _persist(
    engine: Engine,
    root: Path,
    *,
    code_revision: str,
) -> dict[str, object]:
    return persist_deep_football_evidence(
        engine,
        root,
        code_revision=code_revision,
        protocol_amendment=_protocol_amendment(),
        protocol_amendment_source_commit=PROTOCOL_AMENDMENT_SOURCE_COMMIT,
        protocol_amendment_published_at=PROTOCOL_AMENDMENT_PUBLISHED_AT,
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


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
                    "status": "PARTIAL",
                    "reasons": ["row-level observed_at unavailable"],
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
                "B0_MARKET_RECALIBRATED_TRAIN_ONLY": {
                    "log_loss": 1.01,
                    "brier": 0.201,
                },
                "B1_TEAM_ONLY_REGULARIZED_MULTINOMIAL": {
                    "log_loss": 1.1,
                    "brier": 0.21,
                    "delta_log_loss": 0.1,
                    "delta_brier": 0.01,
                    "status": "POST_CONTRACT_DIAGNOSTIC_NON_PROMOTABLE",
                },
                "B1_TEAM_ONLY_BOUNDED_GRADIENT_BOOSTING": {
                    "log_loss": 1.2,
                    "brier": 0.22,
                    "delta_log_loss": 0.2,
                    "delta_brier": 0.02,
                    "status": "POST_CONTRACT_DIAGNOSTIC_NON_PROMOTABLE",
                },
                "B1_TEAM_ONLY_POISSON": {
                    "log_loss": 1.3,
                    "brier": 0.23,
                    "delta_log_loss": 0.3,
                    "delta_brier": 0.03,
                    "status": "POST_CONTRACT_DIAGNOSTIC_NON_PROMOTABLE",
                },
                "B1_TEAM_ONLY_DIXON_COLES": {
                    "log_loss": 1.4,
                    "brier": 0.24,
                    "delta_log_loss": 0.4,
                    "delta_brier": 0.04,
                    "status": "POST_CONTRACT_DIAGNOSTIC_NON_PROMOTABLE",
                },
                "B1_MARKET_PLUS_TEAM_REGULARIZED_MULTINOMIAL": {
                    "reference": "B0_MARKET_RECALIBRATED_TRAIN_ONLY",
                    "log_loss": 1.02,
                    "brier": 0.202,
                    "delta_log_loss": 0.01,
                    "delta_brier": 0.001,
                    "status": ("PRIMARY_CORRECTIVE_NON_PROMOTABLE_TEAM_GATE_PARTIAL"),
                },
                "B1_MARKET_PLUS_TEAM_BOUNDED_GRADIENT_BOOSTING": {
                    "reference": "B0_MARKET_RECALIBRATED_TRAIN_ONLY",
                    "log_loss": 1.03,
                    "brier": 0.203,
                    "delta_log_loss": 0.02,
                    "delta_brier": 0.002,
                    "status": "POST_CONTRACT_DIAGNOSTIC_NON_PROMOTABLE",
                },
                "primary_for_inference": ("B1_MARKET_PLUS_TEAM_REGULARIZED_MULTINOMIAL"),
            },
            "statistics": {
                "cr1_one_sided_p": 0.9638269233447452,
                "sign_flip_p": 0.961,
                "family_q": 0.9638269233447452,
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

    first = _persist(
        engine,
        tmp_path,
        code_revision="revision-1",
    )
    replay = _persist(
        engine,
        tmp_path,
        code_revision="revision-1",
    )

    assert first["inserted"] == {
        "feature_definitions": 2,
        "coverage_gates": 3,
        "hypotheses": 9,
        "evaluations": 14,
    }
    assert replay["inserted"] == {
        "feature_definitions": 0,
        "coverage_gates": 0,
        "hypotheses": 0,
        "evaluations": 0,
    }
    assert replay["feature_observations_inserted"] == 0
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(DeepFeatureDefinitionModel)) == 2
        assert session.scalar(select(func.count()).select_from(CoverageGateModel)) == 3
        assert session.scalar(select(func.count()).select_from(MatchupHypothesisModel)) == 9
        assert session.scalar(select(func.count()).select_from(MatchupEvaluationModel)) == 14
        team_hypothesis = session.scalar(
            select(MatchupHypothesisModel).where(
                MatchupHypothesisModel.hypothesis_id == "H11-A-TEAM-INCREMENTAL"
            )
        )
        assert team_hypothesis is not None
        assert team_hypothesis.hypothesis_version == TEAM_HYPOTHESIS_VERSION
        protocol = team_hypothesis.protocol
        assert protocol["frozen_before_results"] is False
        assert protocol["prior_team_only_diagnostics_seen"] is True
        assert protocol["promotion_eligible"] is False
        assert protocol["protocol_amendment"] == _protocol_amendment()
        assert protocol["protocol_amendment_hash"] == PROTOCOL_AMENDMENT_HASH
        assert protocol["protocol_amendment_source_commit"] == PROTOCOL_AMENDMENT_SOURCE_COMMIT
        assert protocol["protocol_amendment_published_at"] == (
            PROTOCOL_AMENDMENT_PUBLISHED_AT.isoformat()
        )
        assert team_hypothesis.preregistration_hash == canonical_hash(protocol)
        assert _utc(team_hypothesis.registered_at) == PROTOCOL_AMENDMENT_PUBLISHED_AT
        assert _utc(team_hypothesis.frozen_at) == PROTOCOL_AMENDMENT_PUBLISHED_AT

        model_evaluations = list(
            session.scalars(
                select(MatchupEvaluationModel).where(
                    MatchupEvaluationModel.model_key != "NOT_RUN_DATA_GATE"
                )
            )
        )
        assert len(model_evaluations) == 6
        primary = next(
            row
            for row in model_evaluations
            if row.model_key == "B1_MARKET_PLUS_TEAM_REGULARIZED_MULTINOMIAL"
        )
        assert primary.p_value == pytest.approx(0.9638269233447452)
        assert primary.q_value_family == pytest.approx(0.9638269233447452)
        assert primary.q_value_global == pytest.approx(1.0)
        assert primary.metrics["inference"] == {
            "eligible": True,
            "multiplicity_included": True,
            "p_value_rule": "MAX_CR1_AND_SIGN_FLIP",
            "promotion_eligible": False,
        }
        assert primary.metrics["statistics"] is not None
        assert primary.metrics["authoritative_evidence"] == {
            "source_commit": AUTHORITATIVE_EVIDENCE_SOURCE_COMMIT,
            "published_at": AUTHORITATIVE_EVIDENCE_PUBLISHED_AT.isoformat(),
            "campaign_result_hash": "b" * 64,
            "dataset_hash": HASH,
        }
        diagnostics = [row for row in model_evaluations if row.id != primary.id]
        assert len(diagnostics) == 5
        for diagnostic in diagnostics:
            assert diagnostic.p_value is None
            assert diagnostic.q_value_family is None
            assert diagnostic.q_value_global is None
            assert diagnostic.status == ("POST_CONTRACT_DIAGNOSTIC_NON_PROMOTABLE")
            assert diagnostic.metrics["statistics"] is None
            assert diagnostic.metrics["inference"] == {
                "eligible": False,
                "multiplicity_included": False,
                "p_value_rule": "NOT_TESTED_DIAGNOSTIC",
                "promotion_eligible": False,
            }
        blocked_owner_evaluations = list(
            session.scalars(
                select(MatchupEvaluationModel).where(
                    MatchupEvaluationModel.model_key == "NOT_RUN_DATA_GATE"
                )
            )
        )
        assert len(blocked_owner_evaluations) == 8
        assert all(
            row.p_value is None and row.q_value_family is None and row.q_value_global is None
            for row in blocked_owner_evaluations
        )
        assert all(
            _utc(row.evaluated_at) == AUTHORITATIVE_EVIDENCE_PUBLISHED_AT
            for row in model_evaluations
        )
        assert all(
            _utc(row.evaluated_at) == AUTHORITATIVE_EVIDENCE_PUBLISHED_AT
            for row in blocked_owner_evaluations
        )
        assert all(
            _utc(row.evaluated_at) == AUTHORITATIVE_EVIDENCE_PUBLISHED_AT
            for row in session.scalars(select(CoverageGateModel))
        )
        assert AUTHORITATIVE_EVIDENCE_PUBLISHED_AT > (PROTOCOL_AMENDMENT_PUBLISHED_AT)


def test_replay_from_later_commit_preserves_creator_revision(
    tmp_path: Path,
) -> None:
    _artifacts(tmp_path)
    engine = build_engine(f"sqlite:///{tmp_path / 'j11-revision.db'}")
    Base.metadata.create_all(engine)

    first = _persist(
        engine,
        tmp_path,
        code_revision="branch-revision",
    )
    replay = _persist(
        engine,
        tmp_path,
        code_revision="merge-revision",
    )

    first_inserted = cast(dict[str, int], first["inserted"])
    replay_inserted = cast(dict[str, int], replay["inserted"])
    assert sum(first_inserted.values()) == 28
    assert sum(replay_inserted.values()) == 0
    with Session(engine) as session:
        revisions = {
            str(value)
            for value in session.scalars(select(DeepFeatureDefinitionModel.code_revision))
        }
    assert revisions == {"branch-revision"}


def test_corrective_protocol_supersedes_a_legacy_team_protocol(
    tmp_path: Path,
) -> None:
    _artifacts(tmp_path)
    engine = build_engine(f"sqlite:///{tmp_path / 'j11-supersedes.db'}")
    Base.metadata.create_all(engine)
    legacy_id = "legacy-h11-a"
    with Session(engine) as session, session.begin():
        session.add(
            MatchupHypothesisModel(
                id=legacy_id,
                hypothesis_id="H11-A-TEAM-INCREMENTAL",
                hypothesis_version="1.0.0",
                title="Legacy Team Diagnostic",
                family="team",
                hypothesis="Legacy team-only comparison.",
                protocol={"frozen_before_results": True},
                required_gates=["TEAM_GATE", "MARKET_GATE"],
                status="DATA_GATE_BLOCKED",
                preregistration_hash="c" * 64,
                dataset_version=DATASET_VERSION,
                dataset_hash=HASH,
                code_revision="legacy-revision",
                registered_at=FROZEN_AT,
                frozen_at=FROZEN_AT,
                supersedes_id=None,
                append_only=True,
                simulation=True,
            )
        )

    _persist(engine, tmp_path, code_revision="corrective-revision")

    with Session(engine) as session:
        corrective = session.scalar(
            select(MatchupHypothesisModel).where(
                MatchupHypothesisModel.hypothesis_id == "H11-A-TEAM-INCREMENTAL",
                MatchupHypothesisModel.hypothesis_version == TEAM_HYPOTHESIS_VERSION,
            )
        )
        assert corrective is not None
        assert corrective.supersedes_id == legacy_id
        legacy = session.get(MatchupHypothesisModel, legacy_id)
        assert legacy is not None
        assert legacy.protocol == {"frozen_before_results": True}


def test_protocol_amendment_provenance_is_validated(
    tmp_path: Path,
) -> None:
    _artifacts(tmp_path)
    engine = build_engine(f"sqlite:///{tmp_path / 'j11-amendment.db'}")
    Base.metadata.create_all(engine)
    mutated = _protocol_amendment()
    mutated["status"] = "PREREGISTERED"
    with pytest.raises(
        ValueError,
        match="JALON11_PROTOCOL_AMENDMENT_HASH_MISMATCH",
    ):
        persist_deep_football_evidence(
            engine,
            tmp_path,
            code_revision="revision",
            protocol_amendment=mutated,
            protocol_amendment_source_commit=(PROTOCOL_AMENDMENT_SOURCE_COMMIT),
            protocol_amendment_published_at=(PROTOCOL_AMENDMENT_PUBLISHED_AT),
        )
    with pytest.raises(
        ValueError,
        match="JALON11_PROTOCOL_AMENDMENT_SOURCE_COMMIT_MISMATCH",
    ):
        persist_deep_football_evidence(
            engine,
            tmp_path,
            code_revision="revision",
            protocol_amendment=_protocol_amendment(),
            protocol_amendment_source_commit="d" * 40,
            protocol_amendment_published_at=(PROTOCOL_AMENDMENT_PUBLISHED_AT),
        )
    with pytest.raises(
        ValueError,
        match="JALON11_PROTOCOL_AMENDMENT_PUBLISHED_AT_MISMATCH",
    ):
        persist_deep_football_evidence(
            engine,
            tmp_path,
            code_revision="revision",
            protocol_amendment=_protocol_amendment(),
            protocol_amendment_source_commit=(PROTOCOL_AMENDMENT_SOURCE_COMMIT),
            protocol_amendment_published_at=datetime(
                2026,
                7,
                27,
                12,
                tzinfo=UTC,
            ),
        )
