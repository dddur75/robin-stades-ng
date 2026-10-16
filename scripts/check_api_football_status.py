"""Mission 027: one /status request, sanitized receipt, no collection or storage."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import requests

from robin.historical_deep.provider import ApiFootballDeepClient


class StatusTransport:
    calls = 0

    def get(self, url: str, **kwargs) -> requests.Response:
        self.calls += 1
        return requests.get(url, allow_redirects=False, **kwargs)


def check_status(environment: Mapping[str, str]) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": "mission-027-status-public-receipt-v1",
        "status": "BLOCKED_PROVIDER",
        "status_calls": 0,
        "lineup_calls": 0,
        "checked_at": datetime.now(UTC).isoformat(),
        "run_id": environment.get("GITHUB_RUN_ID"),
        "code_revision": environment.get("GITHUB_SHA"),
    }
    if environment.get("GITHUB_RUN_ATTEMPT", "1") != "1":
        return {**receipt, "reason": "RERUN_FORBIDDEN_SINGLE_STATUS"}
    key = environment.get("API_FOOTBALL_KEY", "").strip()
    if not key:
        return {**receipt, "reason": "API_FOOTBALL_KEY_REQUIRED"}
    transport = StatusTransport()
    try:
        client = ApiFootballDeepClient(api_key=key, max_retries=0, transport=transport)
        status = client.get_status()
        if not status.is_fresh(datetime.now(UTC)):
            raise ValueError("EXPIRED_STATUS")
        receipt.update(
            status="PASS", daily_limit=status.daily_limit,
            quota_remaining=status.daily_remaining,
            subscription_end=status.subscription_end.isoformat(),
        )
    except Exception as error:
        # Never retain provider bodies, account fields, exception text or credentials.
        receipt["reason"] = type(error).__name__
    receipt["status_calls"] = transport.calls
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = check_status(os.environ)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return 0 if receipt["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
