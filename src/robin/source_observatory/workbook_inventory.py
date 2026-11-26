"""Complete local workbook references; importing never grants collection authority."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

from .candidate_registry import safe_link

PROFILE_SHEETS = {"Catalogue", "Profils FR"}
URL_COLUMNS = {
    "Catalogue": "G",
    "Profils FR": "F",
    "Plateformes": "G",
    "Pilote L1": "G",
    "Sujets et archives": "E",
    "Hors pilote": "D",
    "Dépôts": "D",
    "Réservoirs": "D",
}
APPROVED_INDEX_SHA256 = "0a4cfac9f560bbc2317ca19d5ccf790695b0b14ea4bfd4a352e6be11d4befcb5"


def build_inventory(
    source: dict[str, Any],
    workbook_sha: str,
    extraction_sha: str,
    formula_links: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    if not all(re.fullmatch("[a-f0-9]{64}", h) for h in (workbook_sha, extraction_sha)):
        raise ValueError("source hashes required")
    records = []
    headers: dict[str, dict[str, Any]] = {}
    parts = {f"xl/worksheets/sheet{i}.xml": name for i, name in enumerate(source, 1)}
    formula_targets = {}
    for item in formula_links or []:
        key = (parts[item["part"]], item["cell"])
        if key in formula_targets:
            raise ValueError("duplicate formula target")
        formula_targets[key] = item["target"]
    for sheet, content in source.items():
        if not isinstance(content.get("rows"), list):
            raise ValueError("invalid sheet")
        headers[sheet] = {}
        for entry in content["rows"]:
            number = entry["row"]
            fields = {re.sub(r"\d+$", "", k): v for k, v in entry["cells"].items()}
            header_number = 5 if sheet == "Repères" else 4
            if number == header_number:
                headers[sheet] = fields
            if number <= header_number:
                continue
            url = fields.get(URL_COLUMNS.get(sheet, ""), "")
            try:
                link = safe_link(url) if url else None
            except (TypeError, ValueError):
                link = None
            if link is None:
                target = formula_targets.get((sheet, f"{URL_COLUMNS.get(sheet, '')}{number}"))
                try:
                    link = safe_link(target) if target else None
                except (TypeError, ValueError):
                    link = None
            row_id = "workbook:" + sha256(f"{sheet}\0{number}".encode()).hexdigest()
            legacy_id = "catalogue:" + sha256(link.encode()).hexdigest() if link else None
            label = (
                fields.get("B") if sheet in {"Pilote L1", "Sujets et archives"} else fields.get("A")
            )
            records.append(
                {
                    "recordId": row_id,
                    "candidateId": legacy_id,
                    "sheet": sheet,
                    "row": number,
                    "label": label or f"Ligne {number}",
                    "platform": fields.get("B", "") if sheet in PROFILE_SHEETS else "",
                    "kind": fields.get("C", "")
                    if sheet == "Catalogue"
                    else ("profil historique" if sheet == "Profils FR" else sheet),
                    "sourceUrl": link,
                    "documentaryLinkRejected": bool(url and not link),
                    "historicalLevel": fields.get("D") if sheet == "Catalogue" else None,
                    "historicalL1": fields.get("E") if sheet == "Catalogue" else None,
                    "collectionEnabled": False,
                    "status": "documentary_unverified",
                    "fields": fields,
                }
            )
    addresses = {r["sourceUrl"] for r in records if r["sheet"] in PROFILE_SHEETS and r["sourceUrl"]}
    return {
        "schemaVersion": "robin-workbook-inventory-v1",
        "workbookSha256": workbook_sha,
        "extractionSha256": extraction_sha,
        "headers": headers,
        "records": records,
        "addressCount": len(addresses),
        "profileRows": sum(r["sheet"] in PROFILE_SHEETS for r in records),
        "claimId": "DATA.SOURCE_OBSERVATORY.WORKBOOK.COMPLETE.20261120",
    }


def load_inventory(
    directory: Path, *, expected_sha256: str, filename: str = "index.json"
) -> dict[str, Any]:
    if filename not in {"index.json", "index-v2.json"}:
        raise ValueError("invalid index name")
    path = directory / filename
    if path.stat().st_size > 64_000_000:
        raise ValueError("index too large")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("index hash mismatch")
    data: dict[str, Any] = json.loads(raw)
    if data["schemaVersion"] != "robin-workbook-inventory-v1":
        raise ValueError("index schema mismatch")
    return data


def query_inventory(
    data: dict[str, Any],
    *,
    q: str = "",
    sheet: str = "",
    platform: str = "",
    page: int = 0,
    limit: int = 25,
    record_id: str = "",
) -> dict[str, Any]:
    if (
        len(q) > 120
        or len(platform) > 160
        or len(record_id) > 100
        or not 0 <= page <= 10000
        or not 1 <= limit <= 50
        or (sheet and sheet not in data["headers"])
    ):
        raise ValueError("invalid catalogue query")
    needle = q.strip().casefold()
    rows = [
        r
        for r in data["records"]
        if (
            r["recordId"] == record_id
            if record_id
            else (r["sheet"] == sheet if sheet else r["sheet"] in PROFILE_SHEETS)
        )
        and (not platform or r["platform"] == platform)
        and (not needle or needle in " ".join(str(v) for v in r["fields"].values()).casefold())
    ]
    result = []
    for row in rows[page * limit : (page + 1) * limit]:
        result.append({k: v for k, v in row.items() if record_id or k != "fields"})
    return {
        "status": "ok",
        "schemaVersion": data["schemaVersion"],
        "records": result,
        "total": len(rows),
        "addressCount": data["addressCount"],
        "profileRows": data["profileRows"],
        "referenceRows": len(data["records"]),
        "page": page,
        "limit": limit,
        "sheets": list(data["headers"]),
        "platforms": sorted({r["platform"] for r in data["records"] if r["platform"]}),
        "headers": data["headers"].get(rows[0]["sheet"], {}) if record_id and rows else {},
        "receipt": {
            "claimId": data["claimId"],
            "workbookSha256": data["workbookSha256"],
            "extractionSha256": data["extractionSha256"],
        },
    }
