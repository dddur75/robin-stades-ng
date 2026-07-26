from __future__ import annotations

import hashlib
import inspect
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml
from botocore.exceptions import ClientError

from robin.historical.critical_closure import (
    PRODUCTION_STATUS,
    ObjectStorageAdapter,
    ObjectStorageIntegrityError,
)
from robin.historical.object_storage_migration import (
    create_r2_client,
    run_continuous_replication,
    run_migration,
    source_snapshot,
)
from robin.historical.object_storage_restore import run_representative_restore
from robin.historical.storage import HistoricalBundleStore
from scripts.manage_historical_state import append_r2_controls

ROOT = Path(__file__).resolve().parents[2]


def client_error(code: str, operation: str = "HeadObject") -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": f"simulated {code}"}},
        operation,
    )


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.metadata: dict[str, dict[str, str]] = {}
        self.head_error: ClientError | None = None
        self.missing_after_put = False
        self.put_calls = 0
        self.get_calls = 0

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        if self.head_error is not None:
            raise self.head_error
        if Key not in self.objects:
            raise client_error("404")
        return {
            "Metadata": self.metadata[Key],
            "ContentLength": len(self.objects[Key]),
        }

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        Metadata: Mapping[str, str],
    ) -> dict[str, object]:
        self.put_calls += 1
        self.objects[Key] = Body
        self.metadata[Key] = dict(Metadata)
        return {}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.get_calls += 1
        if self.missing_after_put or Key not in self.objects:
            raise client_error("NoSuchKey", "GetObject")
        return {"Body": BytesIO(self.objects[Key])}


class FlakyS3(FakeS3):
    def __init__(self, failures: int, code: str = "503") -> None:
        super().__init__()
        self.failures = failures
        self.code = code

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        if self.failures > 0:
            self.failures -= 1
            raise client_error(self.code)
        return super().head_object(Bucket=Bucket, Key=Key)


def factory(client: FakeS3) -> Any:
    return lambda environment: (client, "private-r2-bucket")


def write_files(root: Path, count: int) -> None:
    for index in range(count):
        path = root / "raw" / f"{index:04d}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"payload-{index}".encode())


def test_dry_run_ne_demande_aucun_secret_et_ne_supprime_rien(tmp_path: Path) -> None:
    write_files(tmp_path, 3)

    def forbidden_factory(environment: Mapping[str, str]) -> tuple[Any, str]:
        raise AssertionError("Le dry-run ne doit pas créer de client R2")

    report = run_migration(
        state=tmp_path,
        execute=False,
        max_files=25,
        environment={},
        client_factory=forbidden_factory,
    )

    assert report["mode"] == "DRY_RUN"
    assert report["source_files"] == 3
    assert report["selected_files"] == 3
    assert report["uploaded"] == 0
    assert report["replayed"] == 0
    assert report["remote_verified"] == 0
    assert report["deletions"] == 0
    assert report["source_mutations"] == 0
    assert report["double_write"] is True
    assert report["complete"] is False
    assert report["status"] == "DRY_RUN_READY"
    assert report["bucket_hash"] is None


def test_client_r2_utilise_endpoint_global_et_region_auto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    class FakeBoto3:
        @staticmethod
        def client(service: str, **kwargs: object) -> object:
            captured["service"] = service
            captured.update(kwargs)
            return sentinel

    monkeypatch.setattr(
        "robin.historical.object_storage_migration.importlib.import_module",
        lambda name: FakeBoto3,
    )
    client, bucket = create_r2_client(
        {
            "R2_ACCOUNT_ID": "account",
            "R2_ACCESS_KEY_ID": "access",
            "R2_SECRET_ACCESS_KEY": "secret",
            "R2_BUCKET_NAME": "bucket",
        }
    )

    assert client is sentinel
    assert bucket == "bucket"
    assert captured["service"] == "s3"
    assert captured["endpoint_url"] == "https://account.r2.cloudflarestorage.com"
    assert ".eu." not in str(captured["endpoint_url"])
    assert captured["region_name"] == "auto"


def test_client_error_404_est_un_objet_absent_reel_puis_upload() -> None:
    client = FakeS3()
    adapter = ObjectStorageAdapter(client, "private")

    outcome = adapter.upload("raw/a", b"payload")

    assert outcome["uploaded"] is True
    assert outcome["remote_verified"] is True
    assert client.put_calls == 1
    assert client.get_calls == 1


