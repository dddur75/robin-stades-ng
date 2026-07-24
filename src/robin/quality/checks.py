"""Moteur minimal de contrôles qualité structurés."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

import pandas as pd
from pydantic import BaseModel, ConfigDict

from robin.quality.zero_audit import ZeroAuditRow


class CheckStatus(StrEnum):
    PASSED = "PASSED"
    WARNING = "WARNING"
    FAILED = "FAILED"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class QualityCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    check_name: str
    run_id: str
    status: CheckStatus
    severity: Severity
    scope: str
    observed_value: str
    expected_rule: str
    affected_rows: int
    started_at: datetime
    finished_at: datetime
    evidence_location: str | None = None


def _result(
    *,
    name: str,
    run_id: str,
    status: CheckStatus,
    severity: Severity,
    observed: str,
    expected: str,
    affected: int,
    started: datetime,
    evidence: str | None = None,
) -> QualityCheckResult:
    return QualityCheckResult(
        check_name=name,
        run_id=run_id,
        status=status,
        severity=severity,
        scope="data/matches.parquet",
        observed_value=observed,
        expected_rule=expected,
        affected_rows=affected,
        started_at=started,
        finished_at=datetime.now(UTC),
        evidence_location=evidence,
    )


def run_match_checks(
    frame: pd.DataFrame,
    zero_audit: list[ZeroAuditRow],
    *,
    as_of_time: datetime | None = None,
    evidence_location: Path | None = None,
) -> list[QualityCheckResult]:
    run_id = str(uuid4())
    started = datetime.now(UTC)
    as_of = as_of_time or started
    evidence = str(evidence_location) if evidence_location else None
    duplicates = int(frame["match_id"].duplicated().sum())
    dates = pd.to_datetime(frame["date"], utc=True)
    future_rows = int((dates > pd.Timestamp(as_of)).sum())
    missing_scores = int(frame[["fthg", "ftag"]].isna().any(axis=1).sum())
    required_columns = {
        "match_id",
        "league",
        "season",
        "date",
        "home",
        "away",
        "fthg",
        "ftag",
    }
    absent_columns = sorted(required_columns - set(frame.columns))
    required_nulls = (
        int(frame[list(required_columns)].isna().any(axis=1).sum())
        if not absent_columns
        else len(frame)
    )
    business_duplicates = (
        int(
            frame.duplicated(
                subset=["league", "season", "date", "home", "away"],
            ).sum()
        )
        if {"home", "away"}.issubset(frame.columns)
        else len(frame)
    )
    impossible_scores = int(
        (
            (pd.to_numeric(frame["fthg"], errors="coerce") < 0)
            | (pd.to_numeric(frame["ftag"], errors="coerce") < 0)
            | (pd.to_numeric(frame["fthg"], errors="coerce") > 20)
            | (pd.to_numeric(frame["ftag"], errors="coerce") > 20)
        ).sum()
    )
    max_date = dates.max()
    freshness_days = int((pd.Timestamp(as_of) - max_date).days)
    suspect_segments = [
        row for row in zero_audit if row.quality_status.value == "SUSPECT_ZERO"
    ]
    suspect_values = sum(row.zeros for row in suspect_segments)

    return [
        _result(
            name="required_schema_completeness",
            run_id=run_id,
            status=(
                CheckStatus.PASSED
                if not absent_columns and required_nulls == 0
                else CheckStatus.FAILED
            ),
            severity=Severity.CRITICAL,
            observed=(
                f"colonnes absentes={absent_columns}, lignes incomplètes={required_nulls}"
            ),
            expected="schéma requis présent et non nul",
            affected=required_nulls,
            started=started,
            evidence=evidence,
        ),
        _result(
            name="match_id_uniqueness",
            run_id=run_id,
            status=CheckStatus.PASSED if duplicates == 0 else CheckStatus.FAILED,
            severity=Severity.CRITICAL,
            observed=f"{duplicates} identifiants dupliqués",
            expected="match_id unique",
            affected=duplicates,
            started=started,
            evidence=evidence,
        ),
        _result(
            name="fixture_business_uniqueness",
            run_id=run_id,
            status=(
                CheckStatus.PASSED
                if business_duplicates == 0
                else CheckStatus.FAILED
            ),
            severity=Severity.CRITICAL,
            observed=f"{business_duplicates} fixtures métier dupliqués",
            expected="(ligue, saison, date, home, away) unique",
            affected=business_duplicates,
            started=started,
            evidence=evidence,
        ),
        _result(
            name="final_score_completeness",
            run_id=run_id,
            status=CheckStatus.PASSED if missing_scores == 0 else CheckStatus.FAILED,
            severity=Severity.CRITICAL,
            observed=f"{missing_scores} scores incomplets",
            expected="scores finaux présents pour les matchs historiques",
            affected=missing_scores,
            started=started,
            evidence=evidence,
        ),
        _result(
            name="score_domain_validity",
            run_id=run_id,
            status=(
                CheckStatus.PASSED
                if impossible_scores == 0
                else CheckStatus.FAILED
            ),
            severity=Severity.HIGH,
            observed=f"{impossible_scores} scores hors domaine [0, 20]",
            expected="buts entiers plausibles",
            affected=impossible_scores,
            started=started,
            evidence=evidence,
        ),
        _result(
            name="future_data",
            run_id=run_id,
            status=CheckStatus.PASSED if future_rows == 0 else CheckStatus.FAILED,
            severity=Severity.CRITICAL,
            observed=f"{future_rows} lignes futures",
            expected="date <= instant d'audit",
            affected=future_rows,
            started=started,
            evidence=evidence,
        ),
        _result(
            name="dataset_freshness",
            run_id=run_id,
            status=(
                CheckStatus.PASSED
                if freshness_days <= 90
                else CheckStatus.WARNING
            ),
            severity=Severity.HIGH,
            observed=f"dernière date il y a {freshness_days} jours",
            expected="fraîcheur <= 90 jours, seuil intersaison",
            affected=0 if freshness_days <= 90 else len(frame),
            started=started,
            evidence=evidence,
        ),
        _result(
            name="suspect_zero_segments",
            run_id=run_id,
            status=(
                CheckStatus.WARNING if suspect_segments else CheckStatus.PASSED
            ),
            severity=Severity.HIGH,
            observed=(
                f"{len(suspect_segments)} segments, {suspect_values} valeurs suspectes"
            ),
            expected="zéros observés distinguables des données absentes",
            affected=suspect_values,
            started=started,
            evidence=evidence,
        ),
        _result(
            name="internal_identity_coverage",
            run_id=run_id,
            status=(
                CheckStatus.PASSED
                if "fixture_id" in frame.columns
                else CheckStatus.WARNING
            ),
            severity=Severity.HIGH,
            observed=(
                "fixture_id présent"
                if "fixture_id" in frame.columns
                else "dataset legacy non migré vers les UUID internes"
            ),
            expected="toute ligne normalisée référence un fixture interne",
            affected=0 if "fixture_id" in frame.columns else len(frame),
            started=started,
            evidence=evidence,
        ),
        _result(
            name="source_conflict_observability",
            run_id=run_id,
            status=(
                CheckStatus.PASSED
                if "provider" in frame.columns
                else CheckStatus.WARNING
            ),
            severity=Severity.MEDIUM,
            observed=(
                "provenance présente"
                if "provider" in frame.columns
                else "provenance source absente du dataset legacy"
            ),
            expected="provider et observation brute traçables",
            affected=0 if "provider" in frame.columns else len(frame),
            started=started,
            evidence=evidence,
        ),
    ]
