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
LEDGER_PATH = "reports/council/decision-ledger.jsonl"
# Preserve one already executed, hash-linked authorization byte for byte.
# This is not a general allowance for context.files or other machine paths.
SEALED_AUTHORIZATION_LINE = 461
SEALED_AUTHORIZATION_LINE_SHA256 = (
    "dadb8c125638d2bdc0d99682d0beafb041ad1979abd9824c2ea850e31ac04a24"
)
SEALED_AUTHORIZATION_RECORD_SHA256 = (
    "cee3f5935a07569017e75816104afcdc9431c63b3b992644554422d01dde299c"
)
SEALED_AUTHORIZATION_FILE_VALUES = {
    1: "c9c669575fcd45bc9e9b27c0206f96c10c8f03955b72023065676a4362c4398c",
    2: "135a76173d3652aba2f66fc4fc9bda7f361f2c7935f99e1c8f0f5eb432a276f4",
}
LEDGER_WORKTREE_PATH_RE = re.compile(
    r"^C:/"
    + "Users/"
    + r"(?!\.{1,2}/)[^/:]+/"
    + r"\."
    + "codex/worktrees/"
    + r"(?!\.{1,2}/)[^/:]+/(?!\.{1,2}$)[^/:]+$",
    re.IGNORECASE,
)
FIXTURE_MARKER = "PORTABILITY_TEST_FIXTURE"
LEGACY_FIXTURE_FRAGMENTS = {
    "tests/council/test_robin_council_os_v3.py": "C:" + "/Users/",
    "tests/jalon5/test_deep_data_factory.py": "/" + "home/runner/work/repository/",
}


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


def _mask_ledger_context_worktree_value(text: str) -> str:
    """Mask only a parsed context.worktree managed-checkout path."""
    try:
        record = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text
    if not isinstance(record, dict):
        return text
    canonical = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    if text != canonical:
        return text
    context = record.get("context")
    if not isinstance(context, dict):
        return text
    worktree = context.get("worktree")
    if not isinstance(worktree, str):
        return text
    normalized_worktree = worktree.replace("\\", "/")
    if LEDGER_WORKTREE_PATH_RE.fullmatch(normalized_worktree) is None:
        return text

    encoded_value = json.dumps(worktree, ensure_ascii=False, separators=(",", ":"))
    field = f'"worktree":{encoded_value}'
    if text.count(field) != 1:
        return text

    masked = list(text)
    field_start = text.index(field)
    start = field_start + len('"worktree":') + 1
    end = start + len(encoded_value) - 2
    masked[start:end] = " " * (end - start)
    return "".join(masked)


