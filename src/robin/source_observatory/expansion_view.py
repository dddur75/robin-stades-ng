"""Read admitted expansion facts separately from recurrent author authority."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from .expanded_olbg_campaign import MISSION, PROFILE, read_state
from .olbg_store import read_bundle
from .qualification_view import merge_sro_collection

APPROVED_REPORT_SHA256 = "879b334212406dff9f0383d3236569201fd6c5f3533d4abe742fe7cbe5e20b02"
APPROVED_BUNDLE_SHA256 = "0e1abfc6d3973fdaa0887bca68d90af1f5cb597d0e8f858c4898a7202a8ec408"


def load_expansion(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    path = root / "reports/source_observatory/TIPSTERS-SOURCE-EXPANSION-E1-20261120.json"
    raw = path.read_bytes()
    if len(raw) > 100_000 or sha256(raw).hexdigest() != APPROVED_REPORT_SHA256:
        raise ValueError("expansion report mismatch")
    report = json.loads(raw)
    if (
        report["schemaVersion"] != "robin-source-expansion-e1-v1"
        or report["evidence"]["bundleSha256"] != APPROVED_BUNDLE_SHA256
    ):
        raise ValueError("expansion source provenance")
    directory = root / "cockpit/.ci/tipsters-source-expansion-20261120-v2"
    bundle = read_bundle(
        directory / f"observations-{APPROVED_BUNDLE_SHA256}.json", APPROVED_BUNDLE_SHA256
    )
    content_raw = (directory / "content.json").read_bytes()
    if (
        len(content_raw) > 2_000_000
        or sha256(content_raw).hexdigest() != report["evidence"]["contentSha256"]
    ):
        raise ValueError("source facts mismatch")
    content = json.loads(content_raw)
    return report, bundle, content


def _unadmitted(url: str, bundle: dict[str, Any], content: dict[str, Any]) -> list[dict[str, Any]]:
    admitted = {p["sourceTipId"] for p in bundle["picks"]}
    out = []
    for item in content["platforms"]["OLBG"]["profiles"]:
        if item["request"]["url"] != url:
            continue
        for row in item["facts"]["records"]:
            if (
                row.get("vc_sport_id") != 1
                or row.get("result") != "Open"
                or row["tipid"] in admitted
            ):
                continue
            native = (
                row.get("winew") == "Win"
                and row.get("market") == ""
                and row.get("hcap_market") is False
            )
            out.append(
                {
                    "sourceTipId": row["tipid"],
                    "fixtureLabel": row.get("eventname"),
                    "selection": row.get("selection"),
                    "marketLabel": row.get("market") or "Win, libellé source",
                    "sourceEventText": row.get("event_datetime"),
                    "sourceUrl": url,
                    "observedAt": item["request"]["observedAt"],
                    "reason": "Calendrier canonique manquant"
                    if native
                    else "Calendrier ou contrat de marché non établi",
                }
            )
    for item in content["platforms"]["TP"]["profiles"]:
        if item["request"]["url"] != url + "/historial.csv" or "sourceFacts" not in item:
            continue
        observed = datetime.fromisoformat(item["request"]["observedAt"])
        for row in item["sourceFacts"]:
            try:
                future = (
                    datetime.fromisoformat(row.get("event_date", "").replace("Z", "+00:00"))
                    > observed
                )
            except (ValueError, TypeError):
                future = False
            if future:
                out.append(
                    {
                        "fixtureLabel": row.get("event"),
                        "selection": row.get("selection"),
                        "marketLabel": row.get("market"),
                        "sourceEventText": row.get("event_date"),
                        "sourceUrl": url,
                        "observedAt": item["request"]["observedAt"],
                        "reason": "Fuseau officiel indépendant et contrat h2h non établis",
                    }
                )
    return out


def apply_expansion_rows(
    base: dict[str, Any],
    report: dict[str, Any],
    bundle: dict[str, Any],
    content: dict[str, Any],
    *,
    active_urls: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    data = deepcopy(base)
    if data.get("qualification", {}).get("status") != "ok":
        data.setdefault("qualification", {})["expansionState"] = "unavailable"
        return data
    cases = {p["id"]: p for p in report["profiles"]}
    for row in data["candidates"]:
        case = cases.get(row["id"])
        if not case:
            continue
        if row["sourceUrl"] != case["sourceUrl"] or row["origin"]["sheet"] != "Catalogue":
            raise ValueError("expansion candidate identity")
        prior = row["qualification"]
        row.setdefault("previousExpansionAssessment", deepcopy(prior))
        new_picks = [p for p in bundle["picks"] if p["authorUrl"] == row["sourceUrl"]]
        picks = {p["id"]: p for p in prior.get("picks", [])}
        picks.update({p["id"]: p for p in new_picks})
        row["qualification"] = {
            **prior,
            **{
                k: case[k]
                for k in [
                    "label",
                    "reason",
                    "requiredAccess",
                    "ownerAction",
                    "observedAt",
                    "profileVisited",
                ]
            },
            "personallyProven": bool(picks),
            "picks": list(picks.values()),
            "expansionClaimId": report["claimId"],
            "unadmittedFacts": _unadmitted(row["sourceUrl"], bundle, content),
        }
        if row["sourceUrl"] == PROFILE:
            row["qualification"].update(expansionCampaignId=MISSION, expansionAuthorUrl=PROFILE)
            if row["sourceUrl"] in active_urls:
                row["qualification"].update(
                    label="Choix personnel observé avant match",
                    requiredAccess="Aucun compte ni achat requis dans ce canari borné.",
                    ownerAction="Campagne propre au profil383717 : un canari et deux créneaux à14h/16hParis, plafond9GET et expiration16h15. Le statut Windows courant reste contrôlé séparément.",
                    campaignClaimId="DATA.SOURCE_OBSERVATORY.EXPANDED.OLBG.E2.20261120",
                )
        if case["platform"] == "Tipster Platform":
            row["qualification"]["responseUrl"] = row["sourceUrl"] + "/historial.csv"
        # A source-wide grant for648433 cannot activate383717.
        row["collectionEnabled"] = bool(picks and row["sourceUrl"] in active_urls)
    data["enabledCount"] = sum(bool(r["collectionEnabled"]) for r in data["candidates"])
    for platform in data["qualification"].get("platforms", []):
        if platform["platform"] not in {"OLBG", "Tipster Platform"}:
            continue
        platform.setdefault("previousExpansionAssessment", deepcopy(platform))
        platform.update(
            expansionClaimId=report["claimId"],
            scope="exact_six_profile_expansion_not_platform_wide",
        )
        if platform["platform"] == "OLBG":
            platform.update(
                label="Contrôle supplémentaire de quatre profils publics",
                reason="Deux tableaux personnels vides ; deux avec des faits football, dont un nouveau choix avant match prouvé. Ce contrôle ne qualifie pas tous les profils de la plateforme.",
                requiredAccess="Preuve individuelle et autorité bornée propre à chaque nouveau profil.",
                ownerAction="Les campagnes648433 et383717 ont des budgets et états distincts. Les autres profils ne sont pas activés par ce contrôle.",
            )
        else:
            platform.update(
                label="Deux exports personnels publics vérifiés",
                reason="Les profils charlespicks etcr-is5687 offrent leurs CSV. Les historiques restent séparés ; le seul choix encore futur observé n’est pas admis sans calendrier et contrat de marché.",
                requiredAccess="Publication prospective, coup d’envoi officiel avec fuseau et contrat du marché natif.",
                ownerAction="Aucun compte ou abonnement requis pour ces deux exports. Aucune collecte des autres profils n’est autorisée par ce contrôle.",
            )
    data["qualification"].update(
        expansionState="ok",
        expansionClaimId=report["claimId"],
        qualifiedCount=sum(
            bool(r.get("qualification", {}).get("personallyProven")) for r in data["candidates"]
        ),
    )
    return data


def add_public_expansion(base: dict[str, Any], root: Path) -> dict[str, Any]:
    try:
        report, bundle, _ = load_expansion(root)
        data = merge_sro_collection(base, bundle)
        fixtures = {f.get("id", f.get("fixture_id")): f for f in base.get("fixtures", [])}
        fixtures.update({f["id"]: f for f in bundle["fixtures"]})
        data["fixtures"] = list(fixtures.values())
        data["sourceExpansion"] = {
            "state": "e1_verified",
            "claimId": report["claimId"],
            "counts": report["counts"],
            "profiles": report["profiles"],
        }
        state, bundles, _ = read_state(root / "cockpit/.ci/tipsters-expanded-olbg-e2-20261120-v2")
        for later in bundles:
            data = merge_sro_collection(data, later)
        data["expandedOlbgCampaign"] = state
        observed = [p["observedAt"] for p in data["picks"] if p.get("observedAt")]
        if observed:
            data["generatedAt"] = max(
                observed, key=lambda t: datetime.fromisoformat(t.replace("Z", "+00:00"))
            )
        return data
    except (OSError, ValueError, KeyError, TypeError):
        data = deepcopy(base)
        data["sourceExpansion"] = {"state": "unavailable"}
        return data


def add_candidate_expansion(base: dict[str, Any], root: Path) -> dict[str, Any]:
    try:
        report, bundle, content = load_expansion(root)
        state, bundles, active = read_state(
            root / "cockpit/.ci/tipsters-expanded-olbg-e2-20261120-v2"
        )
        merged = deepcopy(bundle)
        for later in bundles:
            merged = merge_sro_collection(merged, later)
        data = apply_expansion_rows(
            base,
            report,
            merged,
            content,
            active_urls=frozenset({PROFILE}) if active else frozenset(),
        )
        data["qualification"]["expandedOlbgCampaign"] = state
        return data
    except (OSError, ValueError, KeyError, TypeError):
        data = deepcopy(base)
        data.setdefault("qualification", {})["expansionState"] = "unavailable"
        return data
