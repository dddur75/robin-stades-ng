from scripts.historical_deep_workflow_outcome import workflow_outcome


def test_provider_stop_is_fail_closed_but_bounded_slices_resume() -> None:
    assert workflow_outcome({"status": "COMPLETE"}) == ("COMPLETE", False)
    assert workflow_outcome({"status": "PARTIAL", "result": {}}) == (
        "PARTIAL",
        False,
    )
    assert workflow_outcome(
        {
            "status": "PARTIAL",
            "result": {"reason": "JOB_PROVIDER_CALL_LIMIT_REACHED"},
        }
    ) == ("PARTIAL", False)
    assert workflow_outcome(
        {
            "status": "PARTIAL",
            "result": {"reason": "PROVIDER_PROTECTED_RESERVE_REACHED"},
        }
    ) == ("PARTIAL", True)
    assert workflow_outcome({"status": "BLOCKED_PROVIDER"}) == (
        "BLOCKED_PROVIDER",
        True,
    )
    assert workflow_outcome({"status": "UNKNOWN"}) == ("UNKNOWN", True)
