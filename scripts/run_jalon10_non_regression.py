"""Replay the three frozen Jalon 10 R3 witnesses without provider I/O."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from robin.hypothesis_evidence.non_regression import run_non_regression


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _paths_alias(left: Path, right: Path) -> bool:
    if left.resolve() == right.resolve():
        return True
    try:
        return left.samefile(right)
    except OSError:
        return False


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=_path, default=repo_root)
    parser.add_argument(
        "--evidence-root",
        type=_path,
        default=repo_root / "artifacts/hypothesis-evidence",
    )
    parser.add_argument(
        "--campaign-root",
        type=_path,
        default=repo_root / ".ci/hypothesis-j10",
    )
    parser.add_argument(
        "--output-root",
        type=_path,
        default=repo_root / "artifacts/r3-jalon10-non-regression",
    )
    parser.add_argument(
        "--report",
        type=_path,
        help="Generated compact report; defaults under the ignored output root.",
    )
    parser.add_argument("--verify-report", type=_path)
    args = parser.parse_args()

    resolved_repo = args.repo_root.resolve()
    resolved_output = args.output_root.resolve()
    artifact_root = resolved_repo / "artifacts"
    output_is_in_repo = resolved_output == resolved_repo or resolved_repo in resolved_output.parents
    output_is_in_artifacts = (
        resolved_output == artifact_root or artifact_root in resolved_output.parents
    )
    if output_is_in_repo and not output_is_in_artifacts:
        raise SystemExit("DETAILED_OUTPUT_MUST_REMAIN_UNDER_IGNORED_ARTIFACTS")
    report_path = args.report or (resolved_output / "compact-report.json")
    verify_report = args.verify_report
    if verify_report is not None and _paths_alias(report_path, verify_report):
        raise SystemExit("GENERATED_REPORT_MUST_NOT_OVERWRITE_REFERENCE")

    report = run_non_regression(
        repo_root=resolved_repo,
        evidence_root=args.evidence_root,
        campaign_root=args.campaign_root,
        output_root=resolved_output,
        report_path=report_path,
    )
    if verify_report is not None:
        generated = report_path.read_bytes().replace(b"\r\n", b"\n")
        expected = verify_report.read_bytes().replace(b"\r\n", b"\n")
        if generated != expected:
            raise SystemExit("TRACKED_R3_REPORT_DRIFT")
    external_effects = report.get("external_effects")
    if not isinstance(external_effects, dict):
        raise SystemExit("R3_EXTERNAL_EFFECTS_MISSING")
    print(
        json.dumps(
            {
                "equivalence_status": report["equivalence_status"],
                "rows_compared": report["rows_compared"],
                "rule_count": report["rule_count"],
                "scientific_verdict": report["scientific_verdict"],
                "provider_http_requests_new": external_effects.get("provider_http_requests_new"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
