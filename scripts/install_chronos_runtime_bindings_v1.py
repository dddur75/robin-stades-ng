"""Generate and install the four exact scoped Chronos environment bindings."""

from __future__ import annotations

import argparse
import hmac
import json
import re
import secrets
import subprocess  # nosec B404 - argv-only invocation of the GitHub CLI.
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from robin.chronos_production import (
    EXPECTED_AFTER_REVISION,
    EXPECTED_BEFORE_REVISIONS,
    EXPECTED_ENVIRONMENT,
    EXPECTED_REPOSITORY,
    DirectPostgresTarget,
    build_scoped_database_url,
    generation_hash,
    preflight_hash,
    require_sha,
)

if __package__ in {None, ""}:
    from github_release_attestation_v1 import (  # type: ignore[import-not-found]
        assert_current_main,
        attest_and_download,
    )
else:
    from scripts.github_release_attestation_v1 import assert_current_main, attest_and_download

BINDINGS = (
    ("CHRONOS_AUTHORITY_DATABASE_URL", "chronos_authority_runtime_login"),
    ("CHRONOS_RUNTIME_DATABASE_URL", "chronos_effect_runtime_login"),
    ("CHRONOS_READER_DATABASE_URL", "chronos_reader_login"),
)
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID = re.compile(r"^[1-9][0-9]*$")
_PREFLIGHT_FIELDS = frozenset(
    {
        "schema_version",
        "main_sha",
        "workflow_sha",
        "project_id",
        "production_branch_id",
        "current_revision",
        "role_inventory_hash",
        "role_inventory",
        "recovery_branch_id",
        "golden_gate",
        "database_host",
        "database_port",
        "database_name",
        "sslmode",
        "channel_binding",
        "created_at",
        "expires_at",
        "preflight_run_id",
        "preflight_run_attempt",
        "post_merge_ci_sha",
        "preflight_hash",
        "signature",
    }
)


class BindingInstallerError(RuntimeError):
    """Sanitized local installer error."""


