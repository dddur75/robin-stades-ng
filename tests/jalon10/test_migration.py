from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from robin.patterns.persistence import persist_campaign
from robin.storage.database import build_engine

JALON10_TABLES = {
    "pattern_definitions",
    "pattern_runs",
    "pattern_evaluations",
    "pattern_decisions",
    "pattern_settlements",
    "bankroll_events",
    "evidence_ledger",
    "experiment_registry",
}


def _alembic_config(database_url: str) -> Config:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _table(engine: sa.Engine, name: str) -> sa.Table:
    return sa.Table(name, sa.MetaData(), autoload_with=engine)


def test_upgrade_downgrade_upgrade_cree_le_schema_jalon10(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROBIN_DATABASE_URL", raising=False)
    database = tmp_path / "jalon10-cycle.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    config = _alembic_config(url)
    engine = build_engine(url)

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    assert JALON10_TABLES <= set(sa.inspect(engine).get_table_names())

    command.downgrade(config, "0005_jalon9_critical_closure")
    assert JALON10_TABLES.isdisjoint(sa.inspect(engine).get_table_names())

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    assert JALON10_TABLES <= set(sa.inspect(engine).get_table_names())
    with engine.connect() as connection:
        revision = connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
    assert revision == "0006_jalon10_pattern_ledger"


def test_contraintes_idempotence_fk_et_shadow_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROBIN_DATABASE_URL", raising=False)
    database = tmp_path / "jalon10-constraints.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    config = _alembic_config(url)
    command.upgrade(config, "head")
    command.downgrade(config, "0005_jalon9_critical_closure")
    command.upgrade(config, "head")
    engine = build_engine(url)
    now = datetime(2026, 7, 27, 12, tzinfo=UTC)

    runs = _table(engine, "pattern_runs")
    run = {
        "id": "run-1",
        "idempotency_key": "discovery:dataset-a:seed-42",
        "run_type": "DISCOVERY",
        "seed": 42,
        "code_revision": "abc123",
        "configuration": {"max_conditions": 3},
        "dataset_hashes": ["a" * 64],
        "environment": {"provider_calls": 0},
        "started_at": now,
        "finished_at": now,
        "status": "COMPLETED",
        "rules_generated": 10,
        "rules_executed": 10,
        "rules_rejected": 9,
        "cost_units": 0.0,
        "checkpoint": {"complete": True},
        "simulation": True,
    }
    with engine.begin() as connection:
        connection.execute(runs.insert().values(**run))

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            runs.insert().values(
                **{
                    **run,
                    "id": "run-replay-with-new-identity",
                }
            )
        )

    evaluations = _table(engine, "pattern_evaluations")
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            evaluations.insert().values(
                id="evaluation-orphan",
                pattern_definition_id="missing-pattern",
                pattern_run_id="missing-run",
                evaluation_scope="WALK_FORWARD",
                fold_key="2024",
                support=50,
                metrics={"roi": 0.01},
                p_value=0.2,
                q_value=0.4,
                status="REJECTED",
                dataset_hash="b" * 64,
                evaluated_at=now,
                simulation=True,
            )
        )

    ledger = _table(engine, "evidence_ledger")
    invalid_record = {
        "id": "ledger-1",
        "record_id": "record-1",
        "idempotency_key": "ledger:record-1",
        "sequence_no": 0,
        "record_type": "DECISION",
        "pattern_decision_id": None,
        "pattern_settlement_id": None,
        "previous_record_hash": "0" * 64,
        "record_hash": "c" * 64,
        "payload": {"decision": "NO_BET"},
        "recorded_at": now,
        "append_only": False,
        "simulation": True,
    }
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(ledger.insert().values(**invalid_record))

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            ledger.insert().values(
                **{
                    **invalid_record,
                    "append_only": True,
                    "simulation": False,
                }
            )
        )