def test_client_error_403_reste_bloquante() -> None:
    client = FakeS3()
    client.head_error = client_error("403")
    adapter = ObjectStorageAdapter(client, "private")

    with pytest.raises(ClientError) as raised:
        adapter.upload("raw/a", b"payload")

    assert raised.value.response["Error"]["Code"] == "403"
    assert client.put_calls == 0
    assert client.get_calls == 0


def test_premier_upload_est_relu_et_verifie() -> None:
    client = FakeS3()
    adapter = ObjectStorageAdapter(client, "private")

    result = adapter.upload("raw/a", b"payload")

    assert result["uploaded"] is True
    assert result["remote_sha256"] == hashlib.sha256(b"payload").hexdigest()
    assert result["remote_size"] == len(b"payload")
    assert client.get_calls == 1


def test_replay_est_relu_et_verifie() -> None:
    client = FakeS3()
    adapter = ObjectStorageAdapter(client, "private")
    adapter.upload("raw/a", b"payload")
    reads_before = client.get_calls

    replay = adapter.upload("raw/a", b"payload")

    assert replay["uploaded"] is False
    assert replay["remote_verified"] is True
    assert client.put_calls == 1
    assert client.get_calls == reads_before + 1


def test_audit_d_un_objet_absent_echoue_sans_le_creer() -> None:
    client = FakeS3()
    adapter = ObjectStorageAdapter(client, "private")

    with pytest.raises(ObjectStorageIntegrityError) as raised:
        adapter.verify("raw/a", b"payload")

    assert raised.value.missing_remote_object is True
    assert client.put_calls == 0


def test_hash_distant_incorrect_fait_echouer_le_replay() -> None:
    client = FakeS3()
    expected = b"payload"
    client.objects["raw/a"] = b"PAYLOAD"
    client.metadata["raw/a"] = {"sha256": hashlib.sha256(expected).hexdigest()}
    adapter = ObjectStorageAdapter(client, "private")

    with pytest.raises(ObjectStorageIntegrityError) as raised:
        adapter.upload("raw/a", expected)

    assert raised.value.hash_mismatch is True
    assert raised.value.size_mismatch is False


def test_taille_distante_incorrecte_est_comptee() -> None:
    client = FakeS3()
    expected = b"payload"
    client.objects["raw/a"] = b"short"
    client.metadata["raw/a"] = {"sha256": hashlib.sha256(expected).hexdigest()}
    adapter = ObjectStorageAdapter(client, "private")

    with pytest.raises(ObjectStorageIntegrityError) as raised:
        adapter.upload("raw/a", expected)

    assert raised.value.hash_mismatch is True
    assert raised.value.size_mismatch is True


def test_objet_absent_apres_upload_est_une_incoherence_explicitement_comptee(
    tmp_path: Path,
) -> None:
    write_files(tmp_path, 1)
    client = FakeS3()
    client.missing_after_put = True

    with pytest.raises(ObjectStorageIntegrityError):
        run_migration(
            state=tmp_path,
            execute=True,
            max_files=1,
            environment={},
            client_factory=factory(client),
        )

    report = yaml.safe_load(
        (tmp_path / "storage" / "r2-migration-latest.json").read_text("utf-8")
    )
    assert report["missing_remote_objects"] == 1
    assert report["status"] == "OBJECT_STORAGE_REMOTE_MISSING"
    assert report["complete"] is False


def test_sources_sont_conservees_et_rapport_exclu_du_perimetre(tmp_path: Path) -> None:
    write_files(tmp_path, 4)
    report_path = tmp_path / "storage" / "r2-migration-latest.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text('{"old": true}', encoding="utf-8")
    manifest = tmp_path / "storage" / "r2-migration-manifest-0001.json"
    manifest.write_text("{}", encoding="utf-8")
    before = source_snapshot(tmp_path)
    client = FakeS3()

    report = run_migration(
        state=tmp_path,
        execute=True,
        max_files=25,
        environment={},
        client_factory=factory(client),
    )

    assert report["source_files"] == 4
    assert report["source_files_after"] == 4
    assert report["source_mutations"] == 0
    assert report["deletions"] == 0
    assert report["double_write"] is True
    assert report["complete"] is True
    assert source_snapshot(tmp_path) == before
    assert "storage/r2-migration-latest.json" not in client.objects
    assert "storage/r2-migration-manifest-0001.json" not in client.objects


