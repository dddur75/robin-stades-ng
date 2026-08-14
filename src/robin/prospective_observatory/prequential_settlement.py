"""Idempotent settlement of frozen predictions from verified final results."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime

from robin.domain.enums import DataAvailability
from robin.prospective_observatory.contracts import canonical_sha256
from robin.prospective_observatory.prequential_contracts import (
    FixtureResultStatus,
    FixtureSettlementRecord,
    FrozenPredictionRecord,
    PredictionScore,
    PredictionStatus,
    VerifiedFixtureResult,
    score_record_id,
    settlement_record_id,
)
from robin.prospective_observatory.prequential_metrics import score_prediction
from robin.prospective_observatory.prequential_storage import (
    ArtifactIntegrityError,
    PrequentialArtifactRepository,
)
from robin.temporal.lineage import parse_utc

FINAL_SCORE_STATUSES = {
    FixtureResultStatus.FINISHED,
    FixtureResultStatus.CORRECTED,
}
FINAL_VOID_STATUSES = {
    FixtureResultStatus.CANCELLED,
    FixtureResultStatus.ABANDONED,
}


def _provider_result_guard_id(
    *,
    fixture_id: str,
    fixture_record_id: str,
    provider_fixture_id: str,
    attempt: int,
) -> str:
    return canonical_sha256(
        {
            "fixture_id": fixture_id,
            "fixture_record_id": fixture_record_id,
            "provider_fixture_id": provider_fixture_id,
            "attempt": attempt,
            "operation": "VERIFY_FINAL_RESULT",
        }
    )


def _content_addressed_json_values(
    repository: PrequentialArtifactRepository,
    *,
    kind: str,
) -> tuple[dict[str, object], ...]:
    """Read valid immutable JSON objects without letting unrelated damage leak in."""

    prefix = f"{repository.namespace}/{kind}/"
    values: list[dict[str, object]] = []
    for key in repository.store.iter_keys(prefix):
        filename = key.rsplit("/", 1)[-1]
        if not filename.endswith(".json"):
            continue
        digest = filename[:-5]
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            continue
        try:
            body = json.loads(repository.read_verified(key, digest))
        except (
            ArtifactIntegrityError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            continue
        if isinstance(body, dict):
            values.append(body)
    return tuple(values)


def _verify_provider_result_call_evidence(
    repository: PrequentialArtifactRepository,
    *,
    observation: Mapping[str, object],
    observation_sha256: str,
) -> None:
    fixture_id = str(observation.get("fixture_id", ""))
    fixture_record_id = str(observation.get("fixture_record_id", ""))
    provider_fixture_id = str(observation.get("provider_fixture_id", ""))
    attempt_value = observation.get("attempt")
    if (
        not fixture_id
        or not fixture_record_id
        or not provider_fixture_id
        or not isinstance(attempt_value, int)
        or isinstance(attempt_value, bool)
        or not 1 <= attempt_value <= 5
    ):
        raise ValueError("PREQUENTIAL_RESULT_OBSERVATION_CALL_IDENTITY_INVALID")
    observed_at = parse_utc(
        str(observation.get("observed_at")),
        field="result_observation_observed_at",
    )
    matching_completions = tuple(
        value
        for value in _content_addressed_json_values(
            repository,
            kind="provider-call-completions",
        )
        if value.get("schema_version")
        == "prequential-provider-call-completion-v1"
        and value.get("observation_sha256") == observation_sha256
        and value.get("fixture_id") == fixture_id
        and value.get("fixture_record_id") == fixture_record_id
        and value.get("attempt") == attempt_value
    )
    completions: list[tuple[dict[str, object], datetime]] = []
    for completion_value in matching_completions:
        try:
            completion_time = parse_utc(
                str(completion_value.get("completed_at")),
                field="result_completion_completed_at",
            )
        except (TypeError, ValueError):
            continue
        # A later append cannot retroactively make an already complete
        # provider call ambiguous.  Only the completion produced with the
        # immutable observation is causally admissible for that observation.
        if completion_time == observed_at:
            completions.append((completion_value, completion_time))
    if len(completions) != 1:
        if matching_completions and not completions:
            raise ValueError("PREQUENTIAL_RESULT_OBSERVATION_CALL_TIME_INVALID")
        raise ValueError("PREQUENTIAL_RESULT_OBSERVATION_COMPLETION_REQUIRED")
    completion, completed_at = completions[0]
    guard_sha256 = completion.get("guard_sha256")
    if not isinstance(guard_sha256, str) or len(guard_sha256) != 64:
        raise ValueError("PREQUENTIAL_RESULT_OBSERVATION_GUARD_REQUIRED")
    guard_key = (
        f"{repository.namespace}/provider-call-guards/"
        f"{guard_sha256}.json"
    )
    try:
        guard = json.loads(repository.read_verified(guard_key, guard_sha256))
    except (
        ArtifactIntegrityError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise ValueError("PREQUENTIAL_RESULT_OBSERVATION_GUARD_REQUIRED") from error
    if not isinstance(guard, dict):
        raise ValueError("PREQUENTIAL_RESULT_OBSERVATION_GUARD_REQUIRED")
    expected_guard_id = _provider_result_guard_id(
        fixture_id=fixture_id,
        fixture_record_id=fixture_record_id,
        provider_fixture_id=provider_fixture_id,
        attempt=attempt_value,
    )
    if (
        guard.get("schema_version") != "prequential-provider-call-guard-v1"
        or guard.get("guard_id") != expected_guard_id
        or guard.get("fixture_id") != fixture_id
        or guard.get("fixture_record_id") != fixture_record_id
        or guard.get("provider_fixture_id") != provider_fixture_id
        or guard.get("attempt") != attempt_value
        or guard.get("operation") != "VERIFY_FINAL_RESULT"
    ):
        raise ValueError("PREQUENTIAL_RESULT_OBSERVATION_GUARD_MISMATCH")
    guarded_at = parse_utc(
        str(guard.get("guarded_at")),
        field="result_guard_guarded_at",
    )
    if not guarded_at <= observed_at or completed_at != observed_at:
        raise ValueError("PREQUENTIAL_RESULT_OBSERVATION_CALL_TIME_INVALID")


def verify_result_observation_artifact(
    repository: PrequentialArtifactRepository,
    result: VerifiedFixtureResult,
) -> tuple[str, str]:
    """Bind a settlement target to its immutable provider observation."""

    if result.status not in FINAL_SCORE_STATUSES | FINAL_VOID_STATUSES:
        raise ValueError("PREQUENTIAL_RESULT_NOT_FINAL")
    key = (
        f"{repository.namespace}/result-observations/"
        f"{result.source_hash}.json"
    )
    try:
        body = json.loads(repository.read_verified(key, result.source_hash))
    except (
        ArtifactIntegrityError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise ValueError(
            "PREQUENTIAL_RESULT_OBSERVATION_BYTES_INVALID"
        ) from error
    if not isinstance(body, dict) or body.get("schema_version") != (
        "prequential-result-observation-v1"
    ):
        raise ValueError("PREQUENTIAL_RESULT_OBSERVATION_BODY_INVALID")
    record = body.get("record")
    provider = str(body.get("provider", "")).strip()
    provider_fixture_id = str(body.get("provider_fixture_id", ""))
    synthetic = body.get("origin") == "SYNTHETIC_MECHANICS_ONLY"
    if (
        not provider
        or body.get("fixture_id") != result.fixture_id
        or body.get("fixture_record_id") != result.fixture_record_id
        or body.get("availability") != DataAvailability.PRESENT.value
        or body.get("provider_calls") != (0 if synthetic else 1)
        or (
            synthetic
            and (
                not result.fixture_id.startswith("synthetic:")
                or not result.fixture_record_id.startswith("synthetic-record-")
            )
        )
        or not isinstance(record, Mapping)
        or parse_utc(
            str(body.get("observed_at")),
            field="result_observation_observed_at",
        )
        != result.verified_at
    ):
        raise ValueError("PREQUENTIAL_RESULT_OBSERVATION_PROJECTION_MISMATCH")
    if not synthetic:
        _verify_provider_result_call_evidence(
            repository,
            observation=body,
            observation_sha256=result.source_hash,
        )
    fixture_value = record.get("fixture")
    goals = record.get("goals")
    if not isinstance(fixture_value, Mapping) or str(
        fixture_value.get("id", "")
    ) != provider_fixture_id:
        raise ValueError("PREQUENTIAL_RESULT_OBSERVATION_PROJECTION_MISMATCH")
    status_value = fixture_value.get("status")
    short = (
        str(status_value.get("short", "")).strip().upper()
        if isinstance(status_value, Mapping)
        else ""
    )
    if result.status in FINAL_SCORE_STATUSES:
        if (
            short not in {"FT", "AET", "PEN"}
            or not isinstance(goals, Mapping)
            or goals.get("home") != result.home_goals
            or goals.get("away") != result.away_goals
        ):
            raise ValueError(
                "PREQUENTIAL_RESULT_OBSERVATION_PROJECTION_MISMATCH"
            )
        return provider, provider_fixture_id
    expected_status = (
        FixtureResultStatus.ABANDONED
        if short == "ABD"
        else FixtureResultStatus.CANCELLED
        if short in {"CANC", "AWD", "WO"}
        else None
    )
    if expected_status is None or result.status is not expected_status:
        raise ValueError("PREQUENTIAL_RESULT_OBSERVATION_PROJECTION_MISMATCH")
    return provider, provider_fixture_id


class SettlementRegistry:
    def __init__(self) -> None:
        self._settlements_by_id: dict[str, FixtureSettlementRecord] = {}
        self._versions_by_fixture_record: dict[
            str,
            list[FixtureSettlementRecord],
        ] = {}
        self._scores: dict[tuple[str, str], PredictionScore] = {}

    @property
    def settlements(self) -> tuple[FixtureSettlementRecord, ...]:
        return tuple(self._settlements_by_id.values())

    @property
    def scores(self) -> tuple[PredictionScore, ...]:
        return tuple(self._scores.values())

    def latest(self, fixture_record_id: str) -> FixtureSettlementRecord | None:
        versions = self._versions_by_fixture_record.get(fixture_record_id, [])
        return versions[-1] if versions else None

    def restore(
        self,
        settlement: FixtureSettlementRecord,
        scores: tuple[PredictionScore, ...] = (),
    ) -> None:
        existing = self._settlements_by_id.get(settlement.settlement_id)
        if existing is not None:
            if existing != settlement:
                raise ValueError("PREQUENTIAL_SETTLEMENT_RESTORE_CONFLICT")
            return
        latest = self.latest(settlement.result.fixture_record_id)
        if latest is None:
            if settlement.supersedes_id is not None:
                raise ValueError("PREQUENTIAL_SETTLEMENT_RESTORE_PARENT_MISSING")
            if (
                settlement.result.result_version != 1
                or settlement.result.status is FixtureResultStatus.CORRECTED
            ):
                raise ValueError("PREQUENTIAL_SETTLEMENT_RESTORE_CHAIN_INVALID")
        elif (
            settlement.supersedes_id != latest.settlement_id
            or settlement.result.result_version
            != latest.result.result_version + 1
            or settlement.result.status is not FixtureResultStatus.CORRECTED
            or settlement.result.source_hash == latest.result.source_hash
            or settlement.result.verified_at <= latest.result.verified_at
            or settlement.settled_at < latest.settled_at
        ):
            raise ValueError("PREQUENTIAL_SETTLEMENT_RESTORE_CHAIN_INVALID")
        self._settlements_by_id[settlement.settlement_id] = settlement
        self._versions_by_fixture_record.setdefault(
            settlement.result.fixture_record_id,
            [],
        ).append(settlement)
        for score in scores:
            if score.settlement_id != settlement.settlement_id:
                raise ValueError("PREQUENTIAL_SCORE_RESTORE_SETTLEMENT_MISMATCH")
            self._scores[(score.prediction_id, score.settlement_id)] = score

    def settle(
        self,
        result: VerifiedFixtureResult,
        *,
        predictions: tuple[FrozenPredictionRecord, ...],
        settled_at: datetime,
    ) -> tuple[FixtureSettlementRecord, tuple[PredictionScore, ...], bool]:
        if result.status in {
            FixtureResultStatus.SCHEDULED,
            FixtureResultStatus.IN_PLAY,
            FixtureResultStatus.POSTPONED,
        }:
            raise ValueError("PREQUENTIAL_RESULT_NOT_FINAL")
        if result.status not in FINAL_SCORE_STATUSES | FINAL_VOID_STATUSES:
            raise ValueError("PREQUENTIAL_RESULT_STATUS_UNSUPPORTED")
        matching = tuple(
            prediction
            for prediction in predictions
            if prediction.fixture_id == result.fixture_id
            and prediction.fixture_record_id == result.fixture_record_id
            and prediction.status is PredictionStatus.FROZEN
        )
        if not matching:
            raise ValueError("PREQUENTIAL_SETTLEMENT_WITHOUT_FROZEN_PREDICTION")
        if any(
            prediction.competition != result.competition
            or prediction.kickoff_at != result.kickoff_at
            for prediction in matching
        ):
            raise ValueError("PREQUENTIAL_SETTLEMENT_FIXTURE_PROJECTION_MISMATCH")
        latest = self.latest(result.fixture_record_id)
        if latest is not None and latest.result.result_hash == result.result_hash:
            existing_scores = tuple(
                score
                for (prediction_id, settlement_id), score in self._scores.items()
                if settlement_id == latest.settlement_id
                and any(
                    prediction.prediction_id == prediction_id
                    for prediction in matching
                )
            )
            return latest, existing_scores, False
        if latest is None:
            if (
                result.result_version != 1
                or result.status is FixtureResultStatus.CORRECTED
            ):
                raise ValueError("PREQUENTIAL_RESULT_INITIAL_VERSION_INVALID")
        else:
            if result.result_version != latest.result.result_version + 1:
                raise ValueError("PREQUENTIAL_RESULT_CORRECTION_VERSION_INVALID")
            if result.status is not FixtureResultStatus.CORRECTED:
                raise ValueError("PREQUENTIAL_RESULT_CORRECTION_STATUS_REQUIRED")
            if (
                result.source_hash == latest.result.source_hash
                or result.verified_at <= latest.result.verified_at
            ):
                raise ValueError("PREQUENTIAL_RESULT_CORRECTION_TIME_INVALID")
            if settled_at < latest.settled_at:
                raise ValueError("PREQUENTIAL_SETTLEMENT_TIME_REGRESSION")
        effective = (
            PredictionStatus.SETTLED
            if result.status in FINAL_SCORE_STATUSES
            else PredictionStatus.VOID
        )
        supersedes_id = latest.settlement_id if latest else None
        settlement = FixtureSettlementRecord(
            settlement_id=settlement_record_id(
                result,
                supersedes_id=supersedes_id,
            ),
            result=result,
            settled_at=settled_at,
            effective_status=effective,
            supersedes_id=supersedes_id,
        )
        self._settlements_by_id[settlement.settlement_id] = settlement
        self._versions_by_fixture_record.setdefault(
            result.fixture_record_id,
            [],
        ).append(settlement)
        scores: list[PredictionScore] = []
        if effective is PredictionStatus.SETTLED:
            reference_losses: dict[tuple[str, str], float] = {}
            provisional: list[tuple[FrozenPredictionRecord, PredictionScore]] = []
            for prediction in matching:
                score = score_prediction(
                    prediction,
                    settlement,
                    scored_at=settled_at,
                    score_id=score_record_id(
                        prediction_id=prediction.prediction_id,
                        settlement_id=settlement.settlement_id,
                    ),
                )
                if score is None:
                    continue
                provisional.append((prediction, score))
                if prediction.model_id.startswith("reference-"):
                    reference_losses[
                        (prediction.market.value, prediction.cutoff_name.value)
                    ] = score.log_loss
            for prediction, score in provisional:
                reference_loss = reference_losses.get(
                    (prediction.market.value, prediction.cutoff_name.value)
                )
                if (
                    reference_loss is not None
                    and not prediction.model_id.startswith("reference-")
                ):
                    score = PredictionScore(
                        score_id=score.score_id,
                        prediction_id=score.prediction_id,
                        settlement_id=score.settlement_id,
                        fixture_id=score.fixture_id,
                        competition=score.competition,
                        market=score.market,
                        cutoff_name=score.cutoff_name,
                        model_id=score.model_id,
                        model_version=score.model_version,
                        scored_at=score.scored_at,
                        outcome=score.outcome,
                        log_loss=score.log_loss,
                        brier_score=score.brier_score,
                        accurate=score.accurate,
                        reference_log_loss_delta=score.log_loss - reference_loss,
                    )
                self._scores[(score.prediction_id, settlement.settlement_id)] = score
                scores.append(score)
        return settlement, tuple(scores), True


__all__ = [
    "FINAL_SCORE_STATUSES",
    "FINAL_VOID_STATUSES",
    "SettlementRegistry",
    "verify_result_observation_artifact",
]
