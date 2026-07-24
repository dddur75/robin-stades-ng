from datetime import UTC, datetime

import pandas as pd

from robin.domain.enums import QualityStatus
from robin.quality.checks import CheckStatus, run_match_checks
from robin.quality.report import write_health_dashboard
from robin.quality.zero_audit import (
    audit_suspect_zeros,
    build_value_quality,
    values_eligible_for_model,
)


def sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "match_id": [f"m{i}" for i in range(30)],
            "league": ["F2"] * 30,
            "season": ["2015-16"] * 30,
            "date": pd.date_range("2015-08-01", periods=30, tz="UTC"),
            "home": [f"H{i}" for i in range(30)],
            "away": [f"A{i}" for i in range(30)],
            "fthg": [1] * 30,
            "ftag": [0] * 30,
            "hthg": [0] * 30,
            "htag": [0] * 30,
            "hy": [0] * 30,
            "ay": [0] * 30,
            "hr": [0] * 30,
            "ar": [0] * 30,
            "hc": [0] * 30,
            "ac": [0] * 30,
        }
    )


def test_suspect_zero_reste_auditable_mais_est_exclu_du_modele() -> None:
    frame = sample_frame()
    audit = audit_suspect_zeros(frame, provider="fixture")
    statuses = build_value_quality(frame, audit)
    eligible = values_eligible_for_model(frame["hy"], statuses["hy"])

    assert statuses["hy"].eq(QualityStatus.SUSPECT_ZERO.value).all()
    assert eligible.isna().all()
    assert frame["hy"].eq(0).all()


def test_controles_et_dashboard_sante_sont_reproductibles(tmp_path) -> None:
    frame = sample_frame()
    audit = audit_suspect_zeros(frame, provider="fixture")
    checks = run_match_checks(
        frame,
        audit,
        as_of_time=datetime(2026, 7, 24, tzinfo=UTC),
    )
    dashboard = tmp_path / "health.html"
    write_health_dashboard(checks, audit, dashboard)

    assert all(check.status != CheckStatus.FAILED for check in checks)
    assert any(check.status == CheckStatus.WARNING for check in checks)
    content = dashboard.read_text("utf-8")
    assert "Santé Data" in content
    assert "SUSPECT" not in content or "Zéros suspects" in content


def test_doublon_et_donnee_future_echouent_clairement() -> None:
    frame = sample_frame()
    frame.loc[1, "match_id"] = "m0"
    frame.loc[2, "date"] = pd.Timestamp("2030-01-01", tz="UTC")
    checks = run_match_checks(
        frame,
        audit_suspect_zeros(frame, provider="fixture"),
        as_of_time=datetime(2026, 7, 24, tzinfo=UTC),
    )
    failed = {check.check_name for check in checks if check.status == CheckStatus.FAILED}
    assert failed == {"match_id_uniqueness", "future_data"}


def test_reference_orpheline_est_bloquante_avec_un_registre() -> None:
    frame = sample_frame()
    frame["fixture_id"] = [f"fixture-{index}" for index in range(len(frame))]
    known = set(frame["fixture_id"])
    known.remove("fixture-4")

    checks = run_match_checks(
        frame,
        audit_suspect_zeros(frame, provider="fixture"),
        known_fixture_ids=known,
    )
    by_name = {check.check_name: check for check in checks}

    assert by_name["orphan_fixture_references"].status == CheckStatus.FAILED
    assert by_name["orphan_fixture_references"].affected_rows == 1
    assert "score_distribution_anomaly" in by_name
    assert "dataset_volume" in by_name
