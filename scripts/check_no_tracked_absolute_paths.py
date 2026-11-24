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



# Exact frozen historical string spans; future records receive no exception.
SEALED_CURRENT_AUDIT_SPANS = [
    {
        "line": 2468,
        "line_sha256": "098381a7c1e018912e6c348545322f3494bffe429333fa796f4d4e348d6d16e5",
        "record_sha256": "66480f2853c5414649590278ce29f491faa4d55aad45c4224d994d3825c6bae4",
        "decision_id": "RCV3-20261124-C0-OLBG-FIRST-OPAQUE-R2-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2470,
        "line_sha256": "54ba3beb6faec8d3e14503656ca808af5145379be02ba469a9e8cb3ecc6491aa",
        "record_sha256": "1782c8ec7980372429553b0472a11b7b574dc77617c4493d8185466b32c52dc6",
        "decision_id": "RCV3-20261124-C0-OLBG-FIRST-OPAQUE-R2-QUALITY-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2471,
        "line_sha256": "ca987c3ce5c48e84ddb2ffd3a14346288f30e8f26ad61d294c06f1e2ad65b730",
        "record_sha256": "04a6a76630579daa7c24d07695072456a6aafda5984608cbb7a433f749775382",
        "decision_id": "RCV3-20261124-C0-OLBG-FIRST-OPAQUE-R2-QUALITY-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2482,
        "line_sha256": "486d06311da9dd96a8c47d1fad2083d289ddc5ac223eac790d5ca6619799ec31",
        "record_sha256": "bad7e8fb3ce63796bb32b0881814e4da5f17321301ee830a97a5900863eb7240",
        "decision_id": "RCV3-20261124-C0-OLBG-OBSERVER-COMPLETE-COLLECTOR-CALLER-R2-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2484,
        "line_sha256": "0c12c415a85b5910bb77508fa75f59ef3f05144fbaeac84797b9bb547d4cdd1a",
        "record_sha256": "0309f8bf9af9c995e7d8d04642478cebc763af55ca19335fcddf6d78ae7c6f57",
        "decision_id": "RCV3-20261124-C0-OLBG-FIRST-REFUSAL-NATIVE-BINDING-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2490,
        "line_sha256": "7ff6ea4e399fbfb1da542b6240341ca76faaec35fe88add93b1554fcf31f2882",
        "record_sha256": "4525d19d2982bfac0db5b65e9c82e4f56b1af9dd2a6305e2fe36bd0b4221aa09",
        "decision_id": "RCV3-20261124-C0-OLBG-UNQUALIFIED-OBSERVATION-BUILDER-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "files",
                    0
                ],
                "value_sha256": "800e2ead8105332a8b22e5d11ccb85f6e2f98ef1e19e62d338d7f308d9360f15"
            },
            {
                "path": [
                    "context",
                    "files",
                    1
                ],
                "value_sha256": "42a5e324acf69627a89377a9ed657c8a9879d03967d4f7f7f9226e47395d19a8"
            }
        ]
    },
    {
        "line": 2491,
        "line_sha256": "57c3f15cc8220a61b9f9ae02b1cd5a9e038b9615747125bed1b9016c41e85247",
        "record_sha256": "7daf6419f9b8c89be7bfec9779d291b58561cde89ff79e96de68087123c897fa",
        "decision_id": "RCV3-20261124-C0-OLBG-PENDING-ZERO-ELIGIBLE-CAPTURE-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2492,
        "line_sha256": "5c2799df8d1beafc94af16efe332ca76998c0e0133d6dc9a218196493b72b5e5",
        "record_sha256": "112ed47cb4a7e10c8cbf8060d20102358d88472f287dec6cd57d5bf979f0f799",
        "decision_id": "RCV3-20261124-C0-OLBG-PENDING-ZERO-ELIGIBLE-CAPTURE-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2494,
        "line_sha256": "ca614a00bc6afe59eed9d11df7c78a05f683b4f4e747bac24e6e5011f917d336",
        "record_sha256": "13fe72b1e774f48d724f945f297ad0f93c79f63afedb9d2a65af7194151312c4",
        "decision_id": "RCV3-20261124-C0-OLBG-PENDING-APP-READER-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2495,
        "line_sha256": "5b039bb35a4b79f70624e403209e9326de1dfecd108f8c866e1f76258206addb",
        "record_sha256": "d35cd9884b35192aa5dfbd4c751babebed6e06d7477524338409f1e34f568d52",
        "decision_id": "RCV3-20261124-C0-OLBG-PENDING-FILESYSTEM-POLICY-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2496,
        "line_sha256": "5e125ff002adcfe61342fe287476c3338c341975671e995d95e4516d4b60aa48",
        "record_sha256": "f2055c78300661f91a435e667efeb3113ca73bf932ec31343e608f6d5810a384",
        "decision_id": "RCV3-20261124-C0-OLBG-PENDING-FILESYSTEM-POLICY-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2497,
        "line_sha256": "47f4f96a2406c6ece3d864783d039b991d024979576a050a89007a5f07a97b24",
        "record_sha256": "43955477428008d82a04aa7d08138e6fa4dcb2473253e38f8efcc50345b4348e",
        "decision_id": "RCV3-20261124-C0-OLBG-PENDING-FILESYSTEM-POLICY-POSITIVE-R2-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2499,
        "line_sha256": "e0f3add67c08e5692ff7c9b7d9658b49784d7316b4f67a5d1e840c07e0871659",
        "record_sha256": "995f25f3610fc0f982f769f888f8026fe32262298c3e5b99d8de767e4c853e83",
        "decision_id": "RCV3-20261124-C0-OLBG-PENDING-FILESYSTEM-POLICY-POSITIVE-R2-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2500,
        "line_sha256": "4a3d915acd5836a97fae4060134963ac40ecfee2924ef7cd2ab772cd13649a22",
        "record_sha256": "f0b42a0a8657b02fe71a9cb43c35089e9e1ce8ef20786c5301f2ee057f458e7d",
        "decision_id": "RCV3-20261124-C0-OLBG-PENDING-CATALOGUE-PANEL-WIRING-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2501,
        "line_sha256": "a502e1e2a023091d6f7054e0020cc7a0b38def7deb0b01b9373dfa89b826f800",
        "record_sha256": "c1ea189e4f941e0c525679b14d0d1919479783869013b9e80fe157d075835fac",
        "decision_id": "RCV3-20261124-C0-OLBG-PENDING-WHOLE-NATIVE-BINDING-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2502,
        "line_sha256": "0a4ed5943c6e30015a1aebe7a5a6904cfe4b586f20e77667166b1e0ed8f6b010",
        "record_sha256": "72204eeaab155539ad7671022ce6321af2f9478cc30b50076f9936c51437f080",
        "decision_id": "RCV3-20261124-C0-OLBG-PENDING-WHOLE-NATIVE-BINDING-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2505,
        "line_sha256": "6fe063a5240f7cc3ca556c15d32866e85cb5bc31a771afd92f13d5f384933707",
        "record_sha256": "26e71d1b7589eb0b4178eb94ccf5022c08032739f5ab4ee659897a8d8acd999c",
        "decision_id": "RCV3-20261124-C0-OLBG-PENDING-WHOLE-NATIVE-BINDING-R2-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2506,
        "line_sha256": "d865ac6c15a2c201df0895b092bfc4d9aeb25fabf9845b92d9c72ae02fd27046",
        "record_sha256": "095ec065b08365be7c8bd14ed3090960de7a4f6780659b339ff95b5ac7359305",
        "decision_id": "RCV3-20261124-C0-UEFA-24NOV-OFFICIAL-CALENDAR-DOCUMENTARY-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2507,
        "line_sha256": "e6a48b60da6d671df8534d08f67502e8f6c07f510987c03927cb0b4dba27919e",
        "record_sha256": "c00a2aa2d98dc764f9d01ee90d0c56258025053ff090d38467c0f48c6d570340",
        "decision_id": "RCV3-20261124-C0-OLBG-PENDING-WHOLE-NATIVE-BINDING-R2-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2511,
        "line_sha256": "1f6251af827084b8f829918661c9158b89e53a03284db5a87adda4f78527f5db",
        "record_sha256": "47f91c3a4fee2dcb9cdfcb22122ae7846a2c4b9835f46b7dd5727bc3c2f116e5",
        "decision_id": "RCV3-20261124-C0-OLBG-PENDING-WHOLE-NATIVE-BINDING-R2-E2-ACTUAL-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2512,
        "line_sha256": "028a6245cc57d2d086bc664a1b96c78cdec3c87711bfe365c734070cd7966f36",
        "record_sha256": "eff9dc75da504e1d6e1f0066d7023d00bc74f2991ea83cff3048b41a074c6fda",
        "decision_id": "RCV3-20261124-C0-OLBG-REAL-PENDING-LOCAL-SNAPSHOT-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2513,
        "line_sha256": "10f7ede6a859aa04ad3d0d5d40eeddf3bfbd12232df3ca28b771cdb63838ab79",
        "record_sha256": "d12c79388b8734e996a678b9abcae0ccf0dee2c429f7288afc7d0364d2c03eab",
        "decision_id": "RCV3-20261124-C0-OLBG-REAL-PENDING-LOCAL-SNAPSHOT-E1-REFUSAL",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2514,
        "line_sha256": "d99bd09b6b1b9ed7bec81ee57e65394bfa87f6a7248cca27ab742dd7da0170a2",
        "record_sha256": "1796e330061586d6d72dcb0ca5cff26be68fb637c8d48b0fb77458a722a9d8da",
        "decision_id": "RCV3-20261124-C0-UEFA-24NOV-PRIMARY-SEARCH-ARCHITECTURE-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2515,
        "line_sha256": "9409c0c4565df9a33b041cd08a814a14032633f9d611f1f84636b8aa5727f735",
        "record_sha256": "d9ce797f7bf5844b3cefd73745991103ed061d55a391b354b8f30def6bfaa8cd",
        "decision_id": "RCV3-20261124-C0-UEFA-24NOV-PRIMARY-SEARCH-ARCHITECTURE-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2516,
        "line_sha256": "ce4d6c11be2da16f37adf54b0de154164a83c9d7e8dc971a6052c17337fa4fed",
        "record_sha256": "f0a65ba14b73f66a1f7568338ceae34c50a086b2cb5d16e61f6ca73dd6e23f81",
        "decision_id": "RCV3-20261124-C0-OLBG-REVIEWED-PENDING-CANDIDATE-HELPER-R2-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2517,
        "line_sha256": "2658af9579799914356f87ddf79490e94406e9a11bb44a989b7e36a6dc294c19",
        "record_sha256": "2eed59c8a11cd9bad8f4ffef7554740bf1073d1b902577b39b09f506841cfc09",
        "decision_id": "RCV3-20261124-C0-OLBG-RETAINED-UEFA-LITERAL-CONTEXT-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2518,
        "line_sha256": "c2a7d905cc74108bb764a487a43871a6a184db860d0c13a26230df79847efdb0",
        "record_sha256": "37d420944adc3c5053686f32bd427b44510e9c710356882cc311a1082e5f4d5d",
        "decision_id": "RCV3-20261124-C0-OLBG-RETAINED-UEFA-LITERAL-CONTEXT-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2519,
        "line_sha256": "7edc8996969a19c40418fbe715f84648dc83660e06a5370b8f545e34e80744d0",
        "record_sha256": "186730524d43eb0a40b7e4ef26b45801b8da715fbec8c0169be0cfb3f5f7fb72",
        "decision_id": "RCV3-20261124-C0-OLBG-REVIEWED-PENDING-CANDIDATE-HELPER-R2-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2520,
        "line_sha256": "0d949a26bc30b7c66d1798b573c3ff3a1d069901723d2c986715d2d49f0d0463",
        "record_sha256": "8e2f7253f0cb6ace4281221bcd4f9fe41d23f7ed21bc988fde12e08ca98d7797",
        "decision_id": "RCV3-20261124-C0-OLBG-EXACT-FICHE-APP-WIRING-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2521,
        "line_sha256": "5615a43247bbc8bcfdf896123b67e7d699c9022700c4945befc5207ad6785c55",
        "record_sha256": "0b4dd7be88e80dc26667b7c35f9ce7d4d983087f056ee8098f162b486c2e60d9",
        "decision_id": "RCV3-20261124-C0-OLBG-EXACT-FICHE-APP-WIRING-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2522,
        "line_sha256": "d6eb6c3207da00c48aea515c0633ca283e735a0c330d7f0f2b3033eb87460184",
        "record_sha256": "f75b7a5d7667228962a5ffe56e10b86c69f7e0b1c17fb84a90b1103c9587f83d",
        "decision_id": "RCV3-20261124-C0-OLBG-EXACT-FICHE-APP-WIRING-LOCAL-E2-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2523,
        "line_sha256": "8d91d81f3a6daa7bcf4711a28ba8ff63b5ea6da199e7aa247938b53b4a1a3b54",
        "record_sha256": "043af7a0a5739794142406de24519156a3f6e073e3054e8d040ecb7de2dd7d73",
        "decision_id": "RCV3-20261124-C0-OLBG-EXACT-FICHE-APP-WIRING-LOCAL-E2-FIRST-FAILURE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2524,
        "line_sha256": "25f551c1e426aadbc44448723456f0acc7734e896d85b15fae47a4547e5aeb6a",
        "record_sha256": "8d4892c2bfef83468a843bb6b21ae85079801f1a680fe1e1260129e7bc6886e0",
        "decision_id": "RCV3-20261124-C0-OLBG-APP-PREDICATE-AND-LOADER-FIX-R2-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2525,
        "line_sha256": "7c69c01f101abdc06433b0bb0a62b6ae8d8510b0ed53f7dff5ca326e19db105e",
        "record_sha256": "8d313722c2ddd52e47e2070c372e3b49a5c89fc7bbfd77fd828c1703906375ce",
        "decision_id": "RCV3-20261124-C0-OLBG-APP-PREDICATE-AND-LOADER-FIX-R2-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2526,
        "line_sha256": "4af53190997330157c0a96214edb42c97145ecf064f289e522e8490e76595b00",
        "record_sha256": "cad486a8181360b60d49f0cd1b9fc88e8c20269607b5c23002117f61ece58544",
        "decision_id": "RCV3-20261124-C0-OLBG-LOCAL-SERVER-RELOAD-AND-TWO-VIEW-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2527,
        "line_sha256": "831936bdfa838ef94d28a59c3b2a2495ac4ef18eae81c04877ae71cb1f30a231",
        "record_sha256": "3d6a6ff5f05332230d00456a003f782b0da01282b18304054e7f7c7ddabe7d5e",
        "decision_id": "RCV3-20261124-C0-OLBG-LOCAL-SERVER-RELOAD-AND-TWO-VIEW-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2528,
        "line_sha256": "478989eb030e7bb4c783b971ecaa54aec83b40a6ed022737dcbbeca6ba8a04c9",
        "record_sha256": "4a18408dd1b3deb9b18527e71188179bcbfe7f8d154f035f28e8b667f7598cb1",
        "decision_id": "RCV3-20261124-C0-OLBG-LOCAL-SERVER-RELOAD-AND-TWO-VIEW-LOCAL-E2-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2529,
        "line_sha256": "a15562bd92ddf312771b7c72d240a271b4246179f9766747fc73c5fd33da74f4",
        "record_sha256": "7f39a67ef04e7c351b2d2c96d2a03d4f8fe1877af7c031f1f27abb412c61b613",
        "decision_id": "RCV3-20261124-C0-OLBG-LOCAL-SERVER-RELOAD-AND-TWO-VIEW-E2-ORCHESTRATION-FAILURE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2530,
        "line_sha256": "30ea5e9d4e4dddb6b3df32dab223223c7132f660a16d9d6618e62b30f5327b5c",
        "record_sha256": "de4c0c3048d4ca84340c325e763dcb4e1b436706d7f429f99c571782a69ecf87",
        "decision_id": "RCV3-20261124-C0-OLBG-RUNNING-SERVER-READONLY-UI-RECETTE-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2531,
        "line_sha256": "711a5a2c9f2bf3f882724cab4858c2f4f68fbf4c6ffd1fcc04c93e56c25bf9a0",
        "record_sha256": "70c501f98c30babed0e3ea5440eb9bb50c24df8d8c6d0ca64df8c6e538939f5b",
        "decision_id": "RCV3-20261124-C0-OLBG-RUNNING-SERVER-READONLY-UI-RECETTE-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2532,
        "line_sha256": "330b1a7a17e0577b881220021c29c34ab43f89d4869d5953f3bc78ecf01dfc4a",
        "record_sha256": "696d0cac3380114b6a8e9a390c18a1e67f428eb3adc1fcb1942d5aa782300750",
        "decision_id": "RCV3-20261124-C0-OLBG-RUNNING-SERVER-READONLY-UI-RECETTE-LOCAL-E2-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2533,
        "line_sha256": "0c31528699e4284bc78216807fd403728d391c9e0b1eb5b9c860543017f321b8",
        "record_sha256": "ac648a4e9c0fc565aa0794cd17c2a856fccd93a7d236b2682d1050bdd6383ba2",
        "decision_id": "RCV3-20261124-C0-OLBG-RUNNING-SERVER-READONLY-UI-RECETTE-E2-ADMIN-FAILURE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2534,
        "line_sha256": "00b7027304c04911c36ae19fac203adf1c421e6aff82591f6561c658610fe35f",
        "record_sha256": "4d103d63a0859b9de254c9f8a390b53403a1bb09d8a54146ebc14a1b9a6f2e70",
        "decision_id": "RCV3-20261124-C0-OLBG-ADMIN-SINGLE-VIEW-CONSOLE-DIAGNOSTIC-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2535,
        "line_sha256": "92361527bf5a9737ba99b671654435cf9a830ebf389b100c8ccb1aa02721f5cf",
        "record_sha256": "34290197d301e569a04f8d6e681c46cd9b06f0dd1fa90a163bc58b72aad8ddda",
        "decision_id": "RCV3-20261124-C0-OLBG-ADMIN-SINGLE-VIEW-CONSOLE-DIAGNOSTIC-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2536,
        "line_sha256": "f99d1adb9a88cabc4c4c0cdb9252ebdb4933566b355da54afb7b189c884b9a64",
        "record_sha256": "8a6ab3c98222c508bcd5bcff57ebfcd8d2c1afee16c08d4a3d216efd6d0bcaac",
        "decision_id": "RCV3-20261124-C0-ROBIN-ORIGINAL-READ-ENVIRONMENT-RESTORATION-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2537,
        "line_sha256": "aed551c0b5538c1e31a51b77bc2e0273cb5ffaa2bffe1ab3db8bbfbbd8ea1922",
        "record_sha256": "353d5d014f6d37babbf34fe4c9ed1f25f0705814ce7316b3e0b0953f14ae5651",
        "decision_id": "RCV3-20261124-C0-ROBIN-ORIGINAL-READ-ENVIRONMENT-RESTORATION-E1-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2538,
        "line_sha256": "789a8ac101e787e34a51551a2a6702bf01941ff439f269679cb32f5a7a841aca",
        "record_sha256": "bd40c9fc2cc3462cf194a90915bafac651486807f5871ff50721226b0a9360a6",
        "decision_id": "RCV3-20261124-C0-ROBIN-ORIGINAL-READ-ENVIRONMENT-RESTORATION-LOCAL-E2-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2539,
        "line_sha256": "91bdb4112edb5b7e98b0cb2aae5ca007ca9e523cd3979bdbf1e0a3079d4a1bea",
        "record_sha256": "49ddfb34979cbfe5b5abc8942be2e236774a3cb6611ecc63ac78b9b144672c5b",
        "decision_id": "RCV3-20261124-C0-ROBIN-ORIGINAL-READ-ENVIRONMENT-RESTORATION-E2-ACTUAL-CLOSE",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2540,
        "line_sha256": "4557033680691a06407829ff4bb2c6d18725127b2ed22483b19727fec18f5639",
        "record_sha256": "f757fb4316e25f3eca369bbe47d83a48977a71061171992d236527452dd57b75",
        "decision_id": "RCV3-20261124-C0-OLBG-FICHE-ADMIN-PROJECTION-V39-R2-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2542,
        "line_sha256": "2d288c8b0314408419c6454626d5f67092528f1227d1cc68f33704ebd75e0789",
        "record_sha256": "0a2f9af250b3251380b68399b6ec95f33568764dc8b9c8459949f90d4ae3b268",
        "decision_id": "RCV3-20261124-C0-OLBG-FICHE-ADMIN-PROJECTION-V39-R3-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    },
    {
        "line": 2574,
        "line_sha256": "0e10775980e99afc3dde7cc62738dc1e85d62c79e31ea2327713b61d7bc24bb7",
        "record_sha256": "c9565d349886f7a101d7db41dd5ca0cfef33da53682f75e4542046e5c328acca",
        "decision_id": "RCV3-20261124-C0-OLBG-THREE-TELEGRAM-LOCAL-E1-AUTH",
        "fields": [
            {
                "path": [
                    "context",
                    "controllerWorktree"
                ],
                "value_sha256": "3eb729adf3c7387c33104cf3043ddaae4868a19136681c9c0d2016465b5f0849"
            }
        ]
    }
]


