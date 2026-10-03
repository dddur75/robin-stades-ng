#!/usr/bin/env python3
"""Execute the owner-authorized real-data result mission."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

_RUNTIME_SOURCE = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_RUNTIME_SOURCE))

from robin.capture.live_transport import (  # noqa: E402
    EnvironmentSecretReader,
    LiveTransportError,
    StrictHttpsTransport,
)
from robin.capture.real_data_result import (  # noqa: E402
    MISSION_ID,
    ResultConfig,
    ResultError,
    run_real_data_result,
)
from robin.capture.reprise_collecte import resolve_provider_once  # noqa: E402
from robin.prospective_observatory.chronos_r2 import (  # noqa: E402
    ChronosR2ConditionalStore,
    ChronosR2Error,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the bounded Robin real-data mission")
    parser.add_argument("--execute", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=int, default=120)
    return parser


def _required(environment: dict[str, str], name: str) -> str:
    value = environment.get(name, "")
    if not value:
        raise ResultError("RESULT_GITHUB_CONTEXT_MISSING")
    return value


def _failure_stage(code: str) -> str:
    if code.startswith("RESULT_DNS_"):
        return "DNS_RESOLUTION"
    if code.startswith("RESULT_R2_"):
        return "R2_CONFIGURATION"
    if code.startswith("RESULT_PROVIDER_SECRET_"):
        return "PROVIDER_SECRET"
    if code.startswith("RESULT_GITHUB_"):
        return "GITHUB_CONTEXT"
    if code.startswith("RESULT_MANIFEST_") or code == "RESULT_MISSION_EXPIRED":
        return "MISSION_AUTHORITY"
    return "RESULT_RUNTIME"


def _emit_failure_diagnostic(code: str, error: BaseException) -> None:
    transport_diagnostic = error.diagnostic if isinstance(error, LiveTransportError) else None
    result_diagnostic = error.diagnostic if isinstance(error, ResultError) else None
    error_number = getattr(error, "errno", None)
    if not isinstance(error_number, int) or isinstance(error_number, bool):
        error_number = None
    stage = _failure_stage(code)
    exception_class = type(error).__name__
    http_status: int | None = None
    if transport_diagnostic is not None:
        stage = transport_diagnostic.stage
        exception_class = transport_diagnostic.exception_class
        error_number = transport_diagnostic.errno
        http_status = transport_diagnostic.http_status
    elif result_diagnostic is not None:
        diagnostic_stage = result_diagnostic.get("stage")
        diagnostic_class = result_diagnostic.get("exception_class")
        diagnostic_errno = result_diagnostic.get("errno")
        diagnostic_status = result_diagnostic.get("http_status")
        if isinstance(diagnostic_stage, str):
            stage = diagnostic_stage
        if isinstance(diagnostic_class, str):
            exception_class = diagnostic_class
        if isinstance(diagnostic_errno, int) and not isinstance(diagnostic_errno, bool):
            error_number = diagnostic_errno
        if isinstance(diagnostic_status, int) and not isinstance(diagnostic_status, bool):
            http_status = diagnostic_status
    print(code, file=sys.stderr)
    print(
        json.dumps(
            {
                "stage": stage,
                "code": code,
                "exception_class": exception_class,
                "errno": error_number,
                "http_status": http_status,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    environment = dict(os.environ)
    try:
        if arguments.execute != MISSION_ID:
            raise ResultError("RESULT_EXECUTION_TOKEN_INVALID")
        if (
            environment.get("GITHUB_REPOSITORY") != "dddur75/robin-stades-ng"
            or environment.get("GITHUB_REF") != "refs/heads/main"
            or environment.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        ):
            raise ResultError("RESULT_GITHUB_CONTEXT_INVALID")

        def clock() -> datetime:
            return datetime.now(UTC)

        config = ResultConfig(
            manifest_path=arguments.manifest,
            output_directory=arguments.output_directory,
            repository_sha=_required(environment, "GITHUB_SHA"),
            github_run_id=_required(environment, "GITHUB_RUN_ID"),
            github_run_attempt=int(_required(environment, "GITHUB_RUN_ATTEMPT")),
            interval_seconds=arguments.interval_seconds,
            safety_environment=environment,
        )
        store = ChronosR2ConditionalStore.from_environment(environment)
        receipt = run_real_data_result(
            config,
            store=store,
            transport_factory=lambda active_clock: StrictHttpsTransport(clock=active_clock),
            secret_reader=EnvironmentSecretReader(environment),
            resolver=lambda: resolve_provider_once(clock=clock),
            clock=clock,
        )
    except ChronosR2Error as error:
        _emit_failure_diagnostic("RESULT_R2_CONFIGURATION_INVALID", error)
        return 2
    except (ResultError, ValueError) as error:
        code = error.code if isinstance(error, ResultError) else "RESULT_CONFIGURATION_INVALID"
        _emit_failure_diagnostic(code, error)
        return 2
    except Exception as error:
        _emit_failure_diagnostic("RESULT_UNEXPECTED_FAILURE", error)
        return 3
    print(json.dumps(receipt, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return (
        0
        if receipt.get("status") in {"REAL_DATA_COMPLETE", "REAL_DATA_PARTIAL"}
        and receipt.get("terminal_safety_status") == "PASS"
        else 4
    )


if __name__ == "__main__":
    raise SystemExit(main())
