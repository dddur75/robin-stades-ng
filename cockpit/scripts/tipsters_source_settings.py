"""Local source catalogue and versioned preparation settings. No network operations."""

import argparse
import csv
import io
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from robin.source_observatory.collector import PilotSource, _endpoint

ROOT = Path(__file__).resolve().parents[2]
EMPTY_REVISION = "0" * 64
HASH = re.compile(r"[0-9a-f]{64}")
MAX_SETTINGS_BYTES = 4_000_000
ADAPTERS = {"rss_atom", "html_public", "manual"}
CONFIG_FIELDS = {"endpoint", "adapter", "intervalMinutes", "requestsPerVisit", "notes"}


class ConflictError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def limited_read(path: Path, maximum: int = 4_000_000) -> bytes:
    with path.open("rb") as stream:
        content = stream.read(maximum + 1)
    if len(content) > maximum:
        raise ValueError("source settings exceed the local size limit")
    return content


def validate_config(config: Any, source: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict) or set(config) != CONFIG_FIELDS:
        raise ValueError("Les champs du paramétrage sont invalides.")
    endpoint = config["endpoint"]
    if not isinstance(endpoint, str) or not 1 <= len(endpoint) <= 1000:
        raise ValueError("L’adresse de collecte est invalide.")
    parsed, origin = urlsplit(endpoint), urlsplit(source["url"])
    if (parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username
            or parsed.password or parsed.fragment or any(ord(c) <= 32 for c in endpoint)
            or parsed.port not in (None, 443 if parsed.scheme == "https" else 80)
            or (origin.scheme == "https" and parsed.scheme != "https")
            or parsed.hostname.removeprefix("www.") != origin.hostname.removeprefix("www.")):
        raise ValueError("L’adresse doit rester sur le domaine public de cette source.")
    if any(re.search(r"token|key|secret|password|auth|session", key, flags=re.I)
           for key, _ in parse_qsl(parsed.query)):
        raise ValueError("L’adresse doit être publique et dépourvue d’identifiants d’accès.")
    if config["adapter"] not in ADAPTERS:
        raise ValueError("Le format de lecture est inconnu.")
    for name, minimum, maximum in [("intervalMinutes", 30, 1440), ("requestsPerVisit", 1, 10)]:
        if type(config[name]) is not int or not minimum <= config[name] <= maximum:
            raise ValueError("La cadence ou le plafond dépasse les limites de préparation.")
    notes = config["notes"]
    if (not isinstance(notes, str) or len(notes) > 2000
            or any(ord(c) < 32 and c not in "\n\t" for c in notes)):
        raise ValueError("La note doit contenir au plus 2 000 caractères de texte.")
    return {key: config[key] for key in sorted(CONFIG_FIELDS)}


def registry(path: Path) -> tuple[list[dict[str, Any]], str]:
    raw = limited_read(path, 2_000_000).replace(b"\r\n", b"\n")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    sources = []
    known: set[str] = set()
    for row in rows:
        identifier, state = row["source_id"], row["etat_connecteur"]
        if not re.fullmatch(r"SRC_\d{3}", identifier) or identifier in known:
            raise ValueError("Le registre contient des identifiants incohérents.")
        if state not in {"a_construire", "manuel", "bloque"}:
            raise ValueError("Le registre contient un état inconnu.")
        known.add(identifier)
        item = PilotSource(identifier, row["nom"], row["adresse"], state,
                           row["mode_acces"], row["cgu_connues"], row["competitions"],
                           row["categorie_audience"])
        endpoint, reason = (None, "registre_bloque") if state == "bloque" else _endpoint(item)
        feed = re.search(r"https?://[^\s)]+", item.access)
        adapter = "manual" if reason else "rss_atom" if feed and re.search(
            r"rss|atom", item.access, re.I) else "html_public"
        source = {
            "id": identifier, "name": row["nom"], "url": row["adresse"],
            "kind": row["type"], "language": row["langue"], "competitions": row["competitions"],
            "historicalState": state, "historicalCheckedAt": row["verifie_le"],
            "historicalAccess": row["mode_acces"], "historicalTerms": row["cgu_connues"],
            "limits": row["limites"], "audience": row["categorie_audience"],
            "historicalGate": reason or "revalidation_required", "includedInPilot": False,
        }
        source["defaults"] = validate_config({
            "endpoint": endpoint or row["adresse"], "adapter": adapter,
            "intervalMinutes": 360, "requestsPerVisit": 2, "notes": "",
        }, source)
        sources.append(source)
    if not sources:
        raise ValueError("Le registre des sources est vide.")
    return sources, sha256(raw).hexdigest()


