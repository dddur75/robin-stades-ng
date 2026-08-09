from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from robin.storage.database import build_engine
from robin.storage.models import Base

JALON11_TABLES = {
    "deep_feature_definitions",
    "deep_feature_observations",
    "coverage_gates",
    "matchup_hypotheses",
    "matchup_evaluations",
    "prospective_watchlist",
    "shadow_candidate_versions",
}


def _alembic_config(database_url: str) -> Config:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _table(engine: sa.Engine, name: str) -> sa.Table:
    return sa.Table(name, sa.MetaData(), autoload_with=engine)


def _upgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sa.Engine:
    monkeypatch.delenv("ROBIN_DATABASE_URL", raising=False)
    database = tmp_path / "jalon11.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    command.upgrade(_alembic_config(url), "head")
    return build_engine(url)


def _proof_rows(now: datetime) -> dict[str, dict[str, object]]:
    return {
        "deep_feature_definitions": {
            "id": "feature-definition-1",
            "feature_id": "starter_baseline",
            "feature_version": "2.0.0",
            "feature_family": "PLAYER",
            "entity_level": "PLAYER",
            "cutoff_policy": "PRE_MATCH_STRICT",
            "contract": {"missing": "NULL_WITH_REASON"},
            "definition_hash": "a" * 64,
            "dataset_version": "team-prematch-v2",
            "dataset_hash": "b" * 64,
            "code_revision": "revision-j11",
            "created_at": now,
            "supersedes_id": None,
            "append_only": True,
            "simulation": True,
        },
        "deep_feature_observations": {
            "id": "feature-observation-1",
            "idempotency_key": "feature:fixture-1:player-1:starter-baseline",
            "feature_definition_id": "feature-definition-1",
            "fixture_id": "fixture-1",
            "entity_id": "player-1",
            "side": "HOME",
            "as_of_at": now,
            "value": {"score": 0.72},
            "missing_reason": None,
            "source_hash": "c" * 64,
            "observation_hash": "d" * 64,
            "dataset_version": "team-prematch-v2",
            "dataset_hash": "b" * 64,
            "code_revision": "revision-j11",
            "recorded_at": now,
            "append_only": True,
            "simulation": True,
        },
        "coverage_gates": {
            "id": "coverage-gate-1",
            "idempotency_key": "gate:player:ligue-1:2025:prematch",
            "gate_key": "PLAYER_GATE",
            "gate_version": "1.0.0",
            "competition": "Ligue 1",
            "season": "2025",
            "feature_family": "PLAYER",
            "cutoff_class": "PRE_MATCH",
            "status": "READY",
            "coverage": 0.95,
            "quality_score": 0.99,
            "evidence": {"rows": 306},
            "evidence_hash": "e" * 64,
            "dataset_version": "coverage-v1",
            "dataset_hash": "f" * 64,
            "code_revision": "revision-j11",
            "evaluated_at": now,
            "append_only": True,
            "simulation": True,
        },
        "matchup_hypotheses": {
            "id": "hypothesis-1",
            "hypothesis_id": "H11-001",
            "hypothesis_version": "1.0.0",
            "title": "Buteur en forme contre deux centraux absents",
            "family": "PLAYER_AVAILABILITY",
            "hypothesis": "Un delta strictement point-in-time améliore le marché.",
            "protocol": {"baseline": "B0_MARKET", "paired": True},
            "required_gates": ["PLAYER_GATE", "ABSENCE_GATE"],
            "status": "REGISTERED",
            "preregistration_hash": "1" * 64,
            "dataset_version": "matchup-v1",
            "dataset_hash": "2" * 64,
            "code_revision": "revision-j11",
            "registered_at": now,
            "frozen_at": now,
            "supersedes_id": None,
            "append_only": True,
            "simulation": True,
        },
        "matchup_evaluations": {
            "id": "evaluation-1",
            "idempotency_key": "evaluation:H11-001:walk-forward:2025:b1",
            "hypothesis_id": "hypothesis-1",
            "coverage_gate_id": "coverage-gate-1",
            "evaluation_scope": "WALK_FORWARD",
            "fold_key": "2025",
            "model_key": "B1_TEAM",
            "market": "1X2_HOME",
            "support": 306,
            "effect": 0.001,
            "metrics": {"log_loss_delta": 0.001},
            "p_value": 0.2,
            "q_value_family": 0.4,
            "q_value_global": 0.8,
            "status": "REJECTED",
            "paired_sample_hash": "3" * 64,
            "dataset_version": "matchup-v1",
            "dataset_hash": "2" * 64,
            "evaluation_hash": "4" * 64,
            "code_revision": "revision-j11",
            "evaluated_at": now,
            "append_only": True,
            "simulation": True,
        },
        "prospective_watchlist": {
            "id": "watchlist-1",
            "idempotency_key": "watchlist:H11-001:1.0.0",
            "candidate_key": "H11-001:1X2_HOME",
            "watchlist_version": "1.0.0",
            "hypothesis_id": "hypothesis-1",
            "evaluation_id": "evaluation-1",
            "status": "WATCHLIST",
            "reason": "Surveillance prospective uniquement.",
            "evidence": {"promotion_gate": "NOT_PASSED"},
            "evidence_hash": "5" * 64,
            "dataset_version": "matchup-v1",
            "dataset_hash": "2" * 64,
            "code_revision": "revision-j11",
            "entered_at": now,
            "expires_at": now + timedelta(days=30),
            "append_only": True,
            "simulation": True,
        },
        "shadow_candidate_versions": {
            "id": "shadow-candidate-1",
            "idempotency_key": "candidate:H11-001:1.0.0",
            "candidate_key": "H11-001:1X2_HOME",
            "candidate_version": "1.0.0",
            "watchlist_id": "watchlist-1",
            "status": "BLOCKED",
            "selection_rule": {"decision": "NO_BET"},
            "selection_rule_hash": "6" * 64,
            "evidence_hash": "7" * 64,
            "dataset_version": "matchup-v1",
            "dataset_hash": "2" * 64,
            "code_revision": "revision-j11",
            "production_status": "PRODUCTION_LOCKED",
            "real_bets": False,
            "no_bet_default": True,
            "payload": {"stake_units": 0},
            "created_at": now,
            "supersedes_id": None,
            "append_only": True,
            "simulation": True,
        },
    }


