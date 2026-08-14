"""Controlled post-settlement challenger training policy."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping

from robin.prospective_observatory.contracts import (
    canonical_json_bytes,
    canonical_sha256,
    ensure_utc,
)
from robin.prospective_observatory.feature_snapshots import FeatureSnapshotRegistry
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


def training_manifest_record_id(
    *,
    previous_model_registry_hash: str,
    training_cutoff: datetime,
    examples: Iterable[EligibleTrainingExample],
) -> str:
    cutoff = ensure_utc(training_cutoff, field="training_cutoff")
    selected = tuple(examples)
    return "training-manifest-" + canonical_sha256(
        {
            "previous_model": previous_model_registry_hash,
            "training_cutoff": cutoff.isoformat(),
            "fixtures": [example.fixture_id for example in selected],
            "settlements": [example.settlement_id for example in selected],
            "snapshots": [example.snapshot_hash for example in selected],
        }
    )


def challenger_model_version(
    *,
    training_cutoff: datetime,
    artifact_sha256: str,
) -> str:
    cutoff = ensure_utc(training_cutoff, field="training_cutoff")
    return f"v-{cutoff.strftime('%Y%m%dT%H%M%SZ')}-{artifact_sha256[:12]}"


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
    fixture_record_id: str
    fixture_id: str
    competition: str
    settlement_id: str
    settled_at: datetime
    snapshot_id: str
    snapshot_hash: str
    snapshot_cutoff_at: datetime
    snapshot_created_at: datetime
    feature_contract_hash: str
    market: str
    outcome: str


def eligible_training_examples(
    *,
    settlements: Iterable[FixtureSettlementRecord],
    snapshots: Iterable[FeatureSnapshot],
    training_cutoff: datetime,
    required_feature_contract_hash: str | None = None,
) -> tuple[EligibleTrainingExample, ...]:
    cutoff = ensure_utc(training_cutoff, field="training_cutoff")
    candidate_snapshots = tuple(
        snapshot
        for snapshot in snapshots
        if snapshot.created_at <= snapshot.cutoff_at < cutoff
    )

    # Reconstruct the append-only correction chain before applying any
    # availability filter.  A terminal correction that removes evidence must
    # invalidate the older value, even when its business cutoff moved earlier.
    snapshot_registry = FeatureSnapshotRegistry()
    pending = list(candidate_snapshots)
    while pending:
        progressed = False
        for candidate in sorted(
            tuple(pending),
            key=lambda value: (value.created_at, value.snapshot_id),
        ):
            if (
                candidate.supersedes_id is not None
                and snapshot_registry.get(candidate.supersedes_id) is None
            ):
                continue
            try:
                snapshot_registry.append(candidate)
            except ValueError as error:
                raise ValueError(
                    "PREQUENTIAL_TRAINING_SNAPSHOT_CHAIN_INVALID"
                ) from error
            pending.remove(candidate)
            progressed = True
        if not progressed:
            raise ValueError("PREQUENTIAL_TRAINING_SNAPSHOT_CHAIN_INVALID")

    snapshots_by_fixture: dict[
        tuple[str, object, str, str],
        list[FeatureSnapshot],
    ] = {}
    for snapshot in candidate_snapshots:
        snapshots_by_fixture.setdefault(
            (
                snapshot.fixture_record_id,
                snapshot.cutoff_name,
                snapshot.market.value,
                snapshot.feature_contract_version,
            ),
            [],
        ).append(snapshot)

    snapshot_heads: dict[tuple[str, object, str, str], FeatureSnapshot] = {}
    for key, snapshot_candidates in snapshots_by_fixture.items():
        superseded_ids = {
            candidate.supersedes_id
            for candidate in snapshot_candidates
            if candidate.supersedes_id is not None
        }
        exact_snapshot_head = tuple(
            candidate
            for candidate in snapshot_candidates
            if candidate.snapshot_id not in superseded_ids
        )
        if len(exact_snapshot_head) != 1:
            raise ValueError("PREQUENTIAL_TRAINING_SNAPSHOT_HEAD_AMBIGUOUS")
        snapshot_heads[key] = exact_snapshot_head[0]

    logical_snapshot_candidates: dict[
        tuple[str, str],
        list[FeatureSnapshot],
    ] = {}
    for (_, _, market, _), snapshot in snapshot_heads.items():
        logical_snapshot_candidates.setdefault(
            (snapshot.fixture_id, market),
            [],
        ).append(snapshot)
    logical_snapshot_heads: dict[tuple[str, str], FeatureSnapshot] = {}
    for logical_key, candidates in logical_snapshot_candidates.items():
        logical_head_position = max(candidate.created_at for candidate in candidates)
        exact_logical_head = tuple(
            candidate
            for candidate in candidates
            if candidate.created_at == logical_head_position
        )
        if len({candidate.fixture_record_id for candidate in exact_logical_head}) > 1:
            raise ValueError(
                "PREQUENTIAL_TRAINING_LOGICAL_REVISION_AMBIGUOUS"
            )
        latest_cutoff = max(candidate.cutoff_at for candidate in exact_logical_head)
        latest_cutoff_heads = tuple(
            candidate
            for candidate in exact_logical_head
            if candidate.cutoff_at == latest_cutoff
        )
        if len({candidate.snapshot_hash for candidate in latest_cutoff_heads}) != 1:
            raise ValueError("PREQUENTIAL_TRAINING_LOGICAL_REVISION_AMBIGUOUS")
        logical_snapshot_heads[logical_key] = min(
            latest_cutoff_heads,
            key=lambda candidate: (
                candidate.fixture_record_id,
                candidate.snapshot_id,
            ),
        )

    settlements_by_record: dict[str, list[FixtureSettlementRecord]] = {}
    for candidate_settlement in settlements:
        if candidate_settlement.settled_at < cutoff:
            settlements_by_record.setdefault(
                candidate_settlement.result.fixture_record_id,
                [],
            ).append(candidate_settlement)
    settlement_heads: dict[str, FixtureSettlementRecord] = {}
    for fixture_record_id, settlement_candidates in settlements_by_record.items():
        settlement_head_position = max(
            (candidate.settled_at, candidate.result.result_version)
            for candidate in settlement_candidates
        )
        exact_settlement_head = tuple(
            candidate
            for candidate in settlement_candidates
            if (
                candidate.settled_at,
                candidate.result.result_version,
            )
            == settlement_head_position
        )
        if (
            len(
                {
                    candidate.settlement_hash
                    for candidate in exact_settlement_head
                }
            )
            != 1
        ):
            raise ValueError("PREQUENTIAL_TRAINING_SETTLEMENT_HEAD_AMBIGUOUS")
        settlement_heads[fixture_record_id] = min(
            exact_settlement_head,
            key=lambda candidate: candidate.settlement_id,
        )

    examples: list[EligibleTrainingExample] = []
    for (_, market), snapshot in sorted(
        logical_snapshot_heads.items(),
        key=lambda item: item[0],
    ):
        fixture_record_id = snapshot.fixture_record_id
        if (
            required_feature_contract_hash is not None
            and snapshot.feature_contract_hash != required_feature_contract_hash
        ):
            raise ValueError("PREQUENTIAL_TRAINING_FEATURE_CONTRACT_MISMATCH")
        if snapshot.missingness.get("market", True) or snapshot.missingness.get(
            "team",
            True,
        ):
            continue
        selected_settlement = settlement_heads.get(fixture_record_id)
        if (
            selected_settlement is None
            or selected_settlement.effective_status
            is not PredictionStatus.SETTLED
        ):
            continue
        if (
            snapshot.fixture_id != selected_settlement.result.fixture_id
            or snapshot.competition != selected_settlement.result.competition
        ):
            raise ValueError(
                "PREQUENTIAL_TRAINING_SNAPSHOT_SETTLEMENT_LINEAGE_MISMATCH"
            )
        outcome = settlement_outcome(selected_settlement, snapshot.market)
        if outcome is None:
            continue
        examples.append(
            EligibleTrainingExample(
                fixture_record_id=selected_settlement.result.fixture_record_id,
                fixture_id=selected_settlement.result.fixture_id,
                competition=selected_settlement.result.competition,
                settlement_id=selected_settlement.settlement_id,
                settled_at=selected_settlement.settled_at,
                snapshot_id=snapshot.snapshot_id,
                snapshot_hash=snapshot.snapshot_hash,
                snapshot_cutoff_at=snapshot.cutoff_at,
                snapshot_created_at=snapshot.created_at,
                feature_contract_hash=snapshot.feature_contract_hash,
                market=market,
                outcome=outcome,
            )
        )

    return tuple(
        sorted(
            examples,
            key=lambda value: (
                value.settled_at,
                value.fixture_id,
                value.market,
                value.fixture_record_id,
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
    cutoff = ensure_utc(training_cutoff, field="training_cutoff")
    if previous_model.role is not ModelRole.CHALLENGER:
        raise ValueError("ONLY_CHALLENGER_CAN_BE_TRAINED")
    if previous_model.created_at > cutoff or (
        previous_model.training_cutoff is not None
        and previous_model.training_cutoff > cutoff
    ):
        raise ValueError("PREQUENTIAL_PARENT_MODEL_AFTER_TRAINING_CUTOFF")
    normalized_last_training_at = (
        ensure_utc(last_training_at, field="last_training_at")
        if last_training_at is not None
        else None
    )
    if normalized_last_training_at is not None and normalized_last_training_at > cutoff:
        raise ValueError("PREQUENTIAL_LAST_TRAINING_AFTER_CUTOFF")
    if normalized_last_training_at is not None and (
        cutoff - normalized_last_training_at < MINIMUM_TRAINING_INTERVAL
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
        training_cutoff=cutoff,
        required_feature_contract_hash=previous_model.feature_contract_hash,
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
    manifest_id = training_manifest_record_id(
        previous_model_registry_hash=previous_model.registry_hash,
        training_cutoff=cutoff,
        examples=all_examples,
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
        "manifest_id": manifest_id,
        "created_at": cutoff.isoformat(),
        "training_cutoff": cutoff.isoformat(),
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
        created_at=cutoff,
        training_cutoff=cutoff,
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
        "training_cutoff": cutoff.isoformat(),
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
    version = challenger_model_version(
        training_cutoff=cutoff,
        artifact_sha256=stored_artifact.sha256,
    )
    next_model = ModelVersion(
        model_id=previous_model.model_id,
        scope=previous_model.scope,
        role=ModelRole.CHALLENGER,
        version=version,
        artifact_sha256=stored_artifact.sha256,
        created_at=cutoff,
        training_cutoff=cutoff,
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
    "challenger_model_version",
    "eligible_training_examples",
    "training_manifest_record_id",
    "train_challenger_if_eligible",
]
