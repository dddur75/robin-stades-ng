from __future__ import annotations

import json
from pathlib import Path

import pytest

from robin.storage import database as database_module
from robin.storage.database import (
    DatabaseConfigurationError,
    alembic_database_url,
    build_engine,
    database_url_object,
    normalize_database_url,
)
from scripts.shadow_diagnostics import diagnose


def test_url_neon_est_normalisee_vers_psycopg3() -> None:
    normalized = normalize_database_url(
        "postgresql://robin:secret@ep-example.eu-central-1.aws.neon.tech/robin"
    )
    assert normalized.startswith("postgresql+psycopg://")
    assert normalized.endswith("/robin")


def test_url_psycopg3_explicite_est_conservee() -> None:
    value = "postgresql+psycopg://robin:secret@localhost:5432/robin"
    assert normalize_database_url(value) == value


def test_url_sqlite_reste_compatible() -> None:
    value = "sqlite+pysqlite:///:memory:"
    assert normalize_database_url(value) == value
    with build_engine(value).connect() as connection:
        assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1


def test_postgresql_pool_revalide_les_connexions_longues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_create_engine(
        url: object,
        **options: object,
    ) -> object:
        captured["url"] = url
        captured.update(options)
        return sentinel

    monkeypatch.setattr(
        database_module,
        "create_engine",
        fake_create_engine,
    )
    engine = database_module.build_engine(
        "postgresql+psycopg://robin:secret@localhost:5432/robin"
    )

    assert engine is sentinel
    assert captured["pool_pre_ping"] is True
    assert captured["pool_recycle"] == 240
    assert captured["connect_args"] == {"connect_timeout": 10}


def test_mot_de_passe_encode_et_sslmode_sont_preserves() -> None:
    value = (
        "postgresql://robin:p%40ss%3Aword%2Fplus@ep-example.neon.tech/robin"
        "?sslmode=require"
    )
    normalized = normalize_database_url(value)
    parsed = database_url_object(normalized)
    assert parsed.password == "p@ss:word/plus"
    assert parsed.query["sslmode"] == "require"
    assert "sslmode=require" in normalized
    assert "p%40ss%3Aword%2Fplus" in normalized
    assert "p%%40ss%%3Aword%%2Fplus" in alembic_database_url(value)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_absence_de_secret_est_explicite(value: str | None) -> None:
    with pytest.raises(DatabaseConfigurationError, match="absente"):
        normalize_database_url(value)


def test_secret_invalide_ne_fuit_pas_dans_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_marker = "NE_DOIT_JAMAIS_FUIR"
    monkeypatch.setenv(
        "ROBIN_DATABASE_URL",
        f"invalid-db://robin:{secret_marker}@example.invalid/robin",
    )
    registry = tmp_path / "registry"
    (registry / "manifests").mkdir(parents=True)
    (registry / "manifests" / "index.jsonl").write_text("", "utf-8")
    report = diagnose(tmp_path / "state", registry)
    encoded = json.dumps(report)
    assert report["database"]["error_code"] == "INVALID_DATABASE_CONFIGURATION"
    assert secret_marker not in encoded


def test_exception_de_configuration_ne_reprend_pas_la_valeur() -> None:
    secret_marker = "AUTRE_SECRET_INTERDIT"
    with pytest.raises(DatabaseConfigurationError) as captured:
        normalize_database_url(
            f"unsupported://robin:{secret_marker}@example.invalid/robin"
        )
    assert secret_marker not in str(captured.value)
