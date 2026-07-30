"""Fail-closed readiness gates for historical-deep datasets."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Final


class GateName(StrEnum):
    TEAM = "TEAM"
    PLAYER = "PLAYER"
    PLAYER_FORM = "PLAYER_FORM"
    STARTER_BASELINE = "STARTER_BASELINE"
    LINEUP = "LINEUP"
    FORMATION = "FORMATION"
    ABSENCE = "ABSENCE"
    DISCIPLINE = "DISCIPLINE"
    FOOTEDNESS = "FOOTEDNESS"
    WEATHER = "WEATHER"


GATE_NAMES: Final = tuple(gate.value for gate in GateName)
GATE_STATUSES: Final = (
    "READY_STRICT",
    "READY_RECONSTRUCTED",
    "PARTIAL",
    "BLOCKED_BY_COVERAGE",
    "BLOCKED_BY_TEMPORALITY",
    "BLOCKED_BY_SOURCE",
)
FOOTEDNESS_API_FOOTBALL: Final = "NOT_AVAILABLE"


@dataclass(frozen=True, slots=True)
class GateThreshold:
    minimum_seasons: int
    minimum_coverage: float
    minimum_identity: float
    require_strict_temporality: bool = True
    reconstructed_allowed: bool = False

    def __post_init__(self) -> None:
        if self.minimum_seasons <= 0:
            raise ValueError("GATE_MINIMUM_SEASONS_MUST_BE_POSITIVE")
        if not 0.0 <= self.minimum_coverage <= 1.0:
            raise ValueError("GATE_COVERAGE_THRESHOLD_OUTSIDE_UNIT_INTERVAL")
        if not 0.0 <= self.minimum_identity <= 1.0:
            raise ValueError("GATE_IDENTITY_THRESHOLD_OUTSIDE_UNIT_INTERVAL")


DEFAULT_THRESHOLDS: Final[dict[str, GateThreshold]] = {
    GateName.TEAM.value: GateThreshold(3, 0.95, 0.99),
    GateName.PLAYER.value: GateThreshold(3, 0.90, 0.99),
    GateName.PLAYER_FORM.value: GateThreshold(3, 0.90, 0.99),
    GateName.STARTER_BASELINE.value: GateThreshold(3, 0.85, 0.99),
    GateName.LINEUP.value: GateThreshold(3, 0.85, 0.99, reconstructed_allowed=True),
    GateName.FORMATION.value: GateThreshold(
        3,
        0.80,
        0.99,
        reconstructed_allowed=True,
    ),
    GateName.ABSENCE.value: GateThreshold(
        3,
        0.80,
        0.99,
        require_strict_temporality=False,
        reconstructed_allowed=True,
    ),
    GateName.DISCIPLINE.value: GateThreshold(3, 0.80, 0.99),
    GateName.FOOTEDNESS.value: GateThreshold(3, 0.90, 0.99),
    GateName.WEATHER.value: GateThreshold(3, 0.80, 0.99),
}


@dataclass(frozen=True, slots=True)
class GateAssessment:
    gate: str
    status: str
    eligible_seasons: tuple[int, ...]
    observed_seasons: tuple[int, ...]
    coverage_rate: float | None
    identity_rate: float | None
    reasons: tuple[str, ...]
    source_status: str
    threshold: dict[str, object]
    status_counts: dict[str, int]

    @property
    def ready(self) -> bool:
        return self.status in {"READY_STRICT", "READY_RECONSTRUCTED"}

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _float(value: object, *, field: str) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError(f"GATE_{field.upper()}_INVALID")
    try:
        result = float(str(value))
    except ValueError as exc:
        raise ValueError(f"GATE_{field.upper()}_INVALID") from exc
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"GATE_{field.upper()}_OUTSIDE_UNIT_INTERVAL")
    return result


def _season(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("GATE_SEASON_REQUIRED") from exc


def _source_unavailable(evidence: Mapping[str, object]) -> bool:
    status = str(
        evidence.get("source_status", evidence.get("availability", "AVAILABLE"))
    ).upper()
    return evidence.get("source_available") is False or status in {
        "NOT_AVAILABLE",
        "UNAVAILABLE",
        "BLOCKED_PROVIDER",
        "BLOCKED_BY_PROVIDER",
        "MISSING_SOURCE",
    }


def assess_gate(
    gate: str | GateName,
    evidence: Sequence[Mapping[str, object]],
    threshold: GateThreshold | None = None,
) -> GateAssessment:
    gate_name = str(gate.value if isinstance(gate, GateName) else gate)
    if gate_name not in GATE_NAMES:
        raise ValueError(f"GATE_NAME_UNKNOWN:{gate_name}")
    selected_threshold = threshold or DEFAULT_THRESHOLDS[gate_name]
    threshold_dict = asdict(selected_threshold)
    if not evidence:
        reason = (
            f"FOOTEDNESS_API_FOOTBALL={FOOTEDNESS_API_FOOTBALL}"
            if gate_name == GateName.FOOTEDNESS.value
            else "NO_EVIDENCE"
        )
        status = (
            "BLOCKED_BY_SOURCE"
            if gate_name == GateName.FOOTEDNESS.value
            else "BLOCKED_BY_COVERAGE"
        )
        return GateAssessment(
            gate=gate_name,
            status=status,
            eligible_seasons=(),
            observed_seasons=(),
            coverage_rate=None,
            identity_rate=None,
            reasons=(reason,),
            source_status="NOT_AVAILABLE" if status == "BLOCKED_BY_SOURCE" else "UNKNOWN",
            threshold=threshold_dict,
            status_counts={status: 1},
        )

    unavailable = [item for item in evidence if _source_unavailable(item)]
    if unavailable:
        observed_seasons = tuple(
            sorted(
                {
                    _season(item.get("season"))
                    for item in evidence
                    if item.get("season") not in (None, "")
                }
            )
        )
        reason = (
            f"FOOTEDNESS_API_FOOTBALL={FOOTEDNESS_API_FOOTBALL}"
            if gate_name == GateName.FOOTEDNESS.value
            else "SOURCE_NOT_AVAILABLE"
        )
        return GateAssessment(
            gate=gate_name,
            status="BLOCKED_BY_SOURCE",
            eligible_seasons=(),
            observed_seasons=observed_seasons,
            coverage_rate=None,
            identity_rate=None,
            reasons=(reason,),
            source_status="NOT_AVAILABLE",
            threshold=threshold_dict,
            status_counts={"BLOCKED_BY_SOURCE": len(unavailable)},
        )
    observed_seasons = tuple(sorted({_season(item.get("season")) for item in evidence}))

    temporally_blocked = [
        item
        for item in evidence
        if (
            item.get("cutoff_proven") is False
            or str(item.get("temporal_status", "")).upper()
            in {"BLOCKED_BY_TEMPORALITY", "POST_MATCH_ONLY"}
        )
        and not (
            selected_threshold.reconstructed_allowed
            and item.get("reconstructed") is True
        )
    ]
    if selected_threshold.require_strict_temporality and temporally_blocked:
        return GateAssessment(
            gate=gate_name,
            status="BLOCKED_BY_TEMPORALITY",
            eligible_seasons=(),
            observed_seasons=observed_seasons,
            coverage_rate=None,
            identity_rate=None,
            reasons=tuple(
                f"CUTOFF_UNPROVEN:{season}"
                for season in sorted(
                    {_season(item.get("season")) for item in temporally_blocked}
                )
            ),
            source_status="AVAILABLE",
            threshold=threshold_dict,
            status_counts={"BLOCKED_BY_TEMPORALITY": len(temporally_blocked)},
        )

    per_season: dict[int, list[Mapping[str, object]]] = {}
    for item in evidence:
        per_season.setdefault(_season(item.get("season")), []).append(item)
    eligible: list[int] = []
    season_status: dict[int, str] = {}
    reconstructed_eligible = False
    coverage_values: list[float] = []
    identity_values: list[float] = []
    reasons: list[str] = []
    for season, rows in sorted(per_season.items()):
        coverage_candidates = [
            value
            for item in rows
            if (
                value := _float(
                    item.get("coverage_rate", item.get("coverage")),
                    field="coverage_rate",
                )
            )
            is not None
        ]
        identity_candidates = [
            value
            for item in rows
            if (value := _float(item.get("identity_rate"), field="identity_rate"))
            is not None
        ]
        coverage = min(coverage_candidates) if coverage_candidates else None
        identity = min(identity_candidates) if identity_candidates else None
        if coverage is not None:
            coverage_values.append(coverage)
        if identity is not None:
            identity_values.append(identity)
        if coverage is None or coverage < selected_threshold.minimum_coverage:
            season_status[season] = "BLOCKED_BY_COVERAGE"
            reasons.append(f"COVERAGE_BELOW_THRESHOLD:{season}")
            continue
        if identity is None or identity < selected_threshold.minimum_identity:
            season_status[season] = "BLOCKED_BY_COVERAGE"
            reasons.append(f"IDENTITY_BELOW_THRESHOLD:{season}")
            continue
        reconstructed = any(item.get("reconstructed") is True for item in rows)
        if reconstructed and not selected_threshold.reconstructed_allowed:
            season_status[season] = "BLOCKED_BY_TEMPORALITY"
            reasons.append(f"RECONSTRUCTED_NOT_ALLOWED:{season}")
            continue
        if any(
            item.get("cutoff_proven") is False
            and item.get("reconstructed") is not True
            for item in rows
        ):
            season_status[season] = "BLOCKED_BY_TEMPORALITY"
            reasons.append(f"CUTOFF_UNPROVEN:{season}")
            continue
        eligible.append(season)
        reconstructed_eligible = reconstructed_eligible or reconstructed
        season_status[season] = (
            "READY_RECONSTRUCTED" if reconstructed else "READY_STRICT"
        )

    counts = Counter(season_status.values())
    if len(eligible) >= selected_threshold.minimum_seasons:
        status = (
            "READY_RECONSTRUCTED" if reconstructed_eligible else "READY_STRICT"
        )
        final_reasons: tuple[str, ...] = ()
    elif eligible or any(value is not None and value > 0 for value in coverage_values):
        status = "PARTIAL"
        final_reasons = tuple(
            reasons
            + [
                f"ELIGIBLE_SEASONS:{len(eligible)}",
                f"MINIMUM_SEASONS:{selected_threshold.minimum_seasons}",
            ]
        )
    elif counts["BLOCKED_BY_TEMPORALITY"]:
        status = "BLOCKED_BY_TEMPORALITY"
        final_reasons = tuple(reasons)
    else:
        status = "BLOCKED_BY_COVERAGE"
        final_reasons = tuple(reasons or ["NO_ELIGIBLE_SEASON"])
    return GateAssessment(
        gate=gate_name,
        status=status,
        eligible_seasons=tuple(eligible),
        observed_seasons=observed_seasons,
        coverage_rate=min(coverage_values) if coverage_values else None,
        identity_rate=min(identity_values) if identity_values else None,
        reasons=final_reasons,
        source_status="AVAILABLE",
        threshold=threshold_dict,
        status_counts=dict(sorted(counts.items())),
    )


def evaluate_gate_registry(
    evidence_by_gate: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    thresholds: Mapping[str, GateThreshold] | None = None,
) -> dict[str, GateAssessment]:
    selected = thresholds or DEFAULT_THRESHOLDS
    unknown = set(evidence_by_gate) - set(GATE_NAMES)
    if unknown:
        raise ValueError(f"GATE_NAME_UNKNOWN:{','.join(sorted(unknown))}")
    return {
        gate: assess_gate(
            gate,
            evidence_by_gate.get(gate, ()),
            selected.get(gate, DEFAULT_THRESHOLDS[gate]),
        )
        for gate in GATE_NAMES
    }


def gate_summary(
    assessments: Mapping[str, GateAssessment],
) -> dict[str, object]:
    missing = set(GATE_NAMES) - set(assessments)
    if missing:
        raise ValueError(f"GATE_ASSESSMENT_MISSING:{','.join(sorted(missing))}")
    counts = Counter(assessment.status for assessment in assessments.values())
    return {
        "statuses": dict(sorted(counts.items())),
        "ready_strict": counts["READY_STRICT"],
        "ready_reconstructed": counts["READY_RECONSTRUCTED"],
        "all_ready": all(assessment.ready for assessment in assessments.values()),
        "promotion": "NO_PROMOTION",
        "production_status": "PRODUCTION_LOCKED",
    }