def _attest_preflight_artifact(
    path: Path,
    *,
    expected_main_sha: str,
    expected_preflight_run_id: str,
) -> tuple[dict[str, Any], bytes]:
    """Bind the local input byte-for-byte to one successful GitHub artifact."""

    try:
        local_bytes = path.read_bytes()
    except OSError:
        raise BindingInstallerError("CHRONOS_BINDING_PREFLIGHT_INVALID") from None
    if not local_bytes or len(local_bytes) > 10 * 1024 * 1024 or path.is_symlink():
        raise BindingInstallerError("CHRONOS_BINDING_PREFLIGHT_INVALID")
    with tempfile.TemporaryDirectory(prefix="robin-preflight-attestation-") as temp_name:
        downloaded = Path(temp_name) / "chronos-preflight-artifact-v3.json"
        try:
            attestation = attest_and_download(
                repository=EXPECTED_REPOSITORY,
                workflow_path=".github/workflows/chronos-production-bootstrap-v3.yml",
                run_id=expected_preflight_run_id,
                main_sha=expected_main_sha,
                artifact_name=f"chronos-preflight-v3-{expected_preflight_run_id}",
                artifact_filename="chronos-preflight-artifact-v3.json",
                output_path=downloaded,
            )
            downloaded_bytes = downloaded.read_bytes()
        except Exception:
            raise BindingInstallerError("CHRONOS_BINDING_PREFLIGHT_ATTESTATION_FAILED") from None
    if not hmac.compare_digest(local_bytes, downloaded_bytes):
        raise BindingInstallerError("CHRONOS_BINDING_PREFLIGHT_BYTES_MISMATCH")
    return attestation, local_bytes


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise BindingInstallerError("CHRONOS_BINDING_PREFLIGHT_EXPIRY_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise BindingInstallerError("CHRONOS_BINDING_PREFLIGHT_EXPIRY_INVALID") from None
    if parsed.tzinfo is None:
        raise BindingInstallerError("CHRONOS_BINDING_PREFLIGHT_EXPIRY_INVALID")
    return parsed.astimezone(UTC)


def _artifact_bytes(
    payload: bytes,
    *,
    expected_main_sha: str,
    expected_preflight_run_id: str,
) -> dict[str, Any]:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise BindingInstallerError("CHRONOS_BINDING_PREFLIGHT_INVALID") from None
    if not isinstance(document, dict):
        raise BindingInstallerError("CHRONOS_BINDING_PREFLIGHT_INVALID")
    artifact = cast(dict[str, Any], document)
    if set(artifact) != _PREFLIGHT_FIELDS:
        raise BindingInstallerError("CHRONOS_BINDING_PREFLIGHT_SCHEMA_MISMATCH")
    if artifact.get("schema_version") != "chronos-preflight-artifact-v3":
        raise BindingInstallerError("CHRONOS_BINDING_PREFLIGHT_SCHEMA_MISMATCH")

    expected_sha = require_sha(expected_main_sha, field="expected_main_sha")
    if _RUN_ID.fullmatch(expected_preflight_run_id) is None:
        raise BindingInstallerError("CHRONOS_BINDING_PREFLIGHT_RUN_INVALID")
    if (
        artifact.get("preflight_run_id") != expected_preflight_run_id
        or artifact.get("preflight_run_attempt") != "1"
    ):
        raise BindingInstallerError("CHRONOS_BINDING_PREFLIGHT_RUN_MISMATCH")

    identity_fields = ("project_id", "production_branch_id", "recovery_branch_id")
    identities = [artifact.get(field) for field in identity_fields]
    if any(
        not isinstance(value, str) or not value or value != value.strip() for value in identities
    ) or len(set(identities)) != len(identities):
        raise BindingInstallerError("CHRONOS_BINDING_PREFLIGHT_IDENTITY_INVALID")

    signature = artifact.get("signature")
    if (
        not isinstance(signature, dict)
        or set(signature) != {"algorithm", "value"}
        or signature.get("algorithm") != "HMAC-SHA256"
        or not isinstance(signature.get("value"), str)
        or _HEX_64.fullmatch(cast(str, signature.get("value"))) is None
    ):
        raise BindingInstallerError("CHRONOS_BINDING_PREFLIGHT_SIGNATURE_INVALID")

    if (
        not isinstance(artifact.get("role_inventory"), dict)
        or not isinstance(artifact.get("role_inventory_hash"), str)
        or _HEX_64.fullmatch(cast(str, artifact.get("role_inventory_hash"))) is None
        or type(artifact.get("database_port")) is not int
    ):
        raise BindingInstallerError("CHRONOS_BINDING_PREFLIGHT_SCHEMA_MISMATCH")
    if (
        artifact.get("main_sha") != expected_sha
        or artifact.get("workflow_sha") != expected_sha
        or artifact.get("post_merge_ci_sha") != expected_sha
        or artifact.get("golden_gate") != "CHRONOS_MIGRATION_READY"
        or artifact.get("current_revision")
        not in {*EXPECTED_BEFORE_REVISIONS, EXPECTED_AFTER_REVISION}
        or artifact.get("preflight_hash") != preflight_hash(artifact)
    ):
        raise BindingInstallerError("CHRONOS_BINDING_PREFLIGHT_MISMATCH")
    created_at = _timestamp(artifact.get("created_at"))
    expiry = _timestamp(artifact.get("expires_at"))
    if created_at >= expiry:
        raise BindingInstallerError("CHRONOS_BINDING_PREFLIGHT_EXPIRY_INVALID")
    if expiry <= datetime.now(UTC):
        raise BindingInstallerError("CHRONOS_BINDING_PREFLIGHT_EXPIRED")
    return artifact


def _set_secret(*, name: str, value: str, repository: str, environment: str) -> None:
    try:
        subprocess.run(  # nosec B603 B607 - fixed CLI and validated secret target.
            [
                "gh",
                "secret",
                "set",
                name,
                "--repo",
                repository,
                "--env",
                environment,
            ],
            input=value.encode("utf-8"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        raise BindingInstallerError(f"CHRONOS_BINDING_INSTALL_FAILED:{name}") from None


def install(
    *,
    preflight_artifact: Path,
    expected_main_sha: str,
    expected_preflight_run_id: str,
    report_path: Path,
    repository: str = EXPECTED_REPOSITORY,
    environment: str = EXPECTED_ENVIRONMENT,
) -> dict[str, Any]:
    if repository != EXPECTED_REPOSITORY or environment != EXPECTED_ENVIRONMENT:
        raise BindingInstallerError("CHRONOS_BINDING_TARGET_FORBIDDEN")
    attestation, attested_bytes = _attest_preflight_artifact(
        preflight_artifact,
        expected_main_sha=expected_main_sha,
        expected_preflight_run_id=expected_preflight_run_id,
    )
    artifact = _artifact_bytes(
        attested_bytes,
        expected_main_sha=expected_main_sha,
        expected_preflight_run_id=expected_preflight_run_id,
    )
    target = DirectPostgresTarget(
        host=str(artifact.get("database_host", "")),
        port=int(artifact.get("database_port", 0)),
        database=str(artifact.get("database_name", "")),
        username="bootstrap-placeholder",
        sslmode=str(artifact.get("sslmode", "")),
        channel_binding=str(artifact.get("channel_binding", "")),
    )
    current_main_sha = assert_current_main(
        repository=repository,
        main_sha=expected_main_sha,
    )
    installed: list[str] = []
    for secret_name, login in BINDINGS:
        password = secrets.token_urlsafe(48)
        value = build_scoped_database_url(target, username=login, password=password)
        _set_secret(
            name=secret_name,
            value=value,
            repository=repository,
            environment=environment,
        )
        installed.append(secret_name)
        del password, value
    nonce = secrets.token_hex(32)
    _set_secret(
        name="CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
        value=nonce,
        repository=repository,
        environment=environment,
    )
    installed.append("CHRONOS_CONTROL_PLANE_GENERATION_NONCE")
    report = {
        "schema_version": "chronos-runtime-binding-install-v1",
        "status": "INSTALLED",
        "repository": repository,
        "environment": environment,
        "expected_main_sha": artifact["main_sha"],
        "current_main_sha_observed": current_main_sha,
        "preflight_hash": artifact["preflight_hash"],
        "preflight_run_id": artifact["preflight_run_id"],
        "preflight_run_attempt": 1,
        "project_id": artifact["project_id"],
        "production_branch_id": artifact["production_branch_id"],
        "recovery_branch_id": artifact["recovery_branch_id"],
        "preflight_signature_algorithm": "HMAC-SHA256",
        "preflight_artifact_attestation": attestation,
        "database_host": target.host,
        "database_port": target.port,
        "database_name": target.database,
        "usernames": [login for _name, login in BINDINGS],
        "secrets_updated": installed,
        "generation_hash": generation_hash(nonce),
        "installed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "secret_values_observed": False,  # nosec B105 - boolean audit field.
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    nonce = ""
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-artifact", type=Path, required=True)
    parser.add_argument("--expected-main-sha", required=True)
    parser.add_argument("--expected-preflight-run-id", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = install(
            preflight_artifact=args.preflight_artifact,
            expected_main_sha=args.expected_main_sha,
            expected_preflight_run_id=args.expected_preflight_run_id,
            report_path=args.report,
        )
    except Exception as error:
        code = (
            str(error)
            if isinstance(error, BindingInstallerError)
            else ("CHRONOS_BINDING_INSTALL_FAILED")
        )
        print(code)
        raise SystemExit(1) from None
    print(f"CHRONOS_BINDINGS_INSTALLED:{result['generation_hash']}")


if __name__ == "__main__":
    main()
