from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import robin.data_torrent.runtime as runtime_module
from robin.chronos_production import ChronosProductionError
from robin.data_torrent.runtime import (
    DataTorrentRuntimeError,
    LiveRuntimeEffects,
    _AccountingPostgresFunctionClient,
    execute_data_torrent,
)
from robin.prospective_observatory.chronos_postgres import (
    SQLAlchemyPostgresFunctionClient,
)
from scripts.run_data_torrent_v1 import _write_failure

ROOT = Path(__file__).resolve().parents[2]


def test_pre_database_failure_carries_complete_zero_effect_receipt(tmp_path: Path) -> None:
    with pytest.raises(DataTorrentRuntimeError) as caught:
        execute_data_torrent(
            repository_root=ROOT,
            config_path=ROOT / "configs" / "data" / "torrent-live-v1.json",
            output_dir=tmp_path / "artifacts",
            environment={},
            system_platform="linux",
        )
    receipt = caught.value.effect_receipt
    assert receipt["accounting_status"] == "COMPLETE_CONSERVATIVE"
    assert receipt["postgresql"] == {
        "read_transactions_attempted": 0,
        "function_reads_attempted": 0,
        "mutating_function_calls_attempted": 0,
        "mutating_function_calls_completed": 0,
        "mutating_function_outcomes_ambiguous": 0,
        "possible_durable_mutations_upper_bound": 0,
        "connection_attempts_upper_bound": 0,
        "automatic_retries": 0,
    }
    assert receipt["official"]["physical_reads_attempted"] == 0
    assert receipt["odds"]["provider_requests_attempted"] == 0
    assert receipt["r2"]["puts_attempted"] == 0


def test_mutating_postgresql_disconnect_is_conservatively_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effects = LiveRuntimeEffects()
    client = object.__new__(_AccountingPostgresFunctionClient)
    client._runtime_effects = effects

    def fail_call(
        _client: SQLAlchemyPostgresFunctionClient,
        _statement: str,
        _parameters: Any,
    ) -> dict[str, object]:
        raise RuntimeError("synthetic-disconnect")

    monkeypatch.setattr(SQLAlchemyPostgresFunctionClient, "fetch_one", fail_call)
    with pytest.raises(RuntimeError, match="synthetic-disconnect"):
        client.fetch_one("SELECT public.chronos_claim_opportunity(%s)", ("safe",))
    postgresql = effects.snapshot()["postgresql"]
    assert postgresql["mutating_function_calls_attempted"] == 1
    assert postgresql["mutating_function_calls_completed"] == 0
    assert postgresql["mutating_function_outcomes_ambiguous"] == 1
    assert postgresql["possible_durable_mutations_upper_bound"] == 1
    assert postgresql["automatic_retries"] == 0


def test_read_only_postgresql_function_is_not_counted_as_possible_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effects = LiveRuntimeEffects()
    client = object.__new__(_AccountingPostgresFunctionClient)
    client._runtime_effects = effects
    monkeypatch.setattr(
        SQLAlchemyPostgresFunctionClient,
        "fetch_one",
        lambda _client, _statement, _parameters: {"event_type": "CONFIRMED"},
    )
    assert client.fetch_one("SELECT public.chronos_get_effect_state(%s)", ("safe",))
    postgresql = effects.snapshot()["postgresql"]
    assert postgresql["function_reads_attempted"] == 1
    assert postgresql["mutating_function_calls_attempted"] == 0
    assert postgresql["possible_durable_mutations_upper_bound"] == 0


def test_postgresql_effect_is_blocked_when_authority_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effects = LiveRuntimeEffects()
    client = object.__new__(_AccountingPostgresFunctionClient)
    client._runtime_effects = effects
    network_calls = 0

    def closed() -> None:
        raise ChronosProductionError("CHRONOS_MISSION_EFFECT_ADMISSION_CLOSED")

    def forbidden(
        _client: SQLAlchemyPostgresFunctionClient,
        _statement: str,
        _parameters: Any,
    ) -> dict[str, object]:
        nonlocal network_calls
        network_calls += 1
        return {}

    monkeypatch.setattr(runtime_module, "validate_data_torrent_authority", closed)
    monkeypatch.setattr(SQLAlchemyPostgresFunctionClient, "fetch_one", forbidden)
    with pytest.raises(
        DataTorrentRuntimeError,
        match="CHRONOS_MISSION_EFFECT_ADMISSION_CLOSED",
    ):
        client.fetch_one("SELECT public.chronos_claim_opportunity(%s)", ("safe",))
    assert network_calls == 0
    assert effects.snapshot()["postgresql"]["mutating_function_calls_attempted"] == 0


def test_failure_artifact_persists_supplied_effect_receipt(tmp_path: Path) -> None:
    effects = LiveRuntimeEffects()
    effects.begin_read_transaction()
    effects.begin_function_call(mutating=True)
    effects.fail_function_call(mutating=True)
    output_dir = tmp_path / "failure"
    _write_failure(
        output_dir,
        "DATA_TORRENT_SYNTHETIC_FAILURE",
        effects=effects.snapshot(),
    )
    document = json.loads((output_dir / "torrent-run-failure-v1.json").read_text(encoding="utf-8"))
    assert document["error_code"] == "DATA_TORRENT_SYNTHETIC_FAILURE"
    assert document["secret_values_observed"] is False
    assert document["effects"]["accounting_status"] == "COMPLETE_CONSERVATIVE"
    assert document["effects"]["postgresql"]["read_transactions_attempted"] == 1
    assert document["effects"]["postgresql"]["mutating_function_outcomes_ambiguous"] == 1
