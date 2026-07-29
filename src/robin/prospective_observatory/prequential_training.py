"""Controlled post-settlement challenger training policy."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping

from robin.prospective_observatory.contracts import canonical_json_bytes, canonical_sha256
from robin.prospective_observatory.prequential_contracts import (
    FIVE_LEAGUE_NAMES,
    FeatureSnapshot,
    FixtureSettlementRecord,
    ModelRole,
    ModelStatus,
    ModelVersion,
    PredictionMarket,
    PredictionStatus,
    TrainingDatasetManifest,
    TrainingDecision,
)
from robin.prospective_observatory.prequential_metrics import settlement_outcome
from robin.prospective_observatory.prequential_storage import (
    PrequentialArtifactRepository,
)

MINIMUM_NEW_FIXTURES = 30
MINIMUM_REPRESENTED_LEAGUES = 2
MINIMUM_TRAINING_INTERVAL = timedelta(days=1)
TRAINING_DEFERRED_INSUFFICIENT_NEW_SUPPORT = (
    "TRAINING_DEFERRED_INSUFFICIENT_NEW_SUPPORT"
)


def challenger_probabilities_from_artifact(
    artifact: Mapping[str, object],
    market: PredictionMarket,
) -> dict[str, float]:
    """Read the small empirical challenger artifact without implicit zero fill."""

    counts_value = artifact.get("counts_by_market")
    if not isinstance(counts_value, Mapping):
        raise ValueError("PREQUENTIAL_CHALLENGER_ARTIFACT_COUNTS_MISSING")
    market_counts = counts_value.get(market.value)
    if not isinstance(market_counts, Mapping):
        raise ValueError("PREQUENTIAL_CHALLENGER_MARKET_SUPPORT_MISSING")
    selections = (
        ("HOME", "DRAW", "AWAY")
        if market is PredictionMarket.ONE_X_TWO
        else ("OVER", "UNDER")
    )
    counts: dict[str, float] = {}
    for selection in selections:
        raw_count = market_counts.get(selection)
        if not isinstance(raw_count, (int, float)) or raw_count < 0:
            raise ValueError("PREQUENTIAL_CHALLENGER_COUNT_INVALID")
        counts[selection] = float(raw_count)
    smoothing = 1.0
    total = sum(counts.values()) + smoothing * len(selections)
    if total <= 0:
        raise ValueError("PREQUENTIAL_CHALLENGER_SUPPORT_INVALID")
    return {
        selection: (counts[selection] + smoothing) / total
        for selection in selections
    }


@dataclass(frozen=True, slots=True)
class EligibleTrainingExample:
    fixture_id: str
    competition: str
    settlement_id: str
    settled_at: datetime
    snapshot_id: str
    snapshot_hash: str
    market: str
    outcome: str


def eligible_training_examples(
    *,
    settlements: Iterable[FixtureSettlementRecord],
    snapshots: Iterable[FeatureSnapshot],
    training_cutoff: datetime,
) -> tuple[EligibleTrainingExample, ...]:
    snapshots_by_fixture: dict[tuple[str, str], list[FeatureSnapshot]] = {}
    for snapshot in snapshots:
        if snapshot.created_at <= snapshot.cutoff_at < training_cutoff:
            snapshots_by_fixture.setdefault(
                (snapshot.fixture_id, snapshot.market.value),
                [],
            ).append(snapshot)
    examples: list[EligibleTrainingExample] = []
    for settlement in sorted(
        settlements,
        key=lambda value: (value.settled_at, value.settlement_id),
    ):
        if (
            settlement.effective_status is not PredictionStatus.SETTLED
            or settlement.settled_at >= training_cutoff
        ):
            continue
        for (fixture_id, market), fixture_snapshots in snapshots_by_fixture.items():
            if fixture_id != settlement.result.fixture_id:
                continue
            snapshot = max(
                fixture_snapshots,
                key=lambda value: (
                    value.cutoff_at,
                    value.created_at,
                    value.snapshot_id,
                ),
            )
            outcome = settlement_outcome(settlement, snapshot.market)
            if outcome is None:
                continue
            examples.append(
                EligibleTrainingExample(
                    fixture_id=settlement.result.fixture_id,
                    competition=settlement.result.competition,
                    settlement_id=settlement.settlement_id,
                    settled_at=settlement.settled_at,
                    snapshot_id=snapshot.snapshot_id,
                    snapshot_hash=snapshot.snapshot_hash,
                    market=market,
                    outcome=outcome,
                )
            )
    # Keep the latest corrected settlement for each fixture and market.
    latest: dict[tuple[str, str], EligibleTrainingExample] = {}
    for example in examples:
        latest[(example.fixture_id, example.market)] = example
    return tuple(
        sorted(
            latest.values(),
            key=lambda value: (
                value.settled_at,
                value.fixture_id,
                value.market,
            ),
        )
    )


def train_challenger_if_eligible(
    *,
    repository: PrequentialArtifactRepository,
    previous_model: ModelVersion,
    settlements: Iterable[FixtureSettlementRecord],
    snapshots: Iterable[FeatureSnapshot],
    training_cutoff: datetime,
    code_revision: str,
    last_training_at: datetime | None = None,
    minimum_new_fixtures: int = MINIMUM_NEW_FIXTURES,
    minimum_leagues: int = MINIMUM_REPRESENTED_LEAGUES,
) -> TrainingDecision:
    if previous_model.role is not ModelRole.CHALLENGER:
        raise ValueError("ONLY_CHALLENGER_CAN_BE_TRAINED")
    if last_training_at is not None and (
        training_cutoff - last_training_at < MINIMUM_TRAINING_INTERVAL
    ):
        return TrainingDecision(
            status="TRAINING_DEFERRED_FREQUENCY_LIMIT",
            eligible_fixtures=0,
            represented_leagues=0,
            reason="ONE_TRAINING_PER_DAY_MAXIMUM",
        )
    all_examples = eligible_training_examples(
        settlements=settlements,
        snapshots=snapshots,
        training_cutoff=training_cutoff,
    )
    expected_competition = FIVE_LEAGUE_NAMES.get(previous_model.scope)
    if expected_competition is not None:
        all_examples = tuple(
            example
            for example in all_examples
            if example.competition == expected_competition
        )
    previous_cutoff = previous_model.training_cutoff
    new_examples = tuple(
        example
        for example in all_examples
        if previous_cutoff is None or example.settled_at > previous_cutoff
    )
    new_fixture_ids = {example.fixture_id for example in new_examples}
    represented = {example.competition for example in new_examples}
    if (
        len(new_fixture_ids) < minimum_new_fixtures
        or len(represented) < minimum_leagues
    ):
        return TrainingDecision(
            status=TRAINING_DEFERRED_INSUFFICIENT_NEW_SUPPORT,
            eligible_fixtures=len(new_fixture_ids),
            represented_leagues=len(represented),
            reason=(
                f"MINIMUM_{minimum_new_fixtures}_FIXTURES_"
                f"AND_{minimum_leagues}_LEAGUES_REQUIRED"
            ),
        )
    manifest_identity = canonical_sha256(
        {
            "previous_model": previous_model.registry_hash,
            "training_cutoff": training_cutoff.isoformat(),
            "fixtures": [example.fixture_id for example in all_examples],
            "settlements": [example.settlement_id for example in all_examples],
            "snapshots": [example.snapshot_hash for example in all_examples],
        }
    )
    latest_settlement_by_fixture = {
        example.fixture_id: example
        for example in all_examples
    }
    fixture_examples = tuple(
        latest_settlement_by_fixture[fixture_id]
        for fixture_id in sorted(latest_settlement_by_fixture)
    )
    counts_by_market: dict[str, Counter[str]] = {}
    for example in all_examples:
        counts_by_market.setdefault(example.market, Counter())[example.outcome] += 1
    training_metrics: dict[str, object] = {
        "fixtures": len(fixture_examples),
        "examples": len(all_examples),
        "represented_leagues": len(
            {example.competition for example in all_examples}
        ),
        "outcomes_by_market": {
            market: dict(sorted(counts.items()))
            for market, counts in sorted(counts_by_market.items())
        },
    }
    provisional_manifest = {
        "schema_version": "prequential-training-dataset-v1",
        "manifest_id": f"training-manifest-{manifest_identity}",
        "created_at": training_cutoff.isoformat(),
        "training_cutoff": training_cutoff.isoformat(),
        "fixture_ids": [example.fixture_id for example in fixture_examples],
        "settlement_ids": [
            example.settlement_id for example in fixture_examples
        ],
        "competitions": sorted({example.competition for example in all_examples}),
        "feature_snapshot_ids": [example.snapshot_id for example in all_examples],
        "feature_contract_hash": previous_model.feature_contract_hash,
        "hyperparameters": {
            "family": "EMPIRICAL_REGULARIZED_CHALLENGER_V1",
            "smoothing": 1.0,
        },
        "training_metrics": training_metrics,
        "code_revision": code_revision,
    }
    stored_manifest = repository.put_manifest(
        "training-manifests",
        provisional_manifest,
    )
    manifest = TrainingDatasetManifest(
        manifest_id=str(provisional_manifest["manifest_id"]),
        created_at=training_cutoff,
        training_cutoff=training_cutoff,
        fixture_ids=tuple(example.fixture_id for example in fixture_examples),
        settlement_ids=tuple(
            example.settlement_id for example in fixture_examples
        ),
        competitions=tuple(
            sorted({example.competition for example in all_examples})
        ),
        feature_snapshot_ids=tuple(
            example.snapshot_id for example in all_examples
        ),
        feature_contract_hash=previous_model.feature_contract_hash,
        hyperparameters={
            "family": "EMPIRICAL_REGULARIZED_CHALLENGER_V1",
            "smoothing": 1.0,
        },
        code_revision=code_revision,
        r2_key=stored_manifest.key,
        training_metrics=training_metrics,
    )
    artifact_payload = {
        "schema_version": "prequential-challenger-artifact-v1",
        "training_manifest_hash": manifest.manifest_hash,
        "training_cutoff": training_cutoff.isoformat(),
        "counts_by_market": {
            market: dict(sorted(counts.items()))
            for market, counts in sorted(counts_by_market.items())
        },
        "support_fixtures": len(fixture_examples),
        "support_examples": len(all_examples),
        "competitions": list(manifest.competitions),
        "promotion_status": "PROMOTION_LOCKED",
    }
    stored_artifact = repository.put_artifact(
        "challenger-models",
        canonical_json_bytes(artifact_payload),
    )
    version = (
        f"v-{training_cutoff.strftime('%Y%m%dT%H%M%SZ')}-"
        f"{stored_artifact.sha256[:12]}"
    )
    next_model = ModelVersion(
        model_id=previous_model.model_id,
        scope=previous_model.scope,
        role=ModelRole.CHALLENGER,
        version=version,
        artifact_sha256=stored_artifact.sha256,
        created_at=training_cutoff,
        training_cutoff=training_cutoff,
        feature_contract_hash=previous_model.feature_contract_hash,
        code_revision=code_revision,
        status=ModelStatus.ACTIVE,
        artifact_r2_key=stored_artifact.key,
        parent_version=previous_model.version,
    )
    return TrainingDecision(
        status="CHALLENGER_VERSION_CREATED",
        eligible_fixtures=len(new_fixture_ids),
        represented_leagues=len(represented),
        manifest=manifest,
        next_model=next_model,
    )


__all__ = [
    "EligibleTrainingExample",
    "MINIMUM_NEW_FIXTURES",
    "MINIMUM_REPRESENTED_LEAGUES",
    "MINIMUM_TRAINING_INTERVAL",
    "TRAINING_DEFERRED_INSUFFICIENT_NEW_SUPPORT",
    "challenger_probabilities_from_artifact",
    "eligible_training_examples",
    "train_challenger_if_eligible",
]