def test_upgrade_downgrade_upgrade_cree_le_schema_jalon11(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROBIN_DATABASE_URL", raising=False)
    database = tmp_path / "jalon11-cycle.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    config = _alembic_config(url)
    engine = build_engine(url)

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    assert JALON11_TABLES <= set(sa.inspect(engine).get_table_names())

    command.downgrade(config, "0007_jalon10_immutable_evidence")
    assert JALON11_TABLES.isdisjoint(sa.inspect(engine).get_table_names())

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    assert JALON11_TABLES <= set(sa.inspect(engine).get_table_names())
    with engine.connect() as connection:
        revision = connection.scalar(
            sa.text("SELECT version_num FROM alembic_version")
        )
    assert revision == "0015_chronos_fail_closed"


def test_modeles_et_migration_portent_timestamps_utc_hashes_et_versions() -> None:
    for table_name in JALON11_TABLES:
        table = Base.metadata.tables[table_name]
        assert "dataset_version" in table.c
        assert "dataset_hash" in table.c
        assert "code_revision" in table.c
        assert "append_only" in table.c
        assert "simulation" in table.c
        dataset_hash_type = table.c.dataset_hash.type
        assert isinstance(dataset_hash_type, sa.String)
        assert dataset_hash_type.length == 64

        timestamp_count = 0
        for column in table.c:
            if isinstance(column.type, sa.DateTime):
                timestamp_count += 1
                assert column.type.timezone
        assert timestamp_count > 0


def test_contraintes_simulation_append_only_unicite_hash_et_fk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _upgrade(tmp_path, monkeypatch)
    rows = _proof_rows(datetime(2026, 7, 27, 12, tzinfo=UTC))
    definitions = _table(engine, "deep_feature_definitions")

    with engine.begin() as connection:
        connection.execute(
            definitions.insert().values(**rows["deep_feature_definitions"])
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            definitions.insert().values(
                **{
                    **rows["deep_feature_definitions"],
                    "id": "feature-definition-duplicate",
                    "definition_hash": "8" * 64,
                }
            )
        )

    for field, value in (("simulation", False), ("append_only", False)):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                definitions.insert().values(
                    **{
                        **rows["deep_feature_definitions"],
                        "id": f"feature-definition-invalid-{field}",
                        "feature_id": f"invalid-{field}",
                        "definition_hash": (
                            "9" * 64 if field == "simulation" else "0" * 64
                        ),
                        field: value,
                    }
                )
            )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            definitions.insert().values(
                **{
                    **rows["deep_feature_definitions"],
                    "id": "feature-definition-invalid-hash",
                    "feature_id": "invalid-hash",
                    "definition_hash": "short",
                }
            )
        )

    observations = _table(engine, "deep_feature_observations")
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            observations.insert().values(
                **{
                    **rows["deep_feature_observations"],
                    "id": "orphan-observation",
                    "idempotency_key": "orphan-observation",
                    "feature_definition_id": "missing-definition",
                    "observation_hash": "9" * 64,
                }
            )
        )

    candidates = _table(engine, "shadow_candidate_versions")
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            candidates.insert().values(
                **{
                    **rows["shadow_candidate_versions"],
                    "id": "unsafe-candidate",
                    "idempotency_key": "unsafe-candidate",
                    "watchlist_id": "missing-watchlist",
                    "evidence_hash": "8" * 64,
                    "real_bets": True,
                }
            )
        )