def test_lot_25_est_idempotent_et_rejoue_par_lecture_distante(tmp_path: Path) -> None:
    write_files(tmp_path, 30)
    client = FakeS3()

    first = run_migration(
        state=tmp_path,
        execute=True,
        max_files=25,
        environment={},
        client_factory=factory(client),
    )
    second = run_migration(
        state=tmp_path,
        execute=True,
        max_files=25,
        environment={},
        client_factory=factory(client),
    )

    assert first["selected_files"] == 25
    assert first["uploaded"] == 25
    assert first["replayed"] == 0
    assert first["remote_verified"] == 25
    assert first["head_operations"] == 25
    assert first["put_operations"] == 25
    assert first["get_operations"] == 25
    assert first["r2_operations"] == 75
    assert first["retry_count"] == 0
    assert float(first["scan_seconds"]) >= 0
    assert float(first["head_seconds"]) >= 0
    assert float(first["upload_seconds"]) >= 0
    assert float(first["download_seconds"]) >= 0
    assert float(first["files_per_minute"]) > 0
    assert float(first["bytes_per_minute"]) > 0
    assert second["uploaded"] == 0
    assert second["replayed"] == 25
    assert second["remote_verified"] == 25
    assert second["head_operations"] == 25
    assert second["put_operations"] == 0
    assert second["get_operations"] == 25
    assert second["r2_operations"] == 50
    assert second["complete"] is False


def test_progression_cumulative_de_25_a_250(tmp_path: Path) -> None:
    write_files(tmp_path, 260)
    client = FakeS3()
    run_migration(
        state=tmp_path,
        execute=True,
        max_files=25,
        environment={},
        client_factory=factory(client),
    )

    report = run_migration(
        state=tmp_path,
        execute=True,
        max_files=250,
        environment={},
        client_factory=factory(client),
    )

    assert report["source_files"] == 260
    assert report["selected_files"] == 250
    assert report["uploaded"] == 225
    assert report["replayed"] == 25
    assert report["remote_verified"] == 250
    assert report["status"] == "PARTIAL_VERIFIED"
    assert report["complete"] is False


def test_reprise_s_amorce_depuis_le_prefixe_deja_verifie(tmp_path: Path) -> None:
    write_files(tmp_path, 5)
    client = FakeS3()
    initial = run_migration(
        state=tmp_path,
        execute=True,
        max_files=2,
        environment={},
        client_factory=factory(client),
    )

    resumed = run_migration(
        state=tmp_path,
        execute=True,
        max_files=2,
        resume=True,
        environment={},
        client_factory=factory(client),
    )

    assert initial["uploaded"] == 2
    assert resumed["selection_start_index"] == 2
    assert resumed["selection_end_index"] == 4
    assert resumed["uploaded"] == 2
    assert resumed["replayed"] == 0
    assert client.put_calls == 4
    checkpoint = yaml.safe_load(
        (tmp_path / "storage" / "r2-migration-checkpoint.json").read_text("utf-8")
    )
    assert checkpoint["bootstrapped_from_index"] == 2
    assert checkpoint["next_index"] == 4


def test_migration_segmentee_reprend_sans_retraiter_les_premiers_fichiers(
    tmp_path: Path,
) -> None:
    write_files(tmp_path, 5)
    client = FakeS3()

    first = run_migration(
        state=tmp_path,
        execute=True,
        max_files=2,
        resume=True,
        environment={},
        client_factory=factory(client),
    )
    second = run_migration(
        state=tmp_path,
        execute=True,
        max_files=2,
        resume=True,
        environment={},
        client_factory=factory(client),
    )
    third = run_migration(
        state=tmp_path,
        execute=True,
        max_files=2,
        resume=True,
        environment={},
        client_factory=factory(client),
    )

    assert first["selection_start_index"] == 0
    assert first["selection_end_index"] == 2
    assert second["selection_start_index"] == 2
    assert second["selection_end_index"] == 4
    assert second["uploaded"] == 2
    assert second["replayed"] == 0
    assert third["selection_start_index"] == 4
    assert third["uploaded"] == 1
    assert third["verified"] == 5
    assert third["pending"] == 0
    assert third["complete"] is True
    assert client.put_calls == 5

    checkpoint = yaml.safe_load(
        (tmp_path / "storage" / "r2-migration-checkpoint.json").read_text("utf-8")
    )
    assert checkpoint["next_index"] == 5
    assert checkpoint["status"] == "COMPLETE"
    index = yaml.safe_load(
        (tmp_path / "storage" / "r2-object-index.json").read_text("utf-8")
    )
    assert len(index["objects"]) == 5
    assert {entry["status"] for entry in index["objects"].values()} == {"verified"}


