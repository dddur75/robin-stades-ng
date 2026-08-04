from __future__ import annotations

import io
import time

import pytest

from scripts.run_historical_deep_segmented_replay import _progress_heartbeat


def test_progress_heartbeat_emits_data_free_liveness() -> None:
    output = io.StringIO()
    deadline = time.monotonic() + 1.0

    with _progress_heartbeat(
        "SEGMENTED_REPLAY_REDUCER_HEARTBEAT",
        interval_seconds=0.005,
        stream=output,
    ):
        while not output.getvalue() and time.monotonic() < deadline:
            time.sleep(0.005)

    heartbeat = output.getvalue()
    assert heartbeat.startswith(
        "SEGMENTED_REPLAY_REDUCER_HEARTBEAT:sequence=1:elapsed_seconds="
    )
    assert "payload" not in heartbeat
    assert "receipt" not in heartbeat


def test_progress_heartbeat_rejects_non_positive_interval() -> None:
    with pytest.raises(ValueError, match="PROGRESS_HEARTBEAT_INTERVAL_INVALID"):
        with _progress_heartbeat("HEARTBEAT", interval_seconds=0):
            pass
