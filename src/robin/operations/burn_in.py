"""Calculs de burn-in, SLO et alertes opérationnelles sans conclusion sportive."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5


class HealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    AT_RISK = "AT_RISK"
    CRITICAL = "CRITICAL"
    INSUFFICIENT_OBSERVATION = "INSUFFICIENT_OBSERVATION"


class AlertSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class SloThresholds:
    workflow_success_rate: float = 0.95
    eligible_window_coverage: float = 0.90
    provenance_completeness: float = 1.0
    quota_reserve_pct: float = 0.20
    maximum_silent_loss: int = 0
    maximum_unresolved_duplicates: int = 0
    maximum_temporal_leaks: int = 0
    maximum_secret_exposures: int = 0
    maximum_demo_as_live: int = 0


def rate(numerator: int, denominator: int) -> float:
    return 0.0 if denominator <= 0 else numerator / denominator


def compute_daily_metrics(
    *,
    metric_date: date,
    runs: Sequence[Mapping[str, object]],
    fixtures: int,
    snapshots: int,
    windows: Sequence[Mapping[str, object]],
    predictions: int,
    decisions: int,
    settlements: int,
    raw_observations: int,
    provenance_complete: int,
    duplicates: int,
    silent_losses: int,
    quota_used: int,
    quota_remaining: int,
    quota_limit: int,
    thresholds: SloThresholds | None = None,
) -> dict[str, object]:
    rules = thresholds or SloThresholds()
    success_statuses = {
        "PASSED",
        "PRESENT",
        "ABSENT",
        "WORKFLOW_SUCCESS_LIVE_DATA",
        "WORKFLOW_SUCCESS_NO_DATA",
        "DURABLE_WRITE_CONFIRMED",
    }
    runs_succeeded = sum(run.get("status") in success_statuses for run in runs)
    eligible = [
        window
        for window in windows
        if window.get("status")
        not in {"PENDING", "CANCELLED_FIXTURE", "NO_MARKET_AVAILABLE"}
    ]
    covered = sum(
        window.get("status") in {"COLLECTED", "COLLECTED_LATE"}
        for window in eligible
    )
    workflow_rate = rate(runs_succeeded, len(runs))
    coverage = rate(covered, len(eligible))
    provenance_rate = rate(provenance_complete, raw_observations)
    quota_reserve = rate(quota_remaining, quota_limit)
    breaches: list[str] = []
    if runs and workflow_rate < rules.workflow_success_rate:
        breaches.append("WORKFLOW_SUCCESS_RATE")
    if eligible and coverage < rules.eligible_window_coverage:
        breaches.append("ELIGIBLE_WINDOW_COVERAGE")
    if raw_observations and provenance_rate < rules.provenance_completeness:
        breaches.append("PROVENANCE_COMPLETENESS")
    if quota_reserve < rules.quota_reserve_pct:
        breaches.append("QUOTA_RESERVE")
    if silent_losses > rules.maximum_silent_loss:
        breaches.append("SILENT_DATA_LOSS")
    if duplicates > rules.maximum_unresolved_duplicates:
        breaches.append("UNRESOLVED_DUPLICATES")
    if silent_losses:
        health = HealthStatus.CRITICAL
    elif len(runs) < 3 or not eligible:
        health = HealthStatus.INSUFFICIENT_OBSERVATION
    elif len(breaches) >= 2:
        health = HealthStatus.AT_RISK
    elif breaches:
        health = HealthStatus.DEGRADED
    else:
        health = HealthStatus.HEALTHY
    return {
        "date": metric_date.isoformat(),
        "health_status": health.value,
        "runs_expected": len(runs),
        "runs_succeeded": runs_succeeded,
        "runs_failed": len(runs) - runs_succeeded,
        "workflow_success_rate": workflow_rate,
        "fixtures": fixtures,
        "snapshots": snapshots,
        "windows_eligible": len(eligible),
        "windows_collected": covered,
        "coverage_rate": coverage,
        "provenance_completeness": provenance_rate,
        "duplicates": duplicates,
        "silent_losses": silent_losses,
        "quota_used": quota_used,
        "quota_remaining": quota_remaining,
        "quota_reserve_rate": quota_reserve,
        "predictions": predictions,
        "decisions": decisions,
        "settlements": settlements,
        "slo_breaches": breaches,
        "statistical_status": "ÉCHANTILLON INSUFFISANT — AUCUNE CONCLUSION STATISTIQUE",
        "production_status": "PRODUCTION_LOCKED",
    }


class IncidentJournal:
    """Journal append-only : un incident ouvert par code, sans spam."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read_all(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        return [
            value
            for line in self.path.read_text("utf-8").splitlines()
            if line.strip()
            for value in [json.loads(line)]
            if isinstance(value, dict)
        ]

    def open(
        self,
        *,
        code: str,
        severity: AlertSeverity,
        cause: str,
        impact: str,
        source_run_id: str | None = None,
    ) -> bool:
        existing = self.read_all()
        latest = [item for item in existing if item.get("incident_code") == code]
        if latest and latest[-1].get("status") == "OPEN":
            return False
        now = datetime.now(UTC)
        incident: dict[str, object] = {
            "incident_id": str(uuid5(NAMESPACE_URL, f"robin:incident:{code}:{now.date()}")),
            "incident_code": code,
            "severity": severity.value,
            "status": "OPEN",
            "started_at": now.isoformat(),
            "ended_at": None,
            "cause": cause,
            "impact": impact,
            "affected_data": [],
            "correction": None,
            "source_run_id": source_run_id,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(incident, ensure_ascii=False, sort_keys=True))
            stream.write("\n")
        return True

    def resolve(self, *, code: str, correction: str) -> bool:
        existing = self.read_all()
        latest = [item for item in existing if item.get("incident_code") == code]
        if not latest or latest[-1].get("status") != "OPEN":
            return False
        resolution = {
            **latest[-1],
            "status": "RESOLVED",
            "ended_at": datetime.now(UTC).isoformat(),
            "correction": correction,
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(resolution, ensure_ascii=False, sort_keys=True))
            stream.write("\n")
        return True


