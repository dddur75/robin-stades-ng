"""Reject machine-local absolute paths in tracked text files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

PLACEHOLDER_RE = re.compile(r"<(?:repo_root|workspace|temp_dir|home)>", re.IGNORECASE)
URL_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s<>\"']+", re.IGNORECASE)
WINDOWS_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"[A-Za-z]:[\\/](?![\\/])[^\\/\s\"'<>]+[\\/][^\s\"'<>]+"
    r"|\\\\[A-Za-z0-9._-]+[\\/][A-Za-z0-9$._-]+(?:[\\/][^\s\"'<>]+)?"
    r")"
)
UNIX_LOCAL_RE = re.compile(r"(?<![A-Za-z0-9])/(?:home|Users|mnt)/[^\s\"'<>]+")
LOCAL_MACHINE_NAMES = "|".join(("One" + "Drive", "App" + "Data", r"\." + "codex"))
LOCAL_SEGMENT_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?:{LOCAL_MACHINE_NAMES})[\\/][^\s\"'<>]+",
    re.IGNORECASE,
)
FIXTURE_MARKER = "PORTABILITY_TEST_FIXTURE"
LEGACY_FIXTURE_FRAGMENTS = {
    "tests/council/test_robin_council_os_v3.py": "C:" + "/Users/",
    "tests/jalon5/test_deep_data_factory.py": "/" + "home/runner/work/repository/",
}
_IMMUTABLE_LEDGER_PATH = "reports/council/decision-ledger.jsonl"
_IMMUTABLE_LEDGER_DECISION_ID = "RCV3-20260830-194"
_IMMUTABLE_LEDGER_RECORD_HASH = (
    "e0a497c717222220ab7e2e1a8dc17529a08acf96000682465da9f4d659d77ffe"
)
_IMMUTABLE_LEDGER_WORKTREE = "".join(
    (
        "C:",
        "/Users/",
        "ddura/",
        "One" + "Drive/",
        "Documents/",
        "Robin des stades V2 Worktrees/",
        "data-torrent-recovery-v2",
    )
)


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    value: str
    category: str


def _mask_allowed(text: str) -> str:
    masked = list(text)
    for pattern in (PLACEHOLDER_RE, URL_RE):
        for match in pattern.finditer(text):
            masked[match.start() : match.end()] = " " * (match.end() - match.start())
    return "".join(masked)


def _mask_immutable_ledger_worktree(text: str, *, path: str) -> str:
    """Mask one already-sealed local locator without permitting future ones."""

    if path.replace("\\", "/") != _IMMUTABLE_LEDGER_PATH:
        return text
    try:
        record = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text
    if not isinstance(record, dict):
        return text
    context = record.get("context")
    record_hash = record.get("hash")
    if (
        record.get("decision_id") != _IMMUTABLE_LEDGER_DECISION_ID
        or record_hash != _IMMUTABLE_LEDGER_RECORD_HASH
        or not isinstance(context, dict)
        or context.get("worktree") != _IMMUTABLE_LEDGER_WORKTREE
        or text.count(_IMMUTABLE_LEDGER_WORKTREE) != 1
    ):
        return text
    unsigned = {key: value for key, value in record.items() if key != "hash"}
    canonical = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != record_hash:
        return text
    return text.replace(
        _IMMUTABLE_LEDGER_WORKTREE,
        " " * len(_IMMUTABLE_LEDGER_WORKTREE),
        1,
    )


def find_forbidden_absolute_paths(
    text: str,
    *,
    path: str = "<memory>",
) -> list[Violation]:
    findings: list[Violation] = []
    normalized_path = path.replace("\\", "/")
    fixture_allowed = normalized_path.startswith("tests/")
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if fixture_allowed and FIXTURE_MARKER in raw_line:
            continue
        legacy_fixture = LEGACY_FIXTURE_FRAGMENTS.get(normalized_path)
        if legacy_fixture is not None and legacy_fixture in raw_line:
            continue
        line = _mask_allowed(
            _mask_immutable_ledger_worktree(raw_line, path=normalized_path)
        )
        for category, pattern in (
            ("WINDOWS_ABSOLUTE_PATH", WINDOWS_RE),
            ("UNIX_LOCAL_ABSOLUTE_PATH", UNIX_LOCAL_RE),
            ("LOCAL_MACHINE_SEGMENT", LOCAL_SEGMENT_RE),
        ):
            if normalized_path.endswith(".gitignore") and category == "LOCAL_MACHINE_SEGMENT":
                continue
            for match in pattern.finditer(line):
                findings.append(
                    Violation(
                        path=path,
                        line=line_number,
                        value=raw_line[match.start() : match.end()],
                        category=category,
                    )
                )
    return findings


def tracked_files(repo_root: Path) -> list[Path]:
    completed = subprocess.run(  # noqa: S603
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    return [
        repo_root / item.decode("utf-8", errors="strict")
        for item in completed.stdout.split(b"\0")
        if item
    ]


def scan_repository(repo_root: Path) -> list[Violation]:
    findings: list[Violation] = []
    for file_path in tracked_files(repo_root):
        try:
            payload = file_path.read_bytes()
        except OSError as exc:
            raise SystemExit(f"TRACKED_FILE_UNREADABLE:{file_path}") from exc
        if b"\0" in payload:
            continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue
        relative = file_path.relative_to(repo_root).as_posix()
        findings.extend(find_forbidden_absolute_paths(text, path=relative))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.repo_root.resolve()
    findings = scan_repository(root)
    if findings:
        for finding in findings:
            print(f"{finding.path}:{finding.line}: {finding.category}: {finding.value}")
        return 1
    print("TRACKED_ABSOLUTE_PATHS_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
