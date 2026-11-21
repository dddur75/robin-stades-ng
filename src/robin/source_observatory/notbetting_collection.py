"""Hash-anchored, source-literal NotBetting facts; no network or activation."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from .connectors import canonical
from .opaque_choices import merge_distinct_choices
from .recurring import instant

SOURCE_URL = "https://notbetting.com/en/tipsters-league/picks"
REPORT_NAME = "TIPSTERS-NOTBETTING-OPAQUE-DATA-20261121.json"
APPROVED_REPORT_SHA256 = "ba729d1d2517d4eabcde14965ea9cb1fb375b2bb7d0737b9040f3f50e15f7f41"
UUID = re.compile(r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}")
HASH = re.compile(r"[a-f0-9]{64}")


def _plain(value: Any, maximum: int = 160) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= maximum
        and not re.search(r"[\x00-\x1f]|https?://|[^\s@]+@[^\s@]+\.[^\s@]+", value)
    )


def build_choices(
    source: dict[str, Any],
    fixtures: list[dict[str, Any]],
    accepted_ids: list[str],
    *,
    parser_sha: str,
) -> list[dict[str, Any]]:
    if (
        source.get("sourceUrl") != SOURCE_URL
        or source["content"].get("status") != 200
        or len(accepted_ids) != 1
        or any(UUID.fullmatch(v) is None for v in accepted_ids)
        or HASH.fullmatch(parser_sha) is None
        or HASH.fullmatch(source["content"]["responseSha256"]) is None
        or not 0 < len(fixtures) <= 14
    ):
        raise ValueError("NotBetting exact admitted scope")
    content = source["content"]
    projection = content["projection"]
    rows = []
    for identifier in accepted_ids:
        records = [r for r in projection["records"] if r["nativeFields"].get("id") == identifier]
        comparisons = [r for r in source["targetComparison"] if r.get("id") == identifier]
        if (
            len(records) != 1
            or len(comparisons) != 1
            or identifier in projection["conflictingTargetIds"]
        ):
            raise ValueError("NotBetting record absent or conflicting")
        record, comparison = records[0], comparisons[0]
        fields, times = record["nativeFields"], record["nativeTemporalFields"]
        fingerprint = sha256(
            canonical(
                dict(fields=fields, linkedOwner=record["linkedOwner"], nativeTemporalFields=times)
            )
        ).hexdigest()
        ids = [
            fields[k]
            for k in (
                "tipsterId",
                "tipster.user.id",
                "tipster.user.tipster.id",
                "tipster.user.tipster.userId",
            )
        ]
        if (
            fingerprint != record["sourceRecordFingerprint"]
            or len(set(ids)) != 1
            or not isinstance(ids[0], str)
            or UUID.fullmatch(ids[0]) is None
            or record["linkedOwner"].get("tipsterId") != ids[0]
            or record["linkedOwner"].get("tipster")
            != {
                k.removeprefix("tipster."): v for k, v in fields.items() if k.startswith("tipster.")
            }
            or not _plain(fields.get("tipster.user.username"), 80)
            or any(not _plain(fields.get(k)) for k in ("event", "pick", "competition"))
            or any(k == "name" or k.endswith(".name") for k in fields)
            or comparison.get("samePreviouslyRetainedNativeFields") is not True
            or comparison.get("changedPreviouslyRetainedFieldNames") != []
            or comparison.get("newTemporalEvidenceObservedAt") != content["observedAt"]
            or comparison.get("firstSeenAt") != source["baselineObservedAt"]
        ):
            raise ValueError("NotBetting native identity, literal fields or provenance")
        names = re.split(r"\s+[-–]\s+", fields["event"])
        matches = [
            f
            for f in fixtures
            if len(names) == 2
            and names[0].strip().casefold() in {a.casefold() for a in f["homeAliases"]}
            and names[1].strip().casefold() in {a.casefold() for a in f["awayAliases"]}
        ]
        if len(matches) != 1 or fields["competition"].strip() != "Premier League":
            raise ValueError("NotBetting canonical fixture absent or ambiguous")
        fixture = matches[0]
        if (
            not isinstance(times.get("date"), str)
            or instant(times["date"]) != instant(fixture["kickoff"])
            or instant(content["observedAt"]) >= instant(fixture["kickoff"])
            or instant(source["baselineObservedAt"]) > instant(content["observedAt"])
        ):
            raise ValueError("NotBetting native edition or strict pre-match proof")
        # The native date identifies this event edition. createdAt is never a certified publication.
        literal = {k: fields[k] for k in ("id", "event", "pick", "competition", "tipsterId")}
        literal.update({k: v for k, v in times.items() if k in {"date", "createdAt"}})
        rows.append(
            dict(
                id=f"notbetting-tip:{identifier}",
                sourceId="NotBetting",
                authorId="public:" + sha256(("notbetting:" + ids[0]).encode()).hexdigest(),
                authorLabel=fields["tipster.user.username"],
                authorUrl=SOURCE_URL,
                sourceUrl=SOURCE_URL,
                sourceTipId=identifier,
                fixtureId=fixture["id"],
                fixtureLabel=fixture["label"],
                kickoff=fixture["kickoff"],
                selection=fields["pick"],
                market="source_native_opaque",
                marketLabel="Choix publié (marché source non interprété)",
                sourceMarketLabel=None,
                sourceBetType=None,
                sourceFields=literal,
                sourceEventLocalText=times["date"],
                sourceEventTimezone=None,
                publishedAt=None,
                publishedCivilDate=None,
                observedAt=content["observedAt"],
                firstSeenAt=source["baselineObservedAt"],
                temporalEvidenceFirstObservedAt=content["observedAt"],
                responseSha256=content["responseSha256"],
                parserSha256=parser_sha,
                sourceRecordFingerprint=fingerprint,
                calendarSha256=sha256(canonical(fixtures)).hexdigest(),
                performanceEvaluationAllowed=False,
                settlementAllowed=False,
                marketInterpretationAllowed=False,
                versions=[dict(selection=fields["pick"], observedAt=content["observedAt"])],
                versionCount=1,
            )
        )
    return rows


def merge_public(base: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    data = deepcopy(base)
    data["picks"] = merge_distinct_choices(data["picks"], bundle["picks"])
    fixtures = {f["id"]: f for f in data.get("fixtures", [])}
    accepted_fixture_ids = {p["fixtureId"] for p in bundle["picks"]}
    for fixture in bundle["fixtures"]:
        if fixture["id"] not in accepted_fixture_ids:
            continue
        prior = fixtures.get(fixture["id"])
        if prior is not None:
            if (
                instant(prior["kickoff"]) != instant(fixture["kickoff"])
                or prior.get("label") != fixture.get("label")
                or any(
                    not {a.casefold() for a in prior.get(k, [])}.intersection(
                        a.casefold() for a in fixture.get(k, [])
                    )
                    for k in ("homeAliases", "awayAliases")
                )
            ):
                raise ValueError("NotBetting existing fixture identity or kickoff conflict")
        else:
            fixtures[fixture["id"]] = deepcopy(fixture)
    data["fixtures"] = list(fixtures.values())
    data["claimIds"] = list(dict.fromkeys([*data.get("claimIds", []), bundle["claimId"]]))
    data["distinctPicks"] = len(data["picks"])
    data["authorCount"] = len({p["authorId"] for p in data["picks"]})
    clocks = [data["sourceObservedThrough"]] if data.get("sourceObservedThrough") else []
    clocks.extend(p[k] for p in data["picks"] for k in ("observedAt", "lastObservedAt") if p.get(k))
    data["sourceObservedThrough"] = max(clocks, key=instant)
    data["generatedAt"] = max([data["generatedAt"], bundle["qualifiedAt"]], key=instant)
    data["notbettingCollection"] = dict(
        state="qualified_one_time",
        claimId=bundle["claimId"],
        qualifiedAt=bundle["qualifiedAt"],
        nativeChoices=len(bundle["picks"]),
        unadmittedNativeWitnesses=2,
        recurringAuthority=False,
    )
    return data


def _read(path: Path, limit: int = 200_000) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("NotBetting artifact size")
    return raw


def _load(root: Path) -> dict[str, Any]:
    raw = _read(root / "reports/source_observatory" / REPORT_NAME)
    if sha256(raw).hexdigest() != APPROVED_REPORT_SHA256:
        raise ValueError("NotBetting reviewed report hash")
    report = json.loads(raw)
    if (
        report.get("schemaVersion") != "robin-notbetting-opaque-data-v1"
        or report.get("scope") != "LOCAL_PERSONAL_NONCOMMERCIAL_NO_REDISTRIBUTION"
    ):
        raise ValueError("NotBetting report scope")
    for k in ("bundleSha256", "sourceResultSha256", "nativeRecordsParserSha256", "calendarSha256"):
        if not isinstance(report.get(k), str) or HASH.fullmatch(report[k]) is None:
            raise ValueError("NotBetting artifact anchors")
    directory = root / "cockpit/.ci/notbetting-prospective-0130-v2-20261121"
    source_raw = _read(directory / "result.json")
    bundle_raw = _read(directory / f"observations-{report['bundleSha256']}.json")
    if (
        sha256(source_raw).hexdigest() != report["sourceResultSha256"]
        or sha256(bundle_raw).hexdigest() != report["bundleSha256"]
    ):
        raise ValueError("NotBetting immutable source or bundle hash")
    bundle: dict[str, Any] = json.loads(bundle_raw)
    if (
        bundle.get("schemaVersion") != "robin-notbetting-opaque-bundle-v1"
        or bundle.get("sourceResultSha256") != report["sourceResultSha256"]
        or bundle.get("claimId") != report.get("dataClaimId")
        or sha256(canonical(bundle.get("fixtures"))).hexdigest() != report["calendarSha256"]
    ):
        raise ValueError("NotBetting bundle lineage")
    expected = build_choices(
        json.loads(source_raw),
        bundle["fixtures"],
        bundle["acceptedSourceTipIds"],
        parser_sha=report["nativeRecordsParserSha256"],
    )
    if canonical(bundle.get("picks")) != canonical(expected):
        raise ValueError("NotBetting admission changed")
    return bundle


def add_public(base: dict[str, Any], root: Path) -> dict[str, Any]:
    try:
        return merge_public(base, _load(root))
    except (OSError, ValueError, KeyError, TypeError):
        data = deepcopy(base)
        data["notbettingCollection"] = dict(state="unavailable", recurringAuthority=False)
        return data
