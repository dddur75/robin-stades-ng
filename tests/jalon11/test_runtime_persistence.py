from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from robin.deep_football.contracts import (
    SCIENTIFIC_FLOAT_CONTRACT_VERSION,
    canonical_hash,
    scientific_evidence_hash,
)
from robin.deep_football.persistence import (
    AUTHORITATIVE_EVIDENCE_PUBLISHED_AT,
    AUTHORITATIVE_EVIDENCE_SOURCE_COMMIT,
    DATASET_VERSION,
    FROZEN_AT,
    LEGACY_NUMERIC_CAMPAIGN_RESULT_HASHES,
    PROTOCOL_AMENDMENT_HASH,
    PROTOCOL_AMENDMENT_PUBLISHED_AT,
    PROTOCOL_AMENDMENT_SOURCE_COMMIT,
    TEAM_HYPOTHESIS_VERSION,
    _legacy_hash_metrics,
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


def _evaluation_snapshot(row: MatchupEvaluationModel) -> str:
    return json.dumps(
        {
            column.name: getattr(row, column.name)
            for column in MatchupEvaluationModel.__table__.columns
        },
        default=str,
        sort_keys=True,
    )


def _primary_evaluation(session: Session) -> MatchupEvaluationModel:
    row = session.scalar(
        select(MatchupEvaluationModel).where(
            MatchupEvaluationModel.model_key == "B1_MARKET_PLUS_TEAM_REGULARIZED_MULTINOMIAL"
        )
    )
    assert row is not None
    return row


def _set_legacy_campaign_hash(
    row: MatchupEvaluationModel,
    campaign_result_hash: str,
) -> None:
    metrics = cast(
        dict[str, object],
        json.loads(json.dumps(row.metrics)),
    )
    authoritative = cast(
        dict[str, object],
        metrics["authoritative_evidence"],
    )
    authoritative["campaign_result_hash"] = campaign_result_hash
    evaluation_hash = _legacy_hash_metrics(
        {
            "hypothesis_id": "H11-A-TEAM-INCREMENTAL",
            "model_key": row.model_key,
            "metrics": metrics,
            "dataset_hash": row.dataset_hash,
        }
    )
    row.metrics = metrics
    row.evaluation_hash = evaluation_hash
    row.idempotency_key = f"j11:evaluation:{evaluation_hash}"


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _artifacts(root: Path) -> str:
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
    campaign: dict[str, object] = {
        "numeric_evidence_contract": SCIENTIFIC_FLOAT_CONTRACT_VERSION,
        "production_status": "PRODUCTION_LOCKED",
        "paired_1x2_rows": 200,
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
    }
    campaign_result_hash = scientific_evidence_hash(campaign)
    campaign["result_hash"] = campaign_result_hash
    _write(root / "campaign-11a-summary.json", campaign)
    return campaign_result_hash


def test_compact_projection_is_idempotent_and_keeps_heavy_rows_out(
    tmp_path: Path,
) -> None:
    campaign_result_hash = _artifacts(tmp_path)
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
            "campaign_result_hash": campaign_result_hash,
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


def test_known_legacy_float_noise_replays_without_mutating_rows(
    tmp_path: Path,
) -> None:
    _artifacts(tmp_path)
    engine = build_engine(f"sqlite:///{tmp_path / 'j11-legacy-numeric.db'}")
    Base.metadata.create_all(engine)
    _persist(engine, tmp_path, code_revision="creator-revision")
    legacy_campaign_hash = next(iter(LEGACY_NUMERIC_CAMPAIGN_RESULT_HASHES))

    before: dict[str, str] = {}
    with Session(engine) as session, session.begin():
        rows = list(
            session.scalars(
                select(MatchupEvaluationModel).where(
                    MatchupEvaluationModel.model_key != "NOT_RUN_DATA_GATE"
                )
            )
        )
        assert len(rows) == 6
        for row in rows:
            metrics = cast(
                dict[str, object],
                json.loads(json.dumps(row.metrics)),
            )
            authoritative = cast(
                dict[str, object],
                metrics["authoritative_evidence"],
            )
            authoritative["campaign_result_hash"] = legacy_campaign_hash
            if row.model_key == "B1_MARKET_PLUS_TEAM_REGULARIZED_MULTINOMIAL":
                model_metrics = cast(dict[str, object], metrics["model"])
                model_metrics["brier"] = float(model_metrics["brier"]) + 1e-16
                row.effect = float(row.effect) + 1e-18
                row.p_value = float(row.p_value) + 1e-16
            evaluation_hash = _legacy_hash_metrics(
                {
                    "hypothesis_id": "H11-A-TEAM-INCREMENTAL",
                    "model_key": row.model_key,
                    "metrics": metrics,
                    "dataset_hash": row.dataset_hash,
                }
            )
            row.metrics = metrics
            row.evaluation_hash = evaluation_hash
            row.idempotency_key = f"j11:evaluation:{evaluation_hash}"
            before[row.id] = _evaluation_snapshot(row)

    replay = _persist(engine, tmp_path, code_revision="replay-revision")

    assert sum(cast(dict[str, int], replay["inserted"]).values()) == 0
    assert replay["legacy_numeric_equivalent_evaluations"] == 6
    with Session(engine) as session:
        after = {
            row.id: _evaluation_snapshot(row)
            for row in session.scalars(
                select(MatchupEvaluationModel).where(
                    MatchupEvaluationModel.model_key != "NOT_RUN_DATA_GATE"
                )
            )
        }
    assert after == before


def test_material_evaluation_drift_still_fails_closed(
    tmp_path: Path,
) -> None:
    _artifacts(tmp_path)
    engine = build_engine(f"sqlite:///{tmp_path / 'j11-material-drift.db'}")
    Base.metadata.create_all(engine)
    _persist(engine, tmp_path, code_revision="creator-revision")
    campaign_path = tmp_path / "campaign-11a-summary.json"
    campaign = cast(
        dict[str, object],
        json.loads(campaign_path.read_text(encoding="utf-8")),
    )
    models = cast(dict[str, object], campaign["models"])
    primary = cast(
        dict[str, object],
        models["B1_MARKET_PLUS_TEAM_REGULARIZED_MULTINOMIAL"],
    )
    primary["log_loss"] = float(primary["log_loss"]) + 1e-6
    campaign.pop("result_hash")
    campaign["result_hash"] = scientific_evidence_hash(campaign)
    _write(campaign_path, campaign)

    with pytest.raises(
        ValueError,
        match="JALON11_IMMUTABLE_REPLAY_MISMATCH:matchup_evaluations",
    ):
        _persist(engine, tmp_path, code_revision="drift-revision")


def test_material_drift_inside_a_coherent_legacy_row_fails_closed(
    tmp_path: Path,
) -> None:
    _artifacts(tmp_path)
    engine = build_engine(f"sqlite:///{tmp_path / 'j11-legacy-material.db'}")
    Base.metadata.create_all(engine)
    _persist(engine, tmp_path, code_revision="creator-revision")
    with Session(engine) as session, session.begin():
        primary = _primary_evaluation(session)
        _set_legacy_campaign_hash(
            primary,
            next(iter(LEGACY_NUMERIC_CAMPAIGN_RESULT_HASHES)),
        )
        metrics = cast(
            dict[str, object],
            json.loads(json.dumps(primary.metrics)),
        )
        model_metrics = cast(dict[str, object], metrics["model"])
        model_metrics["log_loss"] = float(model_metrics["log_loss"]) + 1e-6
        evaluation_hash = _legacy_hash_metrics(
            {
                "hypothesis_id": "H11-A-TEAM-INCREMENTAL",
                "model_key": primary.model_key,
                "metrics": metrics,
                "dataset_hash": primary.dataset_hash,
            }
        )
        primary.metrics = metrics
        primary.evaluation_hash = evaluation_hash
        primary.idempotency_key = f"j11:evaluation:{evaluation_hash}"

    with pytest.raises(
        ValueError,
        match="JALON11_IMMUTABLE_REPLAY_MISMATCH:matchup_evaluations",
    ):
        _persist(engine, tmp_path, code_revision="replay-revision")


def test_unallowlisted_legacy_campaign_hash_fails_closed(
    tmp_path: Path,
) -> None:
    _artifacts(tmp_path)
    engine = build_engine(f"sqlite:///{tmp_path / 'j11-unallowlisted.db'}")
    Base.metadata.create_all(engine)
    _persist(engine, tmp_path, code_revision="creator-revision")
    with Session(engine) as session, session.begin():
        _set_legacy_campaign_hash(_primary_evaluation(session), "c" * 64)

    with pytest.raises(
        ValueError,
        match="JALON11_IMMUTABLE_REPLAY_MISMATCH:matchup_evaluations",
    ):
        _persist(engine, tmp_path, code_revision="replay-revision")


def test_corrupt_legacy_evaluation_hash_fails_closed(
    tmp_path: Path,
) -> None:
    _artifacts(tmp_path)
    engine = build_engine(f"sqlite:///{tmp_path / 'j11-corrupt-legacy.db'}")
    Base.metadata.create_all(engine)
    _persist(engine, tmp_path, code_revision="creator-revision")
    with Session(engine) as session, session.begin():
        primary = _primary_evaluation(session)
        _set_legacy_campaign_hash(
            primary,
            next(iter(LEGACY_NUMERIC_CAMPAIGN_RESULT_HASHES)),
        )
        primary.evaluation_hash = "d" * 64
        primary.idempotency_key = f"j11:evaluation:{primary.evaluation_hash}"

    with pytest.raises(
        ValueError,
        match="JALON11_IMMUTABLE_REPLAY_MISMATCH:matchup_evaluations",
    ):
        _persist(engine, tmp_path, code_revision="replay-revision")


def test_legacy_replay_does_not_relax_non_float_row_fields(
    tmp_path: Path,
) -> None:
    _artifacts(tmp_path)
    engine = build_engine(f"sqlite:///{tmp_path / 'j11-status-drift.db'}")
    Base.metadata.create_all(engine)
    _persist(engine, tmp_path, code_revision="creator-revision")
    with Session(engine) as session, session.begin():
        primary = _primary_evaluation(session)
        _set_legacy_campaign_hash(
            primary,
            next(iter(LEGACY_NUMERIC_CAMPAIGN_RESULT_HASHES)),
        )
        primary.status = "DATA_GATE_BLOCKED"

    with pytest.raises(
        ValueError,
        match="JALON11_IMMUTABLE_REPLAY_MISMATCH:matchup_evaluations",
    ):
        _persist(engine, tmp_path, code_revision="replay-revision")


def test_invalid_campaign_result_hash_is_rejected_before_persistence(
    tmp_path: Path,
) -> None:
    _artifacts(tmp_path)
    engine = build_engine(f"sqlite:///{tmp_path / 'j11-invalid-hash.db'}")
    Base.metadata.create_all(engine)
    campaign_path = tmp_path / "campaign-11a-summary.json"
    campaign = cast(
        dict[str, object],
        json.loads(campaign_path.read_text(encoding="utf-8")),
    )
    campaign["result_hash"] = "f" * 64
    _write(campaign_path, campaign)

    with pytest.raises(
        ValueError,
        match="JALON11_CAMPAIGN_RESULT_HASH_MISMATCH",
    ):
        _persist(engine, tmp_path, code_revision="invalid-hash-revision")
