"""Local documentary candidates, separate from every admitted prediction."""

from __future__ import annotations

import csv
import ipaddress
import json
import re
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .connectors import canonical


def safe_link(value: str) -> str:
    p = urlsplit(value)
    if (
        p.scheme not in {"http", "https"}
        or not p.hostname
        or p.username
        or p.password
        or len(value) > 2000
        or any(ord(c) <= 32 for c in value)
        or p.hostname.lower() in {"localhost", "localhost.localdomain"}
        or p.port not in {None, 80, 443}
    ):
        raise ValueError("invalid public documentary link")
    try:
        address = ipaddress.ip_address(p.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("private documentary link")
    if any(
        re.search(r"token|secret|password|api.?key|session|authorization|^sid$", k, re.I)
        for k, _ in parse_qsl(p.query)
    ):
        raise ValueError("credential-like documentary link")
    return value


def validate_rows(rows: list[dict[str, Any]], expected_count: int) -> None:
    if len(rows) != expected_count or len({r["id"] for r in rows}) != len(rows):
        raise ValueError("candidate count/identity mismatch")
    for r in rows:
        if r["collectionEnabled"] is not False or r["status"] != "pending_qualification":
            raise ValueError("documentary import cannot activate collection")
        if r["id"] != "catalogue:" + sha256(safe_link(r["sourceUrl"]).encode()).hexdigest():
            raise ValueError("candidate URL identity mismatch")
        safe_link(r["evidenceUrl"])
        if r["declaredLastDate"] is not None:
            date.fromisoformat(r["declaredLastDate"])
        if (
            not r["label"]
            or not r["platform"]
            or r["origin"]["sheet"] != "Catalogue"
            or not isinstance(r["origin"]["row"], int)
            or r["origin"]["row"] < 5
        ):
            raise ValueError("candidate provenance missing")


def import_candidates(
    source: Path, directory: Path, *, source_workbook_sha256: str, expected_count: int = 317
) -> dict[str, Any]:
    if not re.fullmatch(r"[a-f0-9]{64}", source_workbook_sha256):
        raise ValueError("workbook SHA256 required")
    rows = []
    with source.open(encoding="utf-8-sig", newline="") as stream:
        for r in csv.DictReader(stream):
            if (
                r["collection_enabled"] != "false"
                or r["qualification_status"] != "UNVERIFIED_FROM_WORKBOOK"
                or r["historical_lot"] != "A"
                or r["l1_flag_reported"] != "Oui"
            ):
                raise ValueError("only inactive historical A-L1 candidates may be imported")
            rows.append(
                dict(
                    id=r["candidate_id"],
                    label=r["name"],
                    platform=r["platform"],
                    sourceUrl=r["source_url"],
                    evidenceUrl=r["evidence_url"],
                    declaredLastDate=r["declared_last_date"] or None,
                    origin={
                        "sheet": r["source_sheet"],
                        "row": int(r["source_row"]),
                        "workbookSha256": source_workbook_sha256,
                    },
                    historicalLabel="A · Ligue 1 (inventaire historique)",
                    status="pending_qualification",
                    collectionEnabled=False,
                )
            )
    validate_rows(rows, expected_count)
    raw = canonical(rows) + b"\n"
    receipt = dict(
        schemaVersion="robin-candidate-registry-v1",
        count=len(rows),
        platformCount=len({r["platform"] for r in rows}),
        datedCount=sum(r["declaredLastDate"] is not None for r in rows),
        registrySha256=sha256(raw).hexdigest(),
        csvSha256=sha256(source.read_bytes()).hexdigest(),
        sourceWorkbookSha256=source_workbook_sha256,
        claimId="DATA.SOURCE_OBSERVATORY.CANDIDATES317.20261119",
    )
    directory.mkdir(parents=True, exist_ok=True)
    for filename, value in [("registry.json", raw), ("receipt.json", canonical(receipt) + b"\n")]:
        path = directory / filename
        if path.exists():
            if path.read_bytes() != value:
                raise ValueError("immutable candidate import differs")
        else:
            with path.open("xb") as out:
                out.write(value)
    return receipt


def load_registry(directory: Path, *, expected_count: int = 317) -> dict[str, Any]:
    raw = (directory / "registry.json").read_bytes()
    receipt = json.loads((directory / "receipt.json").read_bytes())
    if (
        receipt["schemaVersion"] != "robin-candidate-registry-v1"
        or receipt["claimId"] != "DATA.SOURCE_OBSERVATORY.CANDIDATES317.20261119"
    ):
        raise ValueError("candidate provenance schema mismatch")
    if expected_count == 317:
        reference = {
            "sourceWorkbookSha256": "c6b15829bb11e40d3145bf25b6cce8a7066de6105897d2b48dc4a74ba9286622",
            "csvSha256": "4954d3333996243334cbd22b99e4ba2420bb63f99206ab85fa4dbb8713674fe4",
            "registrySha256": "74def990602b5d2bf1b2a030827967e8d155af664ed9016769cf81b4cdd236ce",
        }
        if any(receipt[k] != v for k, v in reference.items()):
            raise ValueError("unapproved candidate registry version")
    if len(raw) > 2_000_000 or sha256(raw).hexdigest() != receipt["registrySha256"]:
        raise ValueError("candidate registry hash mismatch")
    rows: list[dict[str, Any]] = json.loads(raw)
    validate_rows(rows, expected_count)
    if any(r["origin"]["workbookSha256"] != receipt["sourceWorkbookSha256"] for r in rows):
        raise ValueError("candidate workbook provenance mismatch")
    if (
        receipt["count"] != len(rows)
        or receipt["platformCount"] != len({r["platform"] for r in rows})
        or receipt["datedCount"] != sum(r["declaredLastDate"] is not None for r in rows)
    ):
        raise ValueError("candidate receipt totals mismatch")
    return dict(
        status="ok",
        schemaVersion=receipt["schemaVersion"],
        candidates=rows,
        count=len(rows),
        platformCount=receipt["platformCount"],
        datedCount=receipt["datedCount"],
        enabledCount=0,
        receipt=receipt,
    )