def render_daily_report(metrics: Mapping[str, object]) -> str:
    breaches = metrics.get("slo_breaches", [])
    breach_text = ", ".join(str(item) for item in breaches) if isinstance(
        breaches, list
    ) else str(breaches)
    return "\n".join(
        [
            f"# Rapport shadow quotidien — {metrics['date']}",
            "",
            f"Statut : `{metrics['health_status']}`",
            "Production : `PRODUCTION_LOCKED`",
            "",
            f"- runs réussis : {metrics['runs_succeeded']}/{metrics['runs_expected']} ;",
            f"- fixtures : {metrics['fixtures']} ;",
            f"- snapshots : {metrics['snapshots']} ;",
            f"- couverture fenêtres : {_as_float(metrics['coverage_rate']):.1%} ;",
            f"- quota restant : {metrics['quota_remaining']} ;",
            f"- prédictions : {metrics['predictions']} ;",
            f"- décisions : {metrics['decisions']} ;",
            f"- règlements : {metrics['settlements']} ;",
            f"- SLO en dégradation : {breach_text or 'aucun'} ;",
            "",
            str(metrics["statistical_status"]),
            "",
        ]
    )


def render_weekly_report(metrics: Sequence[Mapping[str, object]]) -> str:
    if not metrics:
        return "# Rapport shadow hebdomadaire\n\nAucune observation.\n"
    average_coverage = sum(
        _as_float(item.get("coverage_rate", 0))
        for item in metrics
    ) / len(metrics)
    failures = sum(_as_int(item.get("runs_failed", 0)) for item in metrics)
    return "\n".join(
        [
            "# Rapport shadow hebdomadaire",
            "",
            f"- jours observés : {len(metrics)} ;",
            f"- couverture moyenne : {average_coverage:.1%} ;",
            f"- runs échoués : {failures} ;",
            f"- quota consommé au dernier relevé : {metrics[-1].get('quota_used', 0)} ;",
            "",
            "Les performances shadow restent descriptives.",
            "",
            "ÉCHANTILLON INSUFFISANT — AUCUNE CONCLUSION STATISTIQUE",
            "",
        ]
    )


def _as_float(value: object) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float | str):
        return float(value)
    return 0.0


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float | str):
        return int(value)
    return 0
