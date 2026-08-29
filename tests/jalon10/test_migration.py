from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from robin.patterns.ledger import EvidenceLedger
from robin.patterns.persistence import persist_campaign
from robin.storage.database import build_engine
from robin.storage.durable import read_bundle
from scripts.manage_durable_registry import (
    append_bridge,
    persist_registry,
    stage,
)

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
    assert revision == "0015_data_torrent_opportunity"


def test_0007_versionne_la_contrainte_sans_recrire_0006(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROBIN_DATABASE_URL", raising=False)
    database = tmp_path / "jalon10-versioned-constraint.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    config = _alembic_config(url)

    command.upgrade(config, "0006_jalon10_pattern_ledger")
    engine = build_engine(url)
    before = {
        item["name"]: item["column_names"]
        for item in sa.inspect(engine).get_unique_constraints(
            "experiment_registry"
        )
    }
    assert before["uq_experiment_preregistration_hash"] == [
        "preregistration_hash"
    ]

    command.upgrade(config, "head")
    after = {
        item["name"]: item["column_names"]
        for item in sa.inspect(engine).get_unique_constraints(
            "experiment_registry"
        )
    }
    assert after["uq_experiment_preregistration_hash"] == [
        "preregistration_hash",
        "experiment_version",
    ]


def test_0007_bloque_update_et_delete_du_ledger_en_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROBIN_DATABASE_URL", raising=False)
    database = tmp_path / "jalon10-immutable-ledger.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    command.upgrade(_alembic_config(url), "head")
    engine = build_engine(url)
    ledger = _table(engine, "evidence_ledger")
    record = {
        "id": "ledger-immutable",
        "record_id": "record-immutable",
        "idempotency_key": "ledger:record-immutable",
        "sequence_no": 0,
        "record_type": "DECISION",
        "pattern_decision_id": None,
        "pattern_settlement_id": None,
        "previous_record_hash": "0" * 64,
        "record_hash": "e" * 64,
        "payload": {"decision": "NO_BET"},
        "recorded_at": datetime(2026, 7, 27, 12, tzinfo=UTC),
        "append_only": True,
        "simulation": True,
    }
    with engine.begin() as connection:
        connection.execute(ledger.insert().values(**record))

    with pytest.raises(sa.exc.DatabaseError), engine.begin() as connection:
        connection.execute(
            ledger.update()
            .where(ledger.c.id == record["id"])
            .values(payload={"decision": "BET"})
        )
    with pytest.raises(sa.exc.DatabaseError), engine.begin() as connection:
        connection.execute(
            ledger.delete().where(ledger.c.id == record["id"])
        )

    with engine.connect() as connection:
        persisted = connection.execute(
            sa.select(ledger.c.payload).where(ledger.c.id == record["id"])
        ).scalar_one()
    assert persisted == {"decision": "NO_BET"}


def test_base_vierge_jusqua_0005_ne_cree_pas_le_schema_jalon10(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROBIN_DATABASE_URL", raising=False)
    database = tmp_path / "pre-jalon10.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    command.upgrade(
        _alembic_config(url),
        "0005_jalon9_critical_closure",
    )
    assert JALON10_TABLES.isdisjoint(
        sa.inspect(build_engine(url)).get_table_names()
    )


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
    payload: dict[str, object] = {
        "dataset_hashes": ["a" * 64],
        "code_revision": "abc123",
        "data_classification": "DISCOVERY_EXPOSED",
        "verdict": "JALON_10_NO_ROBUST_PATTERN_FOUND",
        "config": {
            "seed": 10010,
            "preregistered_at": "2026-07-27T00:00:00+00:00",
            "fdr_alpha": 0.05,
            "feature_cutoff": "HISTORICAL_PRICE_CATEGORY_NO_EXACT_CUTOFF",
            "odds_type": "HISTORICAL_CLOSING_OR_PRE_CLOSING_MARKET",
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
    stable = {
        key: value
        for key, value in payload.items()
        if key not in {"checkpoint", "verdict"}
    }
    digest = hashlib.sha256(
        json.dumps(
            stable,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    payload["result_hash"] = digest
    payload["checkpoint"] = {
        **dict(payload["checkpoint"]),
        "result_hash": digest,
    }
    return payload


def test_persistance_campaign_est_idempotente_et_versionnee(
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

    evolved = _campaign_payload()
    evolved["code_revision"] = "def456"
    evolved["dataset_hashes"] = ["c" * 64]
    stable = {
        key: value
        for key, value in evolved.items()
        if key not in {"checkpoint", "result_hash", "verdict"}
    }
    evolved_hash = hashlib.sha256(
        json.dumps(
            stable,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    evolved["result_hash"] = evolved_hash
    evolved["checkpoint"] = {
        **dict(evolved["checkpoint"]),
        "result_hash": evolved_hash,
    }
    second_version = persist_campaign(engine, evolved)
    assert second_version["inserted"] == {
        "runs": 1,
        "definitions": 1,
        "evaluations": 1,
        "experiments": 1,
    }
    with engine.connect() as connection:
        assert connection.scalar(
            sa.text("SELECT count(*) FROM pattern_definitions")
        ) == 2

    tampered = _campaign_payload()
    tampered["code_revision"] = "tampered-without-new-hash"
    with pytest.raises(ValueError, match="PATTERN_CAMPAIGN_RESULT_HASH_MISMATCH"):
        persist_campaign(engine, tampered)


def test_ledger_et_registre_candidats_traversent_le_pont_durable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROBIN_DATABASE_URL", raising=False)
    state = tmp_path / "shadow"
    candidate_path = (
        state
        / "pattern-research"
        / "shadow-candidate-registry.json"
    )
    candidate_path.parent.mkdir(parents=True)
    candidate_registry = {
        "schema_version": "pattern-shadow-candidates-v1",
        "source_result_hash": "a" * 64,
        "dataset_hashes": ["b" * 64],
        "code_revision": "abc123",
        "data_classification": "DISCOVERY_EXPOSED",
        "verdict": "JALON_10_NO_ROBUST_PATTERN_FOUND",
        "config": {"live_market_point_in_time": False},
        "provider_calls": 0,
        "odds_api_credits": 0,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
        "no_bet_default": True,
        "social_publishing_enabled": False,
        "demo_mode_enabled": False,
        "candidate_count": 0,
        "hypotheses": [],
    }
    candidate_path.write_text(
        json.dumps(candidate_registry),
        encoding="utf-8",
    )
    assert candidate_path.stat().st_size < 262_144
    ledger = EvidenceLedger(state / "pattern-evidence-ledger.jsonl")
    published = datetime(2026, 8, 1, 10, tzinfo=UTC)
    cutoff = datetime(2026, 8, 1, 11, tzinfo=UTC)
    kickoff = datetime(2026, 8, 1, 12, tzinfo=UTC)
    ledger.append_decision(
        decision_id="decision-live-1",
        published_at=published,
        cutoff_at=cutoff,
        fixture_id="odds-api-uuid-1",
        competition="Ligue 1",
        kickoff_at=kickoff,
        market="1X2_HOME",
        selection="HOME",
        odds=2.0,
        odds_source="POINT_IN_TIME_CACHE",
        pattern_id="PTRN-LIVE",
        pattern_version="1.0.0",
        decision="BET",
        code_revision="abc123",
        dataset_hash="b" * 64,
    )
    ledger.append_settlement(
        settlement_id="settlement-live-1",
        decision_id="decision-live-1",
        settled_at=datetime(2026, 8, 1, 15, tzinfo=UTC),
        result="WIN",
        profit_units=1.0,
    )

    outbox = tmp_path / "outbox"
    staged = stage(state, outbox, "jalon10-durable-test")
    bundle = read_bundle(Path(str(staged["bundle"])))
    kinds = [str(item["kind"]) for item in bundle["records"]]
    assert "quality_runs" in kinds
    assert "candidate_bets" in kinds
    assert "settlements" in kinds
    serialized_bundle = json.dumps(bundle)
    assert '"candidate_count": 0' in serialized_bundle
    assert "hypotheses_generated" not in serialized_bundle

    registry = tmp_path / "shadow-data"
    appended = append_bridge(outbox, registry)
    assert appended["bundles_appended"] == 1
    database = tmp_path / "jalon10-durable.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    command.upgrade(_alembic_config(url), "head")

    first = persist_registry(registry, url)
    replay = persist_registry(registry, url)
    assert first["pattern_ledger"]["inserted"] == {
        "decisions": 1,
        "settlements": 1,
        "bankroll_events": 1,
        "evidence_records": 2,
    }
    assert replay["pattern_ledger"]["inserted"] == {
        "decisions": 0,
        "settlements": 0,
        "bankroll_events": 0,
        "evidence_records": 0,
    }
    engine = build_engine(url)
    with engine.connect() as connection:
        assert connection.scalar(
            sa.text("SELECT count(*) FROM pattern_decisions")
        ) == 1
        assert connection.scalar(
            sa.text("SELECT count(*) FROM pattern_settlements")
        ) == 1
        assert connection.scalar(
            sa.text("SELECT count(*) FROM bankroll_events")
        ) == 1
        assert connection.scalar(
            sa.text("SELECT count(*) FROM evidence_ledger")
        ) == 2
