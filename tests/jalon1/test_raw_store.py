from datetime import UTC, datetime, timedelta

import pytest

from robin.ingestion.raw_store import LocalRawStore


def test_stockage_brut_est_append_only_et_dedoublonne_le_payload(tmp_path) -> None:
    store = LocalRawStore(tmp_path / "raw")
    requested = datetime(2026, 7, 24, 10, tzinfo=UTC)
    payload = b'{"fixture": 42}'
    arguments = dict(
        provider="mock",
        endpoint="/fixtures",
        request_parameters={"league": "F1", "api_key": "secret-value"},
        requested_at=requested,
        received_at=requested + timedelta(seconds=1),
        http_status=200,
        payload=payload,
        schema_version="1",
        ingestion_run_id="run-1",
    )

    first = store.store(**arguments)
    second = store.store(**arguments)

    assert first.observation_id != second.observation_id
    assert first.raw_payload_location == second.raw_payload_location
    assert first.request_parameters["api_key"] == "[REDACTED]"
    assert store.load_payload(first) == payload
    assert len(store.iter_observations()) == 2
    assert len(list((tmp_path / "raw" / "payloads").rglob("*.bin"))) == 1


def test_payload_altere_est_detecte(tmp_path) -> None:
    store = LocalRawStore(tmp_path / "raw")
    now = datetime(2026, 7, 24, 10, tzinfo=UTC)
    observation = store.store(
        provider="mock",
        endpoint="/fixtures",
        request_parameters={},
        requested_at=now,
        received_at=now,
        http_status=200,
        payload=b"original",
        schema_version="1",
        ingestion_run_id="run-1",
    )
    payload_path = tmp_path / "raw" / "payloads" / observation.raw_payload_location
    payload_path.write_bytes(b"mutation")

    with pytest.raises(RuntimeError, match="hash"):
        store.load_payload(observation)


def test_secret_imbrique_n_est_jamais_persiste(tmp_path) -> None:
    store = LocalRawStore(tmp_path / "raw")
    now = datetime(2026, 7, 24, 10, tzinfo=UTC)
    observation = store.store(
        provider="mock",
        endpoint="/odds",
        request_parameters={
            "filters": {"authorization": "Bearer secret"},
            "regions": ["eu"],
        },
        requested_at=now,
        received_at=now,
        http_status=200,
        payload=b"[]",
        schema_version="1",
        ingestion_run_id="run-1",
    )

    assert observation.request_parameters["filters"] == {
        "authorization": "[REDACTED]"
    }