def test_preuves_sont_protegees_par_triggers_append_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _upgrade(tmp_path, monkeypatch)
    rows = _proof_rows(datetime(2026, 7, 27, 12, tzinfo=UTC))
    definitions = _table(engine, "deep_feature_definitions")
    with engine.begin() as connection:
        connection.execute(
            definitions.insert().values(**rows["deep_feature_definitions"])
        )

    with engine.connect() as connection:
        trigger_count = connection.scalar(
            sa.text(
                "SELECT count(*) FROM sqlite_master "
                "WHERE type = 'trigger' "
                "AND name LIKE 'trg_%_append_only_%' "
                "AND tbl_name IN ("
                "'deep_feature_definitions', "
                "'deep_feature_observations', "
                "'coverage_gates', "
                "'matchup_hypotheses', "
                "'matchup_evaluations', "
                "'prospective_watchlist', "
                "'shadow_candidate_versions'"
                ")"
            )
        )
    assert trigger_count == len(JALON11_TABLES) * 2

    with pytest.raises(sa.exc.DatabaseError), engine.begin() as connection:
        connection.execute(
            definitions.update()
            .where(definitions.c.id == "feature-definition-1")
            .values(feature_family="MUTATED")
        )
    with pytest.raises(sa.exc.DatabaseError), engine.begin() as connection:
        connection.execute(
            definitions.delete().where(
                definitions.c.id == "feature-definition-1"
            )
        )

    with engine.connect() as connection:
        family = connection.scalar(
            sa.select(definitions.c.feature_family).where(
                definitions.c.id == "feature-definition-1"
            )
        )
    assert family == "PLAYER"


def test_replay_complet_est_idempotent_et_ne_duplique_aucune_preuve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _upgrade(tmp_path, monkeypatch)
    rows = _proof_rows(datetime(2026, 7, 27, 12, tzinfo=UTC))

    inserted_by_pass: list[dict[str, int]] = []
    for _ in range(2):
        inserted: dict[str, int] = {}
        with engine.begin() as connection:
            for table_name in (
                "deep_feature_definitions",
                "deep_feature_observations",
                "coverage_gates",
                "matchup_hypotheses",
                "matchup_evaluations",
                "prospective_watchlist",
                "shadow_candidate_versions",
            ):
                table = _table(engine, table_name)
                result = connection.execute(
                    sqlite_insert(table)
                    .values(**rows[table_name])
                    .on_conflict_do_nothing()
                )
                inserted[table_name] = result.rowcount
        inserted_by_pass.append(inserted)

    assert inserted_by_pass[0] == {
        table_name: 1 for table_name in JALON11_TABLES
    }
    assert inserted_by_pass[1] == {
        table_name: 0 for table_name in JALON11_TABLES
    }
    with engine.connect() as connection:
        counts = {
            table_name: connection.scalar(
                sa.text(f"SELECT count(*) FROM {table_name}")
            )
            for table_name in JALON11_TABLES
        }
    assert counts == {table_name: 1 for table_name in JALON11_TABLES}