def test_audit_integral_est_segmente_et_n_ecrit_aucun_objet(tmp_path: Path) -> None:
    write_files(tmp_path, 5)
    client = FakeS3()
    migration = run_migration(
        state=tmp_path,
        execute=True,
        max_files=5,
        environment={},
        client_factory=factory(client),
    )
    puts_before_audit = client.put_calls

    first = run_migration(
        state=tmp_path,
        execute=True,
        max_files=2,
        resume=True,
        audit=True,
        environment={},
        client_factory=factory(client),
    )
    second = run_migration(
        state=tmp_path,
        execute=True,
        max_files=3,
        resume=True,
        audit=True,
        environment={},
        client_factory=factory(client),
    )

    assert migration["complete"] is True
    assert first["status"] == "AUDIT_PARTIAL_VERIFIED"
    assert first["verified"] == 2
    assert first["pending"] == 3
    assert first["uploaded"] == 0
    assert first["replayed"] == 2
    assert first["complete"] is False
    assert second["status"] == "AUDIT_COMPLETE_VERIFIED"
    assert second["verified"] == 5
    assert second["pending"] == 0
    assert second["uploaded"] == 0
    assert second["replayed"] == 3
    assert second["complete"] is True
    assert client.put_calls == puts_before_audit
    checkpoint = yaml.safe_load(
        (tmp_path / "storage" / "r2-audit-checkpoint.json").read_text("utf-8")
    )
    assert checkpoint["next_index"] == 5
    assert checkpoint["status"] == "COMPLETE"


def test_audit_reprend_le_meme_objet_apres_un_incident_resolu(
    tmp_path: Path,
) -> None:
    write_files(tmp_path, 2)
    client = FakeS3()
    run_migration(
        state=tmp_path,
        execute=True,
        max_files=1,
        environment={},
        client_factory=factory(client),
    )

    with pytest.raises(ObjectStorageIntegrityError):
        run_migration(
            state=tmp_path,
            execute=True,
            max_files=2,
            resume=True,
            audit=True,
            environment={},
            client_factory=factory(client),
        )
    failed_checkpoint = yaml.safe_load(
        (tmp_path / "storage" / "r2-audit-checkpoint.json").read_text("utf-8")
    )
    assert failed_checkpoint["next_index"] == 1
    assert failed_checkpoint["failed"] == 1

    second_payload = (tmp_path / "raw" / "0001.json").read_bytes()
    ObjectStorageAdapter(client, "private").upload("raw/0001.json", second_payload)
    recovered = run_migration(
        state=tmp_path,
        execute=True,
        max_files=2,
        resume=True,
        audit=True,
        environment={},
        client_factory=factory(client),
    )

    assert recovered["status"] == "AUDIT_COMPLETE_VERIFIED"
    assert recovered["verified"] == 2
    assert recovered["failed"] == 0
    assert recovered["complete"] is True


def test_replication_continue_envoie_uniquement_le_delta(tmp_path: Path) -> None:
    write_files(tmp_path, 3)
    client = FakeS3()
    run_migration(
        state=tmp_path,
        execute=True,
        max_files=1,
        environment={},
        client_factory=factory(client),
    )

    report = run_continuous_replication(
        state=tmp_path,
        max_files=10,
        environment={},
        client_factory=factory(client),
        retry_sleep=lambda seconds: None,
    )

    assert report["expected_objects"] == 3
    assert report["selected_files"] == 2
    assert report["uploaded"] == 2
    assert report["replayed"] == 0
    assert report["remote_verified"] == 2
    assert report["verified_objects"] == 3
    assert report["lag_objects"] == 0
    assert report["status"] == "SYNCED"
    assert report["source_preserved"] is True


