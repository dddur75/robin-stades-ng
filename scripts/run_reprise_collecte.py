#!/usr/bin/env python3
"""Execute the single owner-authorized reprise-collecte pilot."""

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
    StrictHttpsTransport,
)
from robin.capture.reprise_collecte import (  # noqa: E402
    MISSION_ID,
    PilotConfig,
    PilotError,
    resolve_provider_once,
    run_reprise_collecte,
)
from robin.prospective_observatory.chronos_r2 import (  # noqa: E402
    ChronosR2ConditionalStore,
    ChronosR2Error,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the bounded reprise-collecte pilot")
    parser.add_argument("--execute", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=int, default=120)
    return parser


def _required(environment: dict[str, str], name: str) -> str:
    value = environment.get(name, "")
    if not value:
        raise PilotError("REPRISE_GITHUB_CONTEXT_MISSING")
    return value


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    environment = dict(os.environ)
    try:
        if arguments.execute != MISSION_ID:
            raise PilotError("REPRISE_EXECUTION_TOKEN_INVALID")
        if (
            environment.get("GITHUB_REPOSITORY") != "dddur75/robin-stades-ng"
            or environment.get("GITHUB_REF") != "refs/heads/main"
            or environment.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        ):
            raise PilotError("REPRISE_GITHUB_CONTEXT_INVALID")

        def clock() -> datetime:
            return datetime.now(UTC)

        config = PilotConfig(
            manifest_path=arguments.manifest,
            output_directory=arguments.output_directory,
            repository_sha=_required(environment, "GITHUB_SHA"),
            github_run_id=_required(environment, "GITHUB_RUN_ID"),
            github_run_attempt=int(_required(environment, "GITHUB_RUN_ATTEMPT")),
            interval_seconds=arguments.interval_seconds,
            safety_environment=environment,
        )
        store = ChronosR2ConditionalStore.from_environment(environment)
        receipt = run_reprise_collecte(
            config,
            store=store,
            transport_factory=lambda active_clock: StrictHttpsTransport(clock=active_clock),
            secret_reader=EnvironmentSecretReader(environment),
            resolver=lambda: resolve_provider_once(clock=clock),
            clock=clock,
        )
    except ChronosR2Error:
        print("REPRISE_R2_CONFIGURATION_INVALID", file=sys.stderr)
        return 2
    except (PilotError, ValueError):
        error = sys.exc_info()[1]
        code = error.code if isinstance(error, PilotError) else "REPRISE_CONFIGURATION_INVALID"
        print(code, file=sys.stderr)
        return 2
    except Exception:
        print("REPRISE_UNEXPECTED_FAILURE", file=sys.stderr)
        return 3
    print(json.dumps(receipt, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 4 if receipt.get("status") == "PARTIEL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