def read_settings(path: Path, sources: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    previous = EMPTY_REVISION
    settings: dict[str, Any] = {}
    if not path.exists():
        return previous, settings
    raw = limited_read(path, MAX_SETTINGS_BYTES)
    if raw and not raw.endswith(b"\n"):
        raise ValueError("Le journal de préparation est incomplet. La sauvegarde est suspendue.")
    for line in raw.splitlines(keepends=True):
        record = json.loads(line)
        digest = record.pop("hash")
        if (set(record) != {"previousHash", "sourceId", "config", "savedAt", "kind"}
                or record["previousHash"] != previous or record["kind"] != "SOURCE_PREPARATION"
                or sha256(canonical(record)).hexdigest() != digest
                or canonical(record | {"hash": digest}) + b"\n" != line
                or record["sourceId"] not in sources):
            raise ValueError("Le journal de préparation ne passe pas le contrôle d’intégrité.")
        instant = datetime.fromisoformat(record["savedAt"])
        if instant.utcoffset() is None:
            raise ValueError("La date de préparation est invalide.")
        config = validate_config(record["config"], sources[record["sourceId"]])
        settings[record["sourceId"]] = {"config": config, "savedAt": record["savedAt"], "revision": digest}
        previous = digest
    return previous, settings


def catalogue(registry_path: Path, directory: Path) -> dict[str, Any]:
    sources, digest = registry(registry_path)
    revision, settings = read_settings(directory / "preparations.jsonl", {s["id"]: s for s in sources})
    counts = Counter(source["historicalState"] for source in sources)
    for source in sources:
        stored = settings.get(source["id"])
        source["config"] = stored["config"] if stored else source["defaults"]
        source["prepared"] = stored is not None
        source["savedAt"] = stored["savedAt"] if stored else None
    return {
        "status": "ok", "schemaVersion": "robin-tipsters-source-settings-v1",
        "revision": revision, "registrySha256": digest,
        "claimId": "ENG.SOURCE_OBSERVATORY.SOURCE_SETTINGS.20261118",
        "counts": dict(counts), "total": len(sources), "prepared": len(settings),
        "sources": sources,
        "pilotProvider": {"id": "FORECAST_RECORD_J12", "name": "Forecast Record",
                          "detailsHref": "/expert/admin-collecte", "requestsMax": 51},
    }


def save(registry_path: Path, directory: Path, payload: Any) -> dict[str, Any]:
    sources, _ = registry(registry_path)
    by_id = {source["id"]: source for source in sources}
    if (not isinstance(payload, dict) or set(payload) != {"sourceId", "expectedRevision", "config"}
            or not isinstance(payload["sourceId"], str) or payload["sourceId"] not in by_id
            or not isinstance(payload["expectedRevision"], str)
            or HASH.fullmatch(payload["expectedRevision"]) is None):
        raise ValueError("La source ou la révision du paramétrage est invalide.")
    config = validate_config(payload["config"], by_id[payload["sourceId"]])
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "preparations.lock"
    try:
        handle = lock.open("x")
    except FileExistsError:
        raise ConflictError("Une sauvegarde est déjà en cours. Rechargez la révision avant de réessayer.") from None
    try:
        with handle:
            head, _ = read_settings(directory / "preparations.jsonl", by_id)
            if head != payload["expectedRevision"]:
                raise ConflictError("Une autre fenêtre a modifié les réglages. Votre brouillon est conservé.")
            record = {"kind": "SOURCE_PREPARATION", "previousHash": head,
                      "sourceId": payload["sourceId"], "config": config,
                      "savedAt": datetime.now(timezone.utc).isoformat()}
            digest = sha256(canonical(record)).hexdigest()
            encoded = canonical(record | {"hash": digest}) + b"\n"
            journal = directory / "preparations.jsonl"
            current_size = journal.stat().st_size if journal.exists() else 0
            if current_size + len(encoded) > MAX_SETTINGS_BYTES:
                raise ValueError("Le journal de préparation a atteint sa limite locale.")
            with journal.open("ab") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        return {"status": "saved", "sourceId": payload["sourceId"], "revision": digest,
                "savedAt": record["savedAt"], "activation": "PREPARATION_ONLY"}
    finally:
        lock.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=ROOT / "data/source_observatory/pilot_sources.csv")
    parser.add_argument("--settings-directory", type=Path, required=True)
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    try:
        if args.update:
            raw = sys.stdin.buffer.read(16_385)
            if len(raw) > 16_384:
                raise ValueError("Le paramétrage dépasse la taille autorisée.")
            result = save(args.registry, args.settings_directory, json.loads(raw))
        else:
            result = catalogue(args.registry, args.settings_directory)
    except ConflictError as exc:
        result = {"status": "conflict", "message": str(exc)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        result = {"status": "invalid", "message": "Le registre ou les réglages locaux sont invalides. Vérifiez l’adresse, les bornes et l’intégrité du journal."}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
