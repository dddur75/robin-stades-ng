from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def test_schema_and_all_scientific_invariants_pass(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    builder["validate_artifacts"](artifacts)


def test_exact_report_set_and_committed_bytes(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    report_root = Path(__file__).resolve().parents[2] / "reports" / "hypothesis-lab"
    expected_names = tuple(sorted(builder["REPORT_FILENAMES"]))
    assert tuple(sorted(path.name for path in report_root.glob("*.json"))) == expected_names
    for filename, document in artifacts.items():
        actual = (report_root / filename).read_bytes().replace(b"\r\n", b"\n")
        assert actual == builder["render_json"](document)


def test_write_and_check_round_trip(
    tmp_path: Path, builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    output_dir = tmp_path / "hypothesis-lab"
    builder["write_artifacts"](artifacts, output_dir)
    builder["check_artifacts"](artifacts, output_dir)
    assert tuple(sorted(path.name for path in output_dir.glob("*.json"))) == tuple(
        sorted(builder["REPORT_FILENAMES"])
    )


def test_source_order_does_not_change_any_artifact(builder: dict[str, Any]) -> None:
    records = builder["_source_records"]()
    normal = builder["build_artifacts"](records)
    reversed_source = builder["build_artifacts"](tuple(reversed(records)))
    assert reversed_source == normal


def test_python_hash_seed_does_not_change_rendered_bytes(
    tmp_path: Path, builder: dict[str, Any]
) -> None:
    builder_path = Path(builder["__file__"])
    output_dirs = [tmp_path / "seed-1", tmp_path / "seed-987"]
    for seed, output_dir in zip(("1", "987"), output_dirs, strict=True):
        environment = os.environ.copy()
        environment.update({"PYTHONHASHSEED": seed, "PYTHONDONTWRITEBYTECODE": "1"})
        subprocess.run(
            [sys.executable, str(builder_path), "--write", "--output-dir", str(output_dir)],
            check=True,
            env=environment,
        )
    first = {path.name: path.read_bytes() for path in output_dirs[0].glob("*.json")}
    second = {path.name: path.read_bytes() for path in output_dirs[1].glob("*.json")}
    assert first == second


def test_counts_and_status_labels(artifacts: dict[str, dict[str, Any]]) -> None:
    universe = artifacts["hypothesis-universe-v1.json"]
    deduplication = artifacts["hypothesis-deduplication-v1.json"]
    families = artifacts["hypothesis-family-map-v1.json"]
    experiments = artifacts["first-25-experiment-protocols-v1.json"]
    controls = artifacts["negative-control-plan-v1.json"]

    assert 80 <= len(universe["hypotheses"]) <= 150
    assert len(universe["hypotheses"]) == len(deduplication["clusters"])
    assert len(deduplication["candidates"]) == 336
    assert len(families["families"]) == 8
    assert experiments["portfolio_size"] == 25
    assert controls["control_count"] == 9
    for document in artifacts.values():
        assert document["status_labels"] == [
            "EXPLORATORY",
            "UNVALIDATED",
            "NO_PROMOTION",
            "NO_BET",
        ]
        assert all(value == 0 for value in document["external_effects"].values())