def test_unicites_metier_definitions_evaluations_et_settlements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROBIN_DATABASE_URL", raising=False)
    database = tmp_path / "jalon10-uniques.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    config = _alembic_config(url)
    command.upgrade(config, "head")
    command.downgrade(config, "0005_jalon9_critical_closure")
    command.upgrade(config, "head")
    engine = build_engine(url)
    now = datetime(2026, 7, 27, 12, tzinfo=UTC)

    definitions = _table(engine, "pattern_definitions")
    definition = {
        "id": "definition-1",
        "pattern_id": "PTRN-ABC",
        "pattern_version": "1.0.0",
        "rule_hash": "d" * 64,
        "sport": "football",
        "market": "1X2",
        "selection": "HOME",
        "status": "DISCOVERED",
        "evidence_scope": "DISCOVERY_EXPOSED",
        "definition": {"conditions": [{"feature": "home_form"}]},
        "code_revision": "abc123",
        "dataset_hashes": ["a" * 64],
        "created_at": now,
        "supersedes_id": None,
    }
    with engine.begin() as connection:
        connection.execute(definitions.insert().values(**definition))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            definitions.insert().values(
                **{
                    **definition,
                    "id": "definition-duplicate",
                    "rule_hash": "e" * 64,
                }
            )
        )

    decisions = _table(engine, "pattern_decisions")
    decision = {
        "id": "decision-row-1",
        "decision_id": "decision-1",
        "idempotency_key": "decision:fixture-1:1x2",
        "pattern_definition_id": "definition-1",
        "pattern_run_id": None,
        "published_at": now,
        "cutoff_at": now,
        "fixture_id": "fixture-1",
        "competition": "Ligue 1",
        "kickoff_at": datetime(2026, 7, 27, 18, tzinfo=UTC),
        "market": "1X2",
        "selection": "HOME",
        "odds": 2.0,
        "odds_source": "CACHE",
        "decision": "BET",
        "stake_units": 1.0,
        "shadow_bankroll_before": 1000.0,
        "status": "LIVE_SHADOW",
        "code_revision": "abc123",
        "dataset_hash": "a" * 64,
        "payload": {},
        "simulation": True,
    }
    with engine.begin() as connection:
        connection.execute(decisions.insert().values(**decision))

    settlements = _table(engine, "pattern_settlements")
    settlement = {
        "id": "settlement-row-1",
        "settlement_id": "settlement-1",
        "idempotency_key": "settlement:decision-1",
        "pattern_decision_id": "decision-row-1",
        "settled_at": now,
        "result": "WIN",
        "profit_units": 1.0,
        "shadow_bankroll_after": 1001.0,
        "payload": {},
        "simulation": True,
    }
    with engine.begin() as connection:
        connection.execute(settlements.insert().values(**settlement))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            settlements.insert().values(
                **{
                    **settlement,
                    "id": "settlement-row-2",
                    "settlement_id": "settlement-2",
                    "idempotency_key": "settlement:decision-1:duplicate",
                }
            )
        )


def _campaign_payload() -> dict[str, object]:
    return {
        "result_hash": "f" * 64,
        "dataset_hashes": ["a" * 64],
        "code_revision": "abc123",
        "data_classification": "DISCOVERY_EXPOSED",
        "verdict": "JALON_10_NO_ROBUST_PATTERN_FOUND",
        "config": {
            "seed": 10010,
            "preregistered_at": "2026-07-27T00:00:00+00:00",
            "fdr_alpha": 0.05,
        },
        "counts": {
            "hypotheses_generated": 1,
            "hypotheses_executed": 1,
            "leakage_rejected": 0,
            "support_rejected": 1,
        },
        "checkpoint": {
            "status": "COMPLETE",
            "rules_completed": 1,
            "result_hash": "f" * 64,
        },
        "hypotheses": [
            {
                "rule_hash": "b" * 64,
                "market": "1X2_HOME",
                "selection": "HOME",
                "conditions": [
                    {
                        "feature": "competition",
                        "operator": "EQ",
                        "value": "Ligue 1",
                    }
                ],
                "status": "INSUFFICIENT_SUPPORT",
                "evidence_scope": "DISCOVERY_EXPOSED",
                "support": {"observations": 10},
                "metrics": None,
                "p_value": 1.0,
                "q_value": 1.0,
            }
        ],
    }


def test_persistance_campaign_est_idempotente_et_immutable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROBIN_DATABASE_URL", raising=False)
    database = tmp_path / "jalon10-persistence.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    command.upgrade(_alembic_config(url), "head")
    engine = build_engine(url)
    payload = _campaign_payload()

    first = persist_campaign(engine, payload)
    replay = persist_campaign(engine, payload)
    assert first["inserted"] == {
        "runs": 1,
        "definitions": 1,
        "evaluations": 1,
        "experiments": 1,
    }
    assert replay["inserted"] == {
        "runs": 0,
        "definitions": 0,
        "evaluations": 0,
        "experiments": 0,
    }
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT count(*) FROM pattern_runs")) == 1
        assert (
            connection.scalar(sa.text("SELECT count(*) FROM pattern_evaluations"))
            == 1
        )

    conflicting = _campaign_payload()
    hypotheses = list(conflicting["hypotheses"])
    hypotheses[0] = {**hypotheses[0], "status": "HISTORICAL_CANDIDATE"}
    conflicting["hypotheses"] = hypotheses
    with pytest.raises(ValueError, match="IMMUTABLE_PATTERN_PERSISTENCE_CONFLICT"):
        persist_campaign(engine, conflicting)