def test_replication_continue_retry_borne_et_circuit_breaker(tmp_path: Path) -> None:
    write_files(tmp_path, 3)
    recovering = FlakyS3(1)

    recovered = run_continuous_replication(
        state=tmp_path,
        max_files=1,
        max_retries=2,
        environment={},
        client_factory=factory(recovering),
        retry_sleep=lambda seconds: None,
    )

    assert recovered["retry_count"] == 1
    assert recovered["uploaded"] == 1
    assert recovered["errors"] == 0
    assert recovered["circuit_breaker"] == "CLOSED"

    blocked_root = tmp_path / "blocked"
    write_files(blocked_root, 3)
    blocked = FlakyS3(20)
    report = run_continuous_replication(
        state=blocked_root,
        max_files=3,
        max_retries=0,
        circuit_breaker_failures=2,
        environment={},
        client_factory=factory(blocked),
        retry_sleep=lambda seconds: None,
    )

    assert report["errors"] == 2
    assert report["remote_verified"] == 0
    assert report["circuit_breaker"] == "OPEN"
    assert report["status"] == "CIRCUIT_OPEN"
    assert report["lag_objects"] == 3


def test_restauration_r2_representative_est_isolee_et_rejouable(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    json_path = state / "raw" / "sample.json"
    csv_path = state / "tables" / "sample.csv"
    parquet_path = state / "parquet" / "sample.parquet"
    checkpoint_path = state / "checkpoints" / "backfill-checkpoint.json"
    for path in (json_path, csv_path, parquet_path, checkpoint_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text('{"ok": true}', encoding="utf-8")
    csv_path.write_text("id,value\n1,ok\n", encoding="utf-8")
    pd.DataFrame(
        [
            {"id": 1, "_record_hash": "hash-1"},
            {"id": 2, "_record_hash": "hash-2"},
        ]
    ).to_parquet(parquet_path, index=False)
    checkpoint_path.write_text('{"cursor": 2}', encoding="utf-8")
    HistoricalBundleStore(state).create_bundle(
        [json_path],
        run_id="restore-test",
        competition="multi",
        season=0,
        endpoint="sample",
    )
    client = FakeS3()
    destination = tmp_path / "restored"

    report = run_representative_restore(
        state=state,
        destination=destination,
        environment={},
        client_factory=factory(client),
    )

    assert report["status"] == "RESTORE_VERIFIED"
    assert report["uploaded"] == report["selected_files"]
    assert report["remote_verified"] == report["selected_files"]
    assert report["restored_files"] == report["selected_files"]
    assert report["hash_mismatches"] == 0
    assert report["size_mismatches"] == 0
    assert report["data_loss"] == 0
    assert report["business_duplicates"] == 0
    assert report["parquet_readable"] == 1
    assert report["bundle_replay_files"] == 1
    assert report["registry_verified"] is True
    assert report["provider_calls"] == 0
    assert report["source_mutations"] == 0
    assert report["deletions"] == 0


def test_persistance_r2_legere_ne_republie_pas_les_sources(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    registry = tmp_path / "registry"
    raw = state / "raw" / "payload.json"
    control = state / "storage" / "r2-migration-latest.json"
    raw.parent.mkdir(parents=True)
    control.parent.mkdir(parents=True)
    raw.write_text('{"source": true}', encoding="utf-8")
    control.write_text('{"status": "PARTIAL_VERIFIED"}', encoding="utf-8")

    result = append_r2_controls(state, registry)

    assert result["status"] == "R2_CONTROLS_APPENDED"
    assert (
        registry / "historical" / "storage" / "r2-migration-latest.json"
    ).exists()
    assert not (registry / "historical" / "raw" / "payload.json").exists()
    manifest = yaml.safe_load(
        (registry / "historical" / "manifest.json").read_text("utf-8")
    )
    assert "storage/r2-migration-latest.json" in manifest["files"]
    action = (
        ROOT
        / ".github"
        / "actions"
        / "historical-r2-control-persist"
        / "action.yml"
    ).read_text("utf-8")
    assert yaml.safe_load(action)
    assert "append-r2-controls" in action
    assert "historical-state-persist" not in action


def test_lot_superieur_au_perimetre_produit_une_preuve_complete(tmp_path: Path) -> None:
    write_files(tmp_path, 3)
    client = FakeS3()

    report = run_migration(
        state=tmp_path,
        execute=True,
        max_files=10_000,
        environment={},
        client_factory=factory(client),
    )

    assert report["uploaded"] == 3
    assert report["remote_verified"] == 3
    assert report["complete"] is True
    assert report["status"] == "COMPLETE_VERIFIED"
    assert report["bucket_hash"] == hashlib.sha256(b"private-r2-bucket").hexdigest()
    serialized = (tmp_path / "storage" / "r2-migration-latest.json").read_text("utf-8")
    assert "private-r2-bucket" not in serialized


def test_aucun_mecanisme_de_suppression_n_existe() -> None:
    adapter_source = inspect.getsource(ObjectStorageAdapter)
    migration_source = inspect.getsource(run_migration)

    assert not hasattr(ObjectStorageAdapter, "delete")
    assert "delete_object" not in adapter_source
    assert "delete_object" not in migration_source


def test_production_reste_verrouillee() -> None:
    assert PRODUCTION_STATUS == "PRODUCTION_LOCKED"
    project_status = (ROOT / "PROJECT-STATUS.md").read_text("utf-8")
    assert "PRODUCTION_LOCKED" in project_status
    assert "REAL_BETS = false" in project_status


def test_workflow_22_valide_yaml_et_exclusivite_des_modes() -> None:
    path = ROOT / ".github" / "workflows" / "historical-quality.yml"
    text = path.read_text("utf-8")

    assert yaml.safe_load(text)
    for input_name in (
        "run_external_validation",
        "run_critical_closure",
        "run_object_storage_migration",
        "execute_object_storage_migration",
        "object_storage_max_files",
    ):
        assert input_name in text
    assert "default: 25" in text
    assert "inputs.run_external_validation && inputs.run_critical_closure" in text
    assert "inputs.run_external_validation && inputs.run_object_storage_migration" in text
    assert "inputs.run_critical_closure && inputs.run_object_storage_migration" in text
    assert "python -m pip install boto3" in text
    assert "region_name" not in text
    assert "historical-state-restore" in text
    assert "scripts/migrate_object_storage.py" in text
    assert "scripts/restore_object_storage.py" in text
    assert 'if [ "$requested" -eq 0 ]' in text
    assert 'if [ "$requested" -lt 0 ]' in text
    assert "batch_args+=(--audit)" in text
    assert "batch_args=(\"${args[@]}\" --max-files \"$batch\" --resume)" in text
    assert "historical-state-persist" in text
    assert "continue-on-error: true" in text
    assert "steps.object_storage_migration.outcome == 'failure'" in text
    assert "timeout-minutes: 120" in text
    assert "API_FOOTBALL_KEY" not in text
    assert "ODDS_API_KEY" not in text


def test_workflow_30_enchaine_uniquement_des_lots_reprenables() -> None:
    path = ROOT / ".github" / "workflows" / "object-storage-migration.yml"
    text = path.read_text("utf-8")

    assert yaml.safe_load(text)
    assert "max_batches_per_run" in text
    assert "(inputs.max_batches_per_run > 1 || inputs.audit) && !inputs.resume" in text
    assert "audit exigent resume=true" in text
    assert "args+=(--audit)" in text
    assert "for ((batch=1;" in text
    assert "['complete']" in text


def test_persistances_historiques_activent_le_delta_r2_sans_bloquer_git() -> None:
    action = (
        ROOT / ".github" / "actions" / "historical-state-persist" / "action.yml"
    ).read_text("utf-8")
    assert yaml.safe_load(action)
    assert "scripts/replicate_object_storage.py" in action
    assert "continue-on-error: true" in action
    assert "Signaler un replay R2 nécessaire" in action
    assert "r2-replication-enabled" in action

    excluded = {
        "historical-quality.yml",
        "object-storage-migration.yml",
        "object-storage-restore.yml",
    }
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = workflow.read_text("utf-8")
        if "uses: ./.github/actions/historical-state-persist" not in text:
            continue
        if workflow.name in excluded:
            assert "r2-replication-enabled: \"true\"" not in text
            continue
        assert "r2-replication-enabled: \"true\"" in text, workflow.name
        assert "r2-account-id: ${{ secrets.R2_ACCOUNT_ID }}" in text
        assert "r2-bucket-name: ${{ secrets.R2_BUCKET_NAME }}" in text
