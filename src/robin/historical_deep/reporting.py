"""Deterministic JSON and Markdown reporting for the historical-deep pilot."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from enum import Enum, StrEnum
from typing import Final

from robin.historical_deep.replay import canonical_sha256


class HarvestVerdict(StrEnum):
    READY = "HISTORICAL_DEEP_DATA_HARVEST_READY"
    PARTIAL = "HISTORICAL_DEEP_DATA_HARVEST_PARTIAL"
    BLOCKED_BY_PROVIDER = "HISTORICAL_DEEP_DATA_HARVEST_BLOCKED_BY_PROVIDER"
    FAILED = "HISTORICAL_DEEP_DATA_HARVEST_FAILED"


HARVEST_VERDICTS: Final = tuple(verdict.value for verdict in HarvestVerdict)
_READY_GATE_STATUSES = {"READY_STRICT", "READY_RECONSTRUCTED"}
_REQUIRED_GATES = {
    "TEAM",
    "PLAYER",
    "PLAYER_FORM",
    "STARTER_BASELINE",
    "LINEUP",
    "FORMATION",
    "ABSENCE",
    "DISCIPLINE",
    "FOOTEDNESS",
    "WEATHER",
}
_REQUIRED_DATASETS = {
    "TEAM_PREMATCH_STRICT",
    "PLAYER_PREMATCH_STRICT",
    "LINEUP_HISTORY_PREMATCH_STRICT",
    "TARGET_POST_LINEUP_RECONSTRUCTED",
    "INJURY_INTERVAL_RECONSTRUCTED",
    "POST_MATCH_DESCRIPTIVE",
}
_REQUIRED_BACKTEST_MODES = {
    "STRICT_PREMATCH",
    "RECONSTRUCTED_POST_LINEUP",
    "DESCRIPTIVE_POST_MATCH",
}


def _plain(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _plain(asdict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _plain(model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, Enum):
        return _plain(value.value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"REPORT_VALUE_NOT_JSON_SERIALIZABLE:{type(value).__name__}")


def _mapped(value: object | None) -> Mapping[str, object]:
    if value is None:
        return {}
    result = _plain(value)
    if not isinstance(result, Mapping):
        raise TypeError("REPORT_SECTION_MUST_BE_A_MAPPING")
    return result


def _provider_blocked(provider: Mapping[str, object]) -> bool:
    status = str(provider.get("status", provider.get("availability", "AVAILABLE"))).upper()
    plan = provider.get("plan")
    return (
        provider.get("available") is False
        or provider.get("active") is False
        or (plan is not None and str(plan) != "Mega")
        or status
        in {
            "BLOCKED_PROVIDER",
            "BLOCKED_BY_PROVIDER",
            "UNAVAILABLE",
            "NOT_AVAILABLE",
            "SUBSCRIPTION_INACTIVE",
            "AUTHENTICATION_FAILED",
        }
    )


def _provider_ready(provider: Mapping[str, object]) -> bool:
    return provider.get("plan") == "Mega" and provider.get("active") is True


def _integer(value: object) -> int:
    try:
        return int(str(value))
    except ValueError as exc:
        raise ValueError("REPORT_INTEGER_FIELD_INVALID") from exc


def _backtest_ready(backtest: Mapping[str, object]) -> bool:
    if (
        str(backtest.get("status", "")).upper() != "COMPLETE"
        or backtest.get("promotion") != "NO_PROMOTION"
        or backtest.get("cache_only") is not True
        or backtest.get("mode_separation_verified") is not True
        or backtest.get("provider_calls", 0) not in (0, None)
        or backtest.get("provider_credits", 0) not in (0, None)
    ):
        return False
    modes = _mapped(backtest.get("modes"))
    if set(modes) != _REQUIRED_BACKTEST_MODES:
        return False
    fold_count = 0
    evaluated_support = 0
    for mode in modes.values():
        folds = _mapped(mode).get("folds")
        if not isinstance(folds, (list, tuple)):
            return False
        for fold in folds:
            fold_data = _mapped(fold)
            fold_count += 1
            test_rows = fold_data.get("test_rows")
            if test_rows is not None:
                evaluated_support += _integer(test_rows)
                continue
            details = fold_data.get("details")
            if isinstance(details, (list, tuple)):
                evaluated_support += len(details)
    return fold_count > 0 and evaluated_support > 0


def determine_harvest_verdict(
    *,
    replay: object | None,
    quality: object | None,
    gates: Mapping[str, object] | None,
    datasets: Mapping[str, object] | None = None,
    provider: Mapping[str, object] | None = None,
    backtest: object | None = None,
    fatal_errors: Sequence[str] = (),
    partial_reasons: Sequence[str] = (),
) -> str:
    if fatal_errors:
        return HarvestVerdict.FAILED.value
    replay_data = _mapped(replay)
    quality_data = _mapped(quality)
    provider_data = provider or {}
    backtest_data = _mapped(backtest)
    if str(replay_data.get("status", "")).upper() in {
        "FAILED",
        "HASH_MISMATCH",
        "INTEGRITY_FAILED",
    }:
        return HarvestVerdict.FAILED.value
    if _integer(replay_data.get("hash_mismatches", 0) or 0) > 0:
        return HarvestVerdict.FAILED.value
    if _integer(quality_data.get("null_to_zero_conversions", 0) or 0) > 0:
        return HarvestVerdict.FAILED.value

    payloads_replayed = _integer(replay_data.get("payloads_replayed", 0) or 0)
    if _provider_blocked(provider_data):
        return HarvestVerdict.BLOCKED_BY_PROVIDER.value
    if partial_reasons:
        return HarvestVerdict.PARTIAL.value

    gate_values = gates or {}
    gate_statuses = [str(_mapped(value).get("status", "")) for value in gate_values.values()]
    replay_ready = (
        payloads_replayed > 0
        and _integer(replay_data.get("receipts_verified", 0) or 0) == payloads_replayed
        and replay_data.get("hash_identical") is True
        and _integer(replay_data.get("hash_mismatches", 0) or 0) == 0
        and _integer(replay_data.get("missing_payloads", 0) or 0) == 0
        and replay_data.get("provider_calls", 0) in (0, None)
    )
    quality_ready = (
        quality_data.get("exact_replay") is True
        and quality_data.get("mismatches") in ((), [])
        and quality_data.get("null_to_zero_conversions", 0) in (0, None)
        and quality_data.get("normalization_errors") in ((), [])
    )
    gates_ready = set(gate_values) == _REQUIRED_GATES and all(
        status in _READY_GATE_STATUSES for status in gate_statuses
    )
    datasets_ready = datasets is not None and set(datasets) == _REQUIRED_DATASETS
    if datasets_ready and datasets is not None:
        datasets_ready = all(
            bool(_mapped(manifest).get("dataset_hash"))
            and bool(_mapped(manifest).get("provenance_hash"))
            and bool(_mapped(manifest).get("cutoff_policy"))
            and bool(_mapped(manifest).get("allowed_usages"))
            and bool(_mapped(manifest).get("features"))
            and isinstance(_mapped(manifest).get("null_counts"), Mapping)
            and _mapped(manifest).get("null_rate") is not None
            and isinstance(
                _mapped(manifest).get("temporal_class_counts"),
                Mapping,
            )
            and _integer(_mapped(manifest).get("row_count", 0) or 0) > 0
            for manifest in datasets.values()
        )
    if (
        _provider_ready(provider_data)
        and replay_ready
        and quality_ready
        and gates_ready
        and datasets_ready
        and _backtest_ready(backtest_data)
    ):
        return HarvestVerdict.READY.value
    return HarvestVerdict.PARTIAL.value


def build_historical_deep_report(
    *,
    replay: object | None,
    quality: object | None,
    datasets: Mapping[str, object],
    gates: Mapping[str, object],
    backtest: object | None,
    provider: Mapping[str, object] | None = None,
    fatal_errors: Sequence[str] = (),
    partial_reasons: Sequence[str] = (),
    campaign_id: str = "historical-deep-data-harvest-v1",
) -> dict[str, object]:
    replay_data = dict(_mapped(replay))
    quality_data = dict(_mapped(quality))
    dataset_data = {str(name): _plain(value) for name, value in sorted(datasets.items())}
    gate_data = {str(name): _plain(value) for name, value in sorted(gates.items())}
    backtest_data = dict(_mapped(backtest))
    verdict = determine_harvest_verdict(
        replay=replay_data,
        quality=quality_data,
        gates=gate_data,
        datasets=dataset_data,
        provider=provider,
        backtest=backtest_data,
        fatal_errors=fatal_errors,
        partial_reasons=partial_reasons,
    )
    body: dict[str, object] = {
        "schema_version": "historical-deep-report-v1",
        "campaign_id": campaign_id,
        "verdict": verdict,
        "provider": _plain(provider or {}),
        "replay": replay_data,
        "quality_v2": quality_data,
        "datasets": dataset_data,
        "gates": gate_data,
        "backtest": backtest_data,
        "fatal_errors": list(fatal_errors),
        "partial_reasons": list(partial_reasons),
        "safety": {
            "cache_only": True,
            "provider_calls_during_replay_and_backtest": 0,
            "production_status": "PRODUCTION_LOCKED",
            "promotion": "NO_PROMOTION",
            "real_bets": False,
            "no_bet_default": True,
        },
    }
    body["report_hash"] = canonical_sha256(body)
    return body


def render_report_json(
    report: Mapping[str, object],
    *,
    indent: int = 2,
) -> str:
    verdict = str(report.get("verdict", ""))
    if verdict not in HARVEST_VERDICTS:
        raise ValueError(f"REPORT_VERDICT_INVALID:{verdict}")
    return (
        json.dumps(
            _plain(report),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=indent,
        )
        + "\n"
    )


def _status(value: object) -> str:
    mapped = _mapped(value)
    return str(mapped.get("status", "UNKNOWN"))


def render_report_markdown(report: Mapping[str, object]) -> str:
    verdict = str(report.get("verdict", ""))
    if verdict not in HARVEST_VERDICTS:
        raise ValueError(f"REPORT_VERDICT_INVALID:{verdict}")
    replay = _mapped(report.get("replay"))
    quality = _mapped(report.get("quality_v2"))
    datasets = _mapped(report.get("datasets"))
    gates = _mapped(report.get("gates"))
    backtest = _mapped(report.get("backtest"))
    lines = [
        "# Historical Deep Data Harvest V1",
        "",
        f"- Verdict: `{verdict}`",
        f"- Report hash: `{report.get('report_hash', 'UNAVAILABLE')}`",
        f"- Replay cache-only: `{replay.get('status', 'UNKNOWN')}`",
        f"- Payloads rejoués: `{replay.get('payloads_replayed', 0)}`",
        f"- Hash identique: `{replay.get('hash_identical', False)}`",
        f"- Comparaison qualité exacte: `{quality.get('exact_replay', False)}`",
        f"- Conversions null vers zéro: `{quality.get('null_to_zero_conversions', 0)}`",
        "",
        "## Datasets séparés",
        "",
        "| Dataset | Lignes | Hash | Cutoff |",
        "|---|---:|---|---|",
    ]
    for name, value in sorted(datasets.items()):
        manifest = _mapped(value)
        lines.append(
            f"| {name} | {manifest.get('row_count', 0)} | "
            f"`{manifest.get('dataset_hash', 'UNAVAILABLE')}` | "
            f"{manifest.get('cutoff_policy', 'UNKNOWN')} |"
        )
    lines.extend(
        [
            "",
            "## Gates",
            "",
            "| Gate | Statut | Raisons |",
            "|---|---|---|",
        ]
    )
    for name, value in sorted(gates.items()):
        assessment = _mapped(value)
        reasons_value = assessment.get("reasons", [])
        reasons = (
            ", ".join(str(reason) for reason in reasons_value)
            if isinstance(reasons_value, (list, tuple))
            else str(reasons_value)
        )
        lines.append(f"| {name} | {_status(value)} | {reasons or '—'} |")
    lines.extend(
        [
            "",
            "## Pilote backtest",
            "",
            f"- Cache-only: `{backtest.get('cache_only', False)}`",
            f"- Séparation des modes: `{backtest.get('mode_separation_verified', False)}`",
            f"- Correction multiple: `{backtest.get('multiple_testing_method', 'UNKNOWN')}`",
            "- Promotion: `NO_PROMOTION`",
            "- Production: `PRODUCTION_LOCKED`",
            "",
        ]
    )
    return "\n".join(lines)


report_json = render_report_json
report_markdown = render_report_markdown
