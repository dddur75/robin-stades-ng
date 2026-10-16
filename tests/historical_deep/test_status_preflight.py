from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import requests
import yaml

from scripts.check_api_football_status import check_status


@pytest.mark.parametrize("outcome", [200, 401, 403, 429, 500, "timeout", "expired"])
def test_preflight_is_one_request_and_never_leaks_provider_body(monkeypatch, outcome):
    calls = []

    class Response:
        status_code = outcome if isinstance(outcome, int) else 200
        headers = {}

        def json(self):
            return {"response": {
                "account": {"email": "private@example.test"},
                "subscription": {"plan": "Mega", "active": True, "end": (
                    datetime.now(UTC) + timedelta(days=-1 if outcome == "expired" else 30)
                ).isoformat()},
                "requests": {"limit_day": 150000, "current": 100},
            }}

    def get(url, **kwargs):
        calls.append((url, kwargs))
        if outcome == "timeout":
            raise requests.Timeout("sensitive-key")
        return Response()

    monkeypatch.setattr(requests, "get", get)
    receipt = check_status({"API_FOOTBALL_KEY": "sensitive-key"})
    assert len(calls) == receipt["status_calls"] == 1
    assert calls[0][0].endswith("/status")
    assert calls[0][1]["allow_redirects"] is False
    assert receipt["lineup_calls"] == 0
    assert receipt["status"] == ("PASS" if outcome == 200 else "BLOCKED_PROVIDER")
    assert "sensitive-key" not in str(receipt)
    assert "private@example.test" not in str(receipt)


def test_missing_key_and_rerun_make_no_request(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("provider request forbidden")

    monkeypatch.setattr(requests, "get", forbidden)
    for environment in ({}, {"API_FOOTBALL_KEY": "key", "GITHUB_RUN_ATTEMPT": "2"}):
        receipt = check_status(environment)
        assert receipt["status_calls"] == 0
        assert receipt["status"] == "BLOCKED_PROVIDER"


def test_workflow_preflight_is_exclusive_of_harvest():
    path = Path(".github/workflows/71-historical-deep-fixture-bundle-harvest.yml")
    workflow = yaml.safe_load(path.read_text())
    steps = workflow["jobs"]["fixture-bundles"]["steps"]
    preflight = next(step for step in steps if "check_api_football_status.py" in step.get("run", ""))
    harvest = next(step for step in steps if "run_historical_deep_harvest.py" in step.get("run", ""))
    assert preflight["if"] == "inputs.status_only"
    assert preflight["env"] == {"API_FOOTBALL_KEY": "${{ secrets.API_FOOTBALL_KEY }}"}
    assert harvest["if"] == "!inputs.status_only"
    assert workflow["jobs"]["fixture-bundles"]["env"]["STORAGE_PAUSED"] == "true"
