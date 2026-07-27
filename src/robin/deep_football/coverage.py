"""Coverage matrix and data-gate evaluation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from robin.deep_football.contracts import DataGateStatus


@dataclass(frozen=True, slots=True)
class CoverageEvidence:
    competition: str
    season: int
    family: str
    fixtures_expected: int
    fixtures_covered: int
    identity_rate: float | None
    minutes_coherent: bool | None
    cutoff_proven: bool
    source: str
    quality_status: str

    @property
    def coverage_rate(self) -> float:
        if self.fixtures_expected <= 0:
            return 0.0
        return min(self.fixtures_covered / self.fixtures_expected, 1.0)

    def as_dict(self) -> dict[str, object]:
        return {**asdict(self), "coverage_rate": self.coverage_rate}


@dataclass(frozen=True, slots=True)
class GateThreshold:
    minimum_seasons: int
    minimum_coverage: float
    minimum_identity: float
    require_minutes_coherent: bool = False
    require_cutoff: bool = True


@dataclass(frozen=True, slots=True)
class GateAssessment:
    gate: str
    status: DataGateStatus
    eligible_seasons: tuple[int, ...]
    reasons: tuple[str, ...]
    minimums: dict[str, object]

    @property
    def ready(self) -> bool:
        return self.status == DataGateStatus.READY

    def as_dict(self) -> dict[str, object]:
        return {
            "gate": self.gate,
            "status": self.status.value,
            "eligible_seasons": list(self.eligible_seasons),
            "reasons": list(self.reasons),
            "minimums": self.minimums,
        }


PLAYER_THRESHOLD = GateThreshold(3, 0.90, 0.99, require_minutes_coherent=True)
LINEUP_THRESHOLD = GateThreshold(3, 0.85, 0.99)
ABSENCE_THRESHOLD = GateThreshold(3, 0.80, 0.99)
FORMATION_THRESHOLD = GateThreshold(3, 0.80, 0.99)
FOOTEDNESS_THRESHOLD = GateThreshold(3, 0.90, 0.99)
PLAYER_FORM_THRESHOLD = GateThreshold(3, 0.90, 0.99, require_minutes_coherent=True)
STARTER_BASELINE_THRESHOLD = GateThreshold(3, 0.85, 0.99)


def assess_gate(
    gate: str,
    evidence: Sequence[CoverageEvidence],
    threshold: GateThreshold,
) -> GateAssessment:
    """Assess a gate without averaging away a failed season."""

    if not evidence:
        return GateAssessment(
            gate,
            DataGateStatus.BLOCKED_BY_COVERAGE,
            (),
            ("NO_OBSERVATIONS",),
            asdict(threshold),
        )
    cutoff_failures = [item.season for item in evidence if not item.cutoff_proven]
    if threshold.require_cutoff and cutoff_failures:
        return GateAssessment(
            gate,
            DataGateStatus.BLOCKED_BY_TEMPORALITY,
            (),
            tuple(f"CUTOFF_UNPROVEN:{season}" for season in sorted(set(cutoff_failures))),
            asdict(threshold),
        )
    identity_failures = [
        item.season
        for item in evidence
        if item.identity_rate is None
        or item.identity_rate < threshold.minimum_identity
    ]
    if identity_failures:
        return GateAssessment(
            gate,
            DataGateStatus.BLOCKED_BY_IDENTITY,
            (),
            tuple(
                f"IDENTITY_BELOW_THRESHOLD:{season}"
                for season in sorted(set(identity_failures))
            ),
            asdict(threshold),
        )
    eligible = tuple(
        sorted(
            {
                item.season
                for item in evidence
                if item.coverage_rate >= threshold.minimum_coverage
                and (
                    not threshold.require_minutes_coherent
                    or item.minutes_coherent is True
                )
                and item.quality_status == "PASSED"
            }
        )
    )
    if len(eligible) < threshold.minimum_seasons:
        partial = any(item.coverage_rate > 0.0 for item in evidence)
        return GateAssessment(
            gate,
            (
                DataGateStatus.PARTIAL
                if partial
                else DataGateStatus.BLOCKED_BY_COVERAGE
            ),
            eligible,
            (
                f"ELIGIBLE_SEASONS:{len(eligible)}",
                f"MINIMUM_SEASONS:{threshold.minimum_seasons}",
            ),
            asdict(threshold),
        )
    return GateAssessment(
        gate,
        DataGateStatus.READY,
        eligible,
        (),
        asdict(threshold),
    )


def evaluate_gate_registry(
    evidence_by_gate: Mapping[str, Sequence[CoverageEvidence]],
) -> dict[str, GateAssessment]:
    thresholds = {
        "PLAYER_GATE": PLAYER_THRESHOLD,
        "LINEUP_GATE": LINEUP_THRESHOLD,
        "ABSENCE_GATE": ABSENCE_THRESHOLD,
        "FORMATION_GATE": FORMATION_THRESHOLD,
        "FOOTEDNESS_GATE": FOOTEDNESS_THRESHOLD,
        "PLAYER_FORM_GATE": PLAYER_FORM_THRESHOLD,
        "STARTER_BASELINE_GATE": STARTER_BASELINE_THRESHOLD,
    }
    return {
        gate: assess_gate(gate, evidence_by_gate.get(gate, ()), threshold)
        for gate, threshold in thresholds.items()
    }
