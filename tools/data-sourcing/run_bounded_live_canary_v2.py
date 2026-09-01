#!/usr/bin/env python3
"""Run one externally owner-authorized V2 item; this tool never creates authority."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import robin.capture as capture_package
from robin.capture import (
    LIVE_ALLOWED_SPORT_KEYS,
    ActivationEnvelopeV2,
    BoundedLiveCanaryExecutor,
    CaptureContractError,
    CaptureMode,
    CaptureStore,
    EnvironmentSecretReader,
    FixtureTargetSetV1,
    GitRepositoryStateReader,
    InternalRetentionPolicy,
    LiveGuardError,
    LivePlanV2,
    LiveStateStore,
    LiveStorageError,
    LiveTransportError,
    OwnerAuthorizationV2,
    ProviderNetworkBindingV1,
    ProviderRequestSpec,
    ReviewedOwnerAuthorizationVerifierV2,
    StrictHttpsTransportV2,
)
from robin.capture.contracts import canonical_json_bytes, strict_json_loads
from robin.capture.storage import (
    CaptureStorageError,
    _safe_read_bounded,
    capture_root_fingerprint,
    exclusive_local_directory_fingerprint,
    validate_capture_workspace,
    validate_exclusive_local_directory_identity,
)
from robin.capture.workspace_bootstrap import (
    WorkspaceBootstrapError,
    load_tracked_real_execution_mission_manifest_v1,
)

_MAXIMUM_CONTROL_ARTIFACT_BYTES = 1_048_576


def _load_json(path: Path) -> Any:
    unresolved = path.absolute()
    validate_capture_workspace(unresolved.parent)
    return strict_json_loads(
        _safe_read_bounded(
            unresolved,
            maximum_bytes=_MAXIMUM_CONTROL_ARTIFACT_BYTES,
        )
    )


def _directories_overlap(left: Path, right: Path) -> bool:
    left_text = os.path.normcase(os.path.abspath(os.fspath(left)))
    right_text = os.path.normcase(os.path.abspath(os.fspath(right)))
    try:
        common = os.path.normcase(os.path.commonpath((left_text, right_text)))
    except ValueError:
        return False
    return common in {left_text, right_text}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Execute exactly one externally owner-authorized V2 item. The Git path is "
            "read only from OwnerAuthorizationV2; provider fixture IDs are learned later."
        )
    )
    parser.add_argument("--mode", required=True, choices=["LIVE_CANARY"])
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--control-temp-root", type=Path, required=True)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--mission-manifest", type=Path, required=True)
    parser.add_argument("--review-candidate", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--activation", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--item-id", required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--fixture-target-set", type=Path, required=True)
    parser.add_argument("--provider-network-binding", type=Path, required=True)
    parser.add_argument("--maximum-response-bytes", type=int, default=1_048_576)
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    try:
        if arguments.maximum_response_bytes <= 0:
            raise LiveGuardError("LIVE_PAYLOAD_LIMIT_INVALID")
        repository_root = validate_exclusive_local_directory_identity(arguments.repository_root)
        control_temp_root = validate_exclusive_local_directory_identity(
            validate_capture_workspace(arguments.control_temp_root)
        )
        capture_root = validate_capture_workspace(arguments.capture_root.absolute())
        roots = (repository_root, control_temp_root, capture_root)
        if any(
            _directories_overlap(left, right)
            for index, left in enumerate(roots)
            for right in roots[index + 1 :]
        ):
            raise LiveGuardError("LIVE_RUNTIME_ROOT_OVERLAP")
        expected_script = repository_root / "tools/data-sourcing/run_bounded_live_canary_v2.py"
        expected_package = repository_root / "src/robin/capture/__init__.py"
        if any(
            os.path.normcase(os.path.abspath(os.fspath(actual)))
            != os.path.normcase(os.path.abspath(os.fspath(expected)))
            for actual, expected in (
                (Path(__file__), expected_script),
                (Path(capture_package.__file__), expected_package),
            )
        ):
            raise LiveGuardError("LIVE_LOADED_CODE_REPOSITORY_MISMATCH")
        authorization = OwnerAuthorizationV2.model_validate(_load_json(arguments.authorization))
        review_candidate = OwnerAuthorizationV2.model_validate(
            _load_json(arguments.review_candidate)
        )
        verifier = ReviewedOwnerAuthorizationVerifierV2(review_candidate)
        verifier.verify(authorization)
        mission_manifest = load_tracked_real_execution_mission_manifest_v1(
            repository_root,
            arguments.mission_manifest,
        )
        activation = ActivationEnvelopeV2.model_validate(_load_json(arguments.activation))
        plan = LivePlanV2.model_validate(_load_json(arguments.plan))
        matching_items = tuple(item for item in plan.items if item.item_id == arguments.item_id)
        if len(matching_items) != 1:
            raise LiveGuardError("LIVE_PLAN_ITEM_SELECTION_INVALID")
        request = ProviderRequestSpec.model_validate(_load_json(arguments.request))
        targets = FixtureTargetSetV1.model_validate(_load_json(arguments.fixture_target_set))
        network_binding = ProviderNetworkBindingV1.model_validate(
            _load_json(arguments.provider_network_binding)
        )
        if (
            capture_root_fingerprint(capture_root)
            != authorization.approved_capture_root_fingerprint
            or exclusive_local_directory_fingerprint(repository_root)
            != authorization.approved_repository_root_fingerprint
            or exclusive_local_directory_fingerprint(control_temp_root)
            != authorization.approved_control_temp_root_fingerprint
        ):
            raise LiveGuardError("LIVE_OWNER_ATTESTED_ROOT_MISMATCH")
        preflight_now = datetime.now(UTC)
        BoundedLiveCanaryExecutor._validate_authority(
            authorization,
            activation,
            now=preflight_now,
            network_binding=network_binding,
        )
        BoundedLiveCanaryExecutor._validate_activation_ttl(
            activation,
            now=preflight_now,
        )
        if activation.sport_key not in LIVE_ALLOWED_SPORT_KEYS:
            raise LiveGuardError("LIVE_SPORT_FORBIDDEN")
        BoundedLiveCanaryExecutor._validate_plan(authorization, activation, plan)
        BoundedLiveCanaryExecutor._validate_item(
            activation,
            plan,
            matching_items[0],
            request,
            (),
            now=preflight_now,
            fixture_target_set=targets,
            network_binding=network_binding,
        )
        repository_reader = GitRepositoryStateReader(
            repository_root,
            git_executable=Path(authorization.approved_git_executable_path),
            git_executable_sha256=authorization.approved_git_executable_sha256,
            control_temp_root=control_temp_root,
            repository_root_fingerprint=authorization.approved_repository_root_fingerprint,
            control_temp_root_fingerprint=(authorization.approved_control_temp_root_fingerprint),
        )
        repository = repository_reader.read_v2(
            approved_git_executable_path=authorization.approved_git_executable_path,
            approved_git_executable_sha256=authorization.approved_git_executable_sha256,
        )
        if (
            repository.head_sha != authorization.authorized_main_sha
            or repository.main_sha != authorization.authorized_main_sha
        ):
            raise LiveGuardError("LIVE_REPOSITORY_SHA_MISMATCH")
        store = CaptureStore(
            capture_root,
            InternalRetentionPolicy(),
            approved_local_root=capture_root,
        )
        LiveStateStore(store).assert_capture_root(authorization.approved_capture_root_fingerprint)

        def now() -> datetime:
            return datetime.now(UTC)

        live_executor = BoundedLiveCanaryExecutor(
            capture_store=store,
            repository_state_reader=repository_reader,
            owner_authorization_verifier=verifier,
            secret_reader=EnvironmentSecretReader(),
            transport=StrictHttpsTransportV2(clock=now),
            clock=now,
            maximum_payload_bytes=arguments.maximum_response_bytes,
        )
        receipt = live_executor.execute_v2(
            mode=CaptureMode(arguments.mode),
            authorization=authorization,
            activation=activation,
            plan=plan,
            item=matching_items[0],
            request=request,
            fixture_target_set=targets,
            provider_network_binding=network_binding,
            mission_manifest=mission_manifest,
            mission_manifest_repository_root=repository_root,
            mission_manifest_path=arguments.mission_manifest,
            review_candidate=review_candidate,
        )
    except (
        CaptureContractError,
        CaptureStorageError,
        LiveGuardError,
        LiveStorageError,
        LiveTransportError,
        WorkspaceBootstrapError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        code = getattr(error, "code", "LIVE_CANARY_INPUT_OR_EXECUTION_INVALID")
        print(f"LIVE_CANARY_FAILED:{code}", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(canonical_json_bytes(receipt.model_dump(mode="json")) + b"\n")
    return 0 if receipt.terminal_disposition.value == "SUCCESS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