def _sealed_string_span(value, route: list, offset: int = 0) -> tuple[int, int]:
    """Locate one exact JSON path within a canonical serialization."""
    def encode(item):
        return json.dumps(item, ensure_ascii=False, separators=(",", ":"))

    if not route:
        if not isinstance(value, str):
            raise ValueError("SEALED_VALUE_NOT_STRING")
        return offset + 1, offset + len(encode(value)) - 1
    head, *tail = route
    cursor = offset + 1
    if isinstance(value, dict) and type(head) is str and head in value:
        for key, item in value.items():
            cursor += len(encode(key)) + 1
            if key == head:
                return _sealed_string_span(item, tail, cursor)
            cursor += len(encode(item)) + 1
    elif isinstance(value, list) and type(head) is int and 0 <= head < len(value):
        cursor += sum(len(encode(item)) + 1 for item in value[:head])
        return _sealed_string_span(value[head], tail, cursor)
    raise ValueError("SEALED_PATH_NOT_FOUND")


def _mask_sealed_current_audit_spans(text: str, line_number: int) -> str:
    """Mask frozen audit string interiors; never authorize a future record."""
    seal = next((item for item in SEALED_CURRENT_AUDIT_SPANS if item["line"] == line_number), None)
    if seal is None or hashlib.sha256(text.encode()).hexdigest() != seal["line_sha256"]:
        return text
    record = json.loads(text)
    if text != json.dumps(record, ensure_ascii=False, separators=(",", ":")):
        return text
    if record.get("decision_id") != seal["decision_id"]:
        return text
    payload = {key: value for key, value in record.items() if key != "hash"}
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if record.get("hash") != seal["record_sha256"] or digest != seal["record_sha256"]:
        return text
    spans = []
    for field in seal["fields"]:
        value = record
        try:
            for key in field["path"]:
                value = value[key]
            if not isinstance(value, str):
                return text
            if hashlib.sha256(value.encode()).hexdigest() != field["value_sha256"]:
                return text
            start, end = _sealed_string_span(record, field["path"])
        except (KeyError, IndexError, TypeError, ValueError):
            return text
        if not 0 <= start <= end <= len(text):
            return text
        spans.append((start, end))
    spans.sort()
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        return text
    masked = list(text)
    for start, end in spans:
        masked[start:end] = " " * (end - start)
    return "".join(masked)


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
            line = _mask_sealed_current_audit_spans(line, line_number)
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