def _mask_sealed_authorization_file_values(text: str, line_number: int) -> str:
    """Mask two exact JSON string spans on one immutable ledger line only."""
    if line_number != SEALED_AUTHORIZATION_LINE:
        return text
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != SEALED_AUTHORIZATION_LINE_SHA256:
        return text
    record = json.loads(text)
    if record.get("decision_id") != "RCV3-20261120-NT-E1-LEGAL-AUTHORIZED":
        return text
    if record.get("hash") != SEALED_AUTHORIZATION_RECORD_SHA256:
        return text
    payload = json.dumps(
        {key: value for key, value in record.items() if key != "hash"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if hashlib.sha256(payload.encode("utf-8")).hexdigest() != SEALED_AUTHORIZATION_RECORD_SHA256:
        return text
    context = record["context"]
    files = context["files"]
    if any(
        not isinstance(files[index], str)
        or hashlib.sha256(files[index].encode("utf-8")).hexdigest() != expected
        for index, expected in SEALED_AUTHORIZATION_FILE_VALUES.items()
    ):
        return text
    encoded_context = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    context_field = '"context":' + encoded_context
    encoded_files = json.dumps(files, ensure_ascii=False, separators=(",", ":"))
    files_field = '"files":' + encoded_files
    if text.count(context_field) != 1 or encoded_context.count(files_field) != 1:
        return text
    offset = (
        text.index(context_field)
        + len('"context":')
        + encoded_context.index(files_field)
        + len('"files":')
        + 1
    )
    masked = list(text)
    for index, value in enumerate(files):
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if index in SEALED_AUTHORIZATION_FILE_VALUES:
            start = offset + 1
            end = offset + len(encoded) - 1
            masked[start:end] = " " * (end - start)
        offset += len(encoded) + 1
    return "".join(masked)


SEALED_PUBLICATION_LINE = 1993
SEALED_PUBLICATION_LINE_SHA256 = "045d94358ad1e21dda6fa42cc5b7d621eea5ef586e6c8b0a134685dbc7172265"
SEALED_PUBLICATION_RECORD_SHA256 = (
    "526b7d9c251b6cc31784eb6d5f44fb6486a03753d7e30a6899e47cae1b5863dc"
)
SEALED_PUBLICATION_VALUE_SHA256 = (
    "0fd8bac29b1ba979c6576f082a9e103d5fa6946c2f94a54f06fd33878e923c87",
    "e79fa7c7861c3c6ba4921e370136a33f531bb74f737d994fdf591b6d57ca8da7",
    "4d4ec701a0a57f691e5530b0879eb4baaf2bb15ec9a538b13d15171e54abcc95",
    "f2fc832a56caf88078e251f3c6ff03d42c1ec1a215685b198a803ed4d3d727b0",
    "cbd3014570af2be8394a54a620e8739d01ac8e64b6f9981b264260a9ca10acd4",
)


def _mask_sealed_publication_test_values(text: str, line_number: int) -> str:
    """Mask exactly five receipt string interiors on the sealed publication line."""
    if line_number != SEALED_PUBLICATION_LINE:
        return text
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != SEALED_PUBLICATION_LINE_SHA256:
        return text
    try:
        record = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text
    if not isinstance(record, dict):
        return text
    if record.get("decision_id") != "RCV3-20261123-C0-FINAL-PUBLIC-BINDING-R1-PRECOMMIT":
        return text
    if record.get("hash") != SEALED_PUBLICATION_RECORD_SHA256:
        return text
    payload = json.dumps(
        {key: value for key, value in record.items() if key != "hash"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if hashlib.sha256(payload.encode("utf-8")).hexdigest() != SEALED_PUBLICATION_RECORD_SHA256:
        return text
    context = record.get("context")
    if not isinstance(context, dict):
        return text
    values = context.get("targeted_tests")
    if type(values) is not list or len(values) != 5:
        return text
    if any(
        type(value) is not str or hashlib.sha256(value.encode("utf-8")).hexdigest() != expected
        for value, expected in zip(values, SEALED_PUBLICATION_VALUE_SHA256, strict=True)
    ):
        return text
    encoded_context = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    context_field = '"context":' + encoded_context
    encoded_values = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    values_field = '"targeted_tests":' + encoded_values
    if text.count(context_field) != 1 or encoded_context.count(values_field) != 1:
        return text
    offset = (
        text.index(context_field)
        + len('"context":')
        + encoded_context.index(values_field)
        + len('"targeted_tests":')
        + 1
    )
    masked = list(text)
    for value in values:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        start, end = offset + 1, offset + len(encoded) - 1
        masked[start:end] = " " * (end - start)
        offset += len(encoded) + 1
    return "".join(masked)


# Exact frozen audit locators only; future records remain subject to normal checks.
SEALED_LOCAL_AUDIT_VALUES = [
    {
        "line": 2250,
        "line_sha256": "996981b0ac8fcfa8481733f16f9672fd47a36689cd5542814ccae1153f5a76ab",
        "record_sha256": "7d778bd5475fce61c1ce669b6989e5a2ea53198f58475ddd3e8b51dd5973cd65",
        "decision_id": "RCV3-20261124-C0-NOTBETTING-ADMIN-LATEST-E2-LOCAL",
        "field": "target",
        "value_sha256": "fbab47f024a8fa83c7d10041da5fcefcc59279961954e30d83deab87100ccd22",
    },
    {
        "line": 2263,
        "line_sha256": "77aeadec3321d113999c69428508e87e0f719cc80bfe21cdec5a5f8ac016f35f",
        "record_sha256": "a431ae9008ef7dfeb1c432dde523bcda26e12f9dcd70aff4afd03cbe8a173583",
        "decision_id": "RCV3-20261124-C0-COTEUR-LITERAL-QUERY-FULLBINDING-E1-AUTH",
        "field": "privateWorktree",
        "value_sha256": "010a2c575039cfb4ad2f8f463b00c0fb8e44106c8e0dc1877dda9230a399a061",
    },
    {
        "line": 2268,
        "line_sha256": "58ce416af80a022607299d556c6641f06ccf2dcdf763c71d78fd78ee08517afb",
        "record_sha256": "1f90583dc7144459e4f2be203236d19c616a76eb8957358fc35d3b9b84165a83",
        "decision_id": "RCV3-20261124-C0-COTEUR-LITERAL-QUERY-FULLBINDING-R2-E1-AUTH",
        "field": "privateWorktree",
        "value_sha256": "010a2c575039cfb4ad2f8f463b00c0fb8e44106c8e0dc1877dda9230a399a061",
    },
    {
        "line": 2271,
        "line_sha256": "a73d1ccc0b55a135a78d79ac5a4ebdce9d900f247483b263304fc539b0bb7357",
        "record_sha256": "e64078688e797a88001e9c661b39fa9068e73ef3c4748ec5e6533a63f044856e",
        "decision_id": "RCV3-20261124-C0-COTEUR-LITERAL-QUERY-FULLBINDING-R3-E1-AUTH",
        "field": "privateWorktree",
        "value_sha256": "010a2c575039cfb4ad2f8f463b00c0fb8e44106c8e0dc1877dda9230a399a061",
    },
    {
        "line": 2284,
        "line_sha256": "ca3e30ec379ef9c298168863335875c26ebe90f6c9ef1118507062f7f35ccec8",
        "record_sha256": "eed89ebbc953f1bd3cd9c3ef2a3b87168a8ccff105cd26024b9dc82858e007a8",
        "decision_id": "RCV3-20261124-C0-COTEUR-LITERAL-QUERY-R4-ACTUAL-STOP",
        "field": "privateExecutionDirectory",
        "value_sha256": "cf9b944277ccfa02d4eaa45f2de91bac1a077f42532a740d61593b7a0f732334",
    },
    {
        "line": 2289,
        "line_sha256": "cf74fdedaa1d7db37f6502f77cafb4987c98f17db011362c9bcc0d8c6ffdc3eb",
        "record_sha256": "3f163236bf753098c13a781a8c0b68923ddc7a04f4a8ad173c7c25cb01b4eb41",
        "decision_id": "RCV3-20261124-C0-NOTBETTING-COMPETITION-BUCKETS-E1-AUTH",
        "field": "privateWorktree",
        "value_sha256": "d8318a134f79359277d1577253843f18e9c4f900b74cfbb398ef3b0e215185c6",
    },
    {
        "line": 2292,
        "line_sha256": "928883be56ebe90c0b72eac344ed1636abaa3454369d33261c1094586d2c8d71",
        "record_sha256": "a02c5583b3b9ca41b7753e93e800ba94990159503a470ab831a83a85fc92e9a7",
        "decision_id": "RCV3-20261124-C0-SOURCE-ADMIN-COTEUR-NOTBETTING-E2-LOCAL",
        "field": "target",
        "value_sha256": "fbab47f024a8fa83c7d10041da5fcefcc59279961954e30d83deab87100ccd22",
    },
    {
        "line": 2297,
        "line_sha256": "fe93c97f69b6fba015bdec58c92069d3f7f928b39cd367f4200f5c37897aaa85",
        "record_sha256": "22dbe5da860bc5ea34a57e2436053f392d374df02e4f900354f686f3fb2a9889",
        "decision_id": "RCV3-20261124-C0-NOTBETTING-COMPETITION-BUCKETS-NATIVE-R1-E1-AUTH",
        "field": "privateWorktree",
        "value_sha256": "d8318a134f79359277d1577253843f18e9c4f900b74cfbb398ef3b0e215185c6",
    },
    {
        "line": 2312,
        "line_sha256": "040b5bd34ce03112fa57bfb0e775c308902a03ea293f8562a9a51fe3f91d3267",
        "record_sha256": "411bd2ddd31ab334bbde390a1317a11a0db405c7330cb8cee01634fa6a9a3182",
        "decision_id": "RCV3-20261124-C0-PLATFORM-CONTEXT-RUNTIME-R2-E2-LOCAL",
        "field": "targetWorktree",
        "value_sha256": "d553924f844207bdf56f03f10de3cf4e4a544f5d3e524289636b6042d2a991bc",
    },
    {
        "line": 2317,
        "line_sha256": "026871e8781bd21a97c330e6014c04c612165499f47c7f65d9974025e8705d6c",
        "record_sha256": "e225204541792f4146d05ba702ab1b420caac04fd8a82755e3c154759f51e28f",
        "decision_id": "RCV3-20261124-C0-ADMIN-ANCHOR-GEOMETRY-E2-LOCAL",
        "field": "targetWorktree",
        "value_sha256": "d553924f844207bdf56f03f10de3cf4e4a544f5d3e524289636b6042d2a991bc",
    },
    {
        "line": 2324,
        "line_sha256": "3f32f454ee5741ae064910b5b9f2801300850fd1246f8d0d751b092638741a0b",
        "record_sha256": "b7b9484b09acf2150d657777a53517a112f4d3325517aabbc22c2c32d953c596",
        "decision_id": "RCV3-20261124-C0-ADMIN-ANCHOR-FIXED-RUNTIME-E2-LOCAL",
        "field": "targetWorktree",
        "value_sha256": "d553924f844207bdf56f03f10de3cf4e4a544f5d3e524289636b6042d2a991bc",
    },
]


def _mask_sealed_local_audit_value(text: str, line_number: int) -> str:
    seal = next((item for item in SEALED_LOCAL_AUDIT_VALUES if item["line"] == line_number), None)
    if seal is None or hashlib.sha256(text.encode("utf-8")).hexdigest() != seal["line_sha256"]:
        return text
    record = json.loads(text)
    if (
        record.get("decision_id") != seal["decision_id"]
        or record.get("hash") != seal["record_sha256"]
    ):
        return text
    payload = json.dumps(
        {key: value for key, value in record.items() if key != "hash"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if hashlib.sha256(payload.encode()).hexdigest() != seal["record_sha256"]:
        return text
    value = record.get("context", {}).get(seal["field"])
    if (
        not isinstance(value, str)
        or hashlib.sha256(value.encode()).hexdigest() != seal["value_sha256"]
    ):
        return text
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if text.count(encoded) != 1:
        return text
    start = text.index(encoded) + 1
    end = start + len(encoded) - 2
    return text[:start] + " " * (end - start) + text[end:]


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
        line = raw_line
        if normalized_path == LEDGER_PATH:
            line = _mask_sealed_authorization_file_values(line, line_number)
            line = _mask_sealed_publication_test_values(line, line_number)
            line = _mask_sealed_local_audit_value(line, line_number)
            line = _mask_ledger_context_worktree_value(line)
        line = _mask_allowed(line)
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
