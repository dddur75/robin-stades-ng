from __future__ import annotations

import gzip
from datetime import UTC, datetime

import pytest

from robin.historical_deep.backtest import (
    benjamini_hochberg,
    grouped_bootstrap,
    run_cache_only_backtest,
)
from robin.historical_deep.features import (
    build_lineup_continuity_features,
    build_player_features,
    build_team_features,
)
from robin.historical_deep.gates import (
    GateThreshold,
    assess_gate,
    evaluate_gate_registry,
)
from robin.historical_deep.quality import (
    DATASET_NAMES,
    INJURY_INTERVAL_RECONSTRUCTED,
    LINEUP_HISTORY_PREMATCH_STRICT,
    POST_MATCH_DESCRIPTIVE,
    TARGET_POST_LINEUP_RECONSTRUCTED,
    build_dataset_manifests,
    classify_temporal_record,
    compare_quality_v2,
    separate_temporal_datasets,
)
from robin.historical_deep.replay import (
    canonical_json_bytes,
    canonical_sha256,
    replay_cache_only,
    replay_stream_cache_only,
)
from robin.historical_deep.reporting import (
    HarvestVerdict,
    build_historical_deep_report,
    determine_harvest_verdict,
    render_report_json,
    render_report_markdown,
)


def at(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, 12, tzinfo=UTC)


def test_cache_only_replay_verifies_canonical_payload_and_is_deterministic() -> None:
    payload = {"response": [{"fixture": 123, "value": None}], "results": 1}
    encoded = canonical_json_bytes(payload)
    receipt = {
        "task_id": "task-1",
        "payload_key": "r2/payload.json.gz",
        "payload_sha256": canonical_sha256(payload),
        "family": "fixtures",
        "competition": "api-football:39",
        "season": 2024,
    }
    first = replay_cache_only(
        {"r2/payload.json.gz": gzip.compress(encoded, mtime=0)},
        [receipt],
    )
    second = replay_cache_only(
        {"r2/payload.json.gz": payload},
        [receipt],
        expected_replay_hash=first.replay_hash,
    )

    assert first.replay_hash == second.replay_hash
    assert second.hash_identical is True
    assert second.provider_calls == second.provider_credits == 0
    assert second.entries[0].projection["payload"] == payload

    with pytest.raises(ValueError, match="REPLAY_PAYLOAD_HASH_MISMATCH"):
        replay_cache_only(
            {"r2/payload.json.gz": {"response": [], "results": 0}},
            [receipt],
        )


def test_cache_only_replay_can_release_full_projections_after_hashing() -> None:
    marker = "large-marker-" + ("x" * 100_000)
    payload = {"response": [{"marker": marker}]}
    receipt = {
        "task_id": "task-digest-only",
        "payload_key": "r2/digest-only.json.gz",
        "payload_sha256": canonical_sha256(payload),
    }

    result = replay_cache_only(
        {"r2/digest-only.json.gz": payload},
        [receipt],
        retain_projections=False,
    )

    assert result.entries[0].projection is None
    assert result.entries[0].projection_sha256
    assert marker not in repr(result.as_dict())


def test_streaming_replay_detects_orphans_without_materializing_payload_map() -> None:
    payload = {"response": [{"fixture": 123}]}
    receipt = {
        "task_id": "stream-task",
        "payload_key": "r2/stream.json.gz",
        "payload_sha256": canonical_sha256(payload),
    }
    result = replay_stream_cache_only(
        iter(((receipt, payload),)),
        known_payload_keys=iter(("r2/stream.json.gz",)),
        retain_projections=False,
    )
    assert result.receipts_verified == 1
    assert result.entries[0].projection is None

    with pytest.raises(ValueError, match="REPLAY_UNREFERENCED_PAYLOADS:1"):
        replay_stream_cache_only(
            iter(((receipt, payload),)),
            known_payload_keys=iter(
                ("r2/stream.json.gz", "r2/orphan.json.gz")
            ),
            retain_projections=False,
        )


def test_quality_v2_preserves_nulls_and_reports_before_after() -> None:
    before = [{"fixture_id": "1", "player_id": "10", "minutes": None}]
    exact = compare_quality_v2(
        before,
        [dict(before[0])],
        key_fields=("fixture_id", "player_id"),
        required_fields=("minutes",),
        identity_fields=("fixture_id", "player_id"),
    )

    assert exact.exact_replay is True
    assert exact.before.null_rate == {"minutes": 1.0}
    assert exact.after.identity_rate == 1.0
    assert exact.before_hash == exact.after_hash

    with pytest.raises(ValueError, match="QUALITY_NULL_TO_ZERO_FORBIDDEN"):
        compare_quality_v2(
            before,
            [{"fixture_id": "1", "player_id": "10", "minutes": 0}],
            key_fields=("fixture_id", "player_id"),
            required_fields=("minutes",),
        )


def test_temporal_classifier_never_uses_target_as_prior_history() -> None:
    prior_lineup = classify_temporal_record(
        {
            "family": "lineups",
            "fixture_id": "prior",
            "source_fixture_kickoff": at(2023),
        },
        target_fixture_id="target",
        target_fixture_kickoff=at(2024),
    )
    target_lineup = classify_temporal_record(
        {
            "family": "lineups",
            "fixture_id": "target",
            "source_fixture_kickoff": at(2024),
        },
        target_fixture_id="target",
        target_fixture_kickoff=at(2024),
    )
    target_stats = classify_temporal_record(
        {
            "family": "team_match_statistics",
            "fixture_id": "target",
            "source_fixture_kickoff": at(2024),
        },
        target_fixture_id="target",
        target_fixture_kickoff=at(2024),
    )
    unknown_injury = classify_temporal_record(
        {
            "family": "injuries",
            "fixture_id": "prior",
            "source_fixture_kickoff": at(2023),
        },
        target_fixture_id="target",
        target_fixture_kickoff=at(2024),
    )

    assert prior_lineup.dataset == LINEUP_HISTORY_PREMATCH_STRICT
    assert prior_lineup.strict_prematch_usable is True
    assert target_lineup.dataset == TARGET_POST_LINEUP_RECONSTRUCTED
    assert target_lineup.temporal_class == "POST_LINEUP_RECONSTRUCTED"
    assert target_stats.dataset == POST_MATCH_DESCRIPTIVE
    assert target_stats.temporal_class == "POST_MATCH_ONLY"
    assert unknown_injury.dataset == INJURY_INTERVAL_RECONSTRUCTED
    assert unknown_injury.temporal_class == "ANNOUNCEMENT_TIME_UNKNOWN"
    assert unknown_injury.reconstructed is True


def test_six_datasets_have_hashed_provenance_cutoff_and_usage_manifests() -> None:
    records = [
        {
            "target_fixture_id": "target",
            "target_fixture_kickoff": at(2024),
            "family": "lineups",
            "fixture_id": "prior",
            "source_fixture_kickoff": at(2023),
        },
        {
            "target_fixture_id": "target",
            "target_fixture_kickoff": at(2024),
            "family": "lineups",
            "fixture_id": "target",
            "source_fixture_kickoff": at(2024),
        },
        {
            "target_fixture_id": "target",
            "target_fixture_kickoff": at(2024),
            "family": "team_match_statistics",
            "fixture_id": "target",
            "source_fixture_kickoff": at(2024),
        },
    ]
    datasets = separate_temporal_datasets(records)
    manifests = build_dataset_manifests(
        datasets,
        provenance={
            "provider": "api-football",
            "r2_namespace": "historical-deep-data/schema-v1",
            "replay_hash": "a" * 64,
        },
    )

    assert tuple(datasets) == DATASET_NAMES
    assert tuple(manifests) == DATASET_NAMES
    assert all(len(manifest.dataset_hash) == 64 for manifest in manifests.values())
    assert all(len(manifest.manifest_hash) == 64 for manifest in manifests.values())
    assert all(manifest.allowed_usages for manifest in manifests.values())
    assert all(manifest.cutoff_policy for manifest in manifests.values())
    non_empty = [manifest for manifest in manifests.values() if manifest.row_count]
    assert all(manifest.features for manifest in non_empty)
    assert all(manifest.null_rate is not None for manifest in non_empty)
    assert all(
        sum(manifest.temporal_class_counts.values()) == manifest.row_count
        for manifest in manifests.values()
    )
    assert all(
        sum(manifest.normalized_family_counts.values()) == manifest.row_count
        for manifest in manifests.values()
    )


def test_dataset_manifests_can_hash_verified_replay_order_without_resorting() -> None:
    source_rows = [
        {
            "fixture_id": fixture_id,
            "family": "lineups",
            "temporal_class": "HISTORICAL_PREMATCH_STRICT",
            "optional_value": optional_value,
        }
        for fixture_id, optional_value in (("a", 1), ("b", None), ("c", 3))
    ]
    replay_rows = list(reversed(sorted(source_rows, key=canonical_sha256)))
    datasets = {LINEUP_HISTORY_PREMATCH_STRICT: replay_rows}
    provenance = {
        "provider": "api-football",
        "r2_namespace": "historical-deep-data/schema-v1",
        "replay_hash": "a" * 64,
    }

    preserved = build_dataset_manifests(
        datasets,
        provenance=provenance,
        preserve_input_order=True,
    )[LINEUP_HISTORY_PREMATCH_STRICT]
    canonical = build_dataset_manifests(
        datasets,
        provenance=provenance,
    )[LINEUP_HISTORY_PREMATCH_STRICT]

    assert preserved.dataset_hash == canonical_sha256(replay_rows)
    assert canonical.dataset_hash == canonical_sha256(
        sorted(replay_rows, key=canonical_sha256)
    )
    assert preserved.dataset_hash != canonical.dataset_hash
    assert preserved.null_counts["optional_value"] == 1


def test_features_use_only_strict_prior_matches_and_keep_unknown_values_null() -> None:
    team_rows = [
        {
            "fixture_id": "p1",
            "source_fixture_kickoff": at(2022),
            "home_team_id": "A",
            "away_team_id": "B",
            "home_goals": 2,
            "away_goals": 1,
            "yellow_cards": None,
        },
        {
            "fixture_id": "target",
            "source_fixture_kickoff": at(2024),
            "home_team_id": "A",
            "away_team_id": "B",
            "home_goals": 9,
            "away_goals": 0,
        },
    ]
    player_rows = [
        {
            "fixture_id": "p1",
            "source_fixture_kickoff": at(2022),
            "player_id": "10",
            "minutes": None,
            "started": None,
            "goals": None,
        },
        {
            "fixture_id": "target",
            "source_fixture_kickoff": at(2024),
            "player_id": "10",
            "minutes": 90,
            "started": True,
            "goals": 5,
        },
    ]
    lineups = [
        {
            "fixture_id": "p1",
            "source_fixture_kickoff": at(2022),
            "team_id": "A",
            "starters": [str(index) for index in range(1, 12)],
            "formation": "4-3-3",
        },
        {
            "fixture_id": "p2",
            "source_fixture_kickoff": at(2023),
            "team_id": "A",
            "starters": [str(index) for index in range(2, 13)],
            "formation": "4-4-2",
        },
        {
            "fixture_id": "target",
            "source_fixture_kickoff": at(2024),
            "team_id": "A",
            "starters": [str(index) for index in range(20, 31)],
        },
    ]

    team = build_team_features(
        team_rows,
        team_id="A",
        target_fixture_id="target",
        target_fixture_kickoff=at(2024),
    )
    player = build_player_features(
        player_rows,
        player_id="10",
        target_fixture_id="target",
        target_fixture_kickoff=at(2024),
    )
    continuity = build_lineup_continuity_features(
        lineups,
        team_id="A",
        target_fixture_id="target",
        target_fixture_kickoff=at(2024),
    )

    assert team["prior_matches_available"] == 1
    assert team["points_3"] == 3.0
    assert team["yellow_cards_3"] is None
    assert player["prior_appearances_available"] == 1
    assert player["minutes_3"] is None
    assert player["goals_3"] is None
    assert continuity["complete_prior_lineups"] == 2
    assert continuity["prior_to_prior_continuity"] == 10 / 11


def test_exact_gate_names_statuses_and_footedness_unavailable_reason() -> None:
    strict_evidence = [
        {
            "season": season,
            "coverage_rate": 1.0,
            "identity_rate": 1.0,
            "cutoff_proven": True,
            "source_available": True,
            "reconstructed": False,
        }
        for season in (2022, 2023, 2024)
    ]
    reconstructed_evidence = [
        {**row, "reconstructed": True, "cutoff_proven": False} for row in strict_evidence
    ]

    assert assess_gate("TEAM", strict_evidence).status == "READY_STRICT"
    absence = assess_gate("ABSENCE", reconstructed_evidence)
    assert absence.status == "READY_RECONSTRUCTED"
    gates = evaluate_gate_registry({"TEAM": strict_evidence})
    assert tuple(gates) == (
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
    )
    assert gates["FOOTEDNESS"].status == "BLOCKED_BY_SOURCE"
    assert gates["FOOTEDNESS"].reasons == ("FOOTEDNESS_API_FOOTBALL=NOT_AVAILABLE",)
    partial = assess_gate(
        "TEAM",
        strict_evidence[:1],
        GateThreshold(3, 0.95, 0.99),
    )
    assert partial.status == "PARTIAL"


def _backtest_row(
    *,
    mode: str,
    season: int,
    fixture: str,
    probability: float,
    target: int,
) -> dict[str, object]:
    return {
        "research_mode": mode,
        "season": season,
        "fixture_id": fixture,
        "kickoff_at": at(season),
        "model_probability": probability,
        "market_probability": 0.52,
        "odds": 2.0,
        "target": target,
        "competition": "api-football:39",
        "source_mode": "R2_CACHE",
        "provider_calls": 0,
    }


def test_cache_only_backtest_separates_modes_and_uses_train_only_thresholds() -> None:
    rows = [
        _backtest_row(
            mode="STRICT_PREMATCH",
            season=season,
            fixture=f"s{season}",
            probability=probability,
            target=target,
        )
        for season, probability, target in (
            (2022, 0.70, 1),
            (2023, 0.65, 1),
            (2024, 0.60, 0),
        )
    ]
    rows.extend(
        [
            _backtest_row(
                mode="RECONSTRUCTED_POST_LINEUP",
                season=season,
                fixture=f"r{season}",
                probability=0.70,
                target=1,
            )
            for season in (2022, 2023)
        ]
    )
    rows.append(
        _backtest_row(
            mode="DESCRIPTIVE_POST_MATCH",
            season=2024,
            fixture="descriptive",
            probability=0.99,
            target=1,
        )
    )
    result = run_cache_only_backtest(rows, devig_method="PROPORTIONAL")

    assert result["provider_calls"] == 0
    assert result["promotion"] == "NO_PROMOTION"
    strict = result["modes"]["STRICT_PREMATCH"]
    assert strict["threshold_policy"] == "TRAIN_ONLY"
    assert strict["folds"]
    assert all(
        fold["threshold_evidence"]["selection_policy"] == "TRAIN_ONLY" for fold in strict["folds"]
    )
    assert all(fold["temporal_order_verified"] for fold in strict["folds"])
    assert all("market_baseline" in fold for fold in strict["folds"])
    assert strict["grouped_bootstrap"]["method"] == "GROUPED_BOOTSTRAP"
    assert "concentration" in strict
    assert strict["negative_controls"]
    assert result["modes"]["DESCRIPTIVE_POST_MATCH"]["predictive_evaluation"] is False
    assert result["multiple_testing_method"] == "BENJAMINI_HOCHBERG"

    with pytest.raises(ValueError, match="BACKTEST_PROVIDER_CALL_FORBIDDEN"):
        run_cache_only_backtest(
            [{**rows[0], "provider_calls": 1}],
            devig_method="PROPORTIONAL",
        )


def test_grouped_bootstrap_and_fdr_are_deterministic() -> None:
    first = grouped_bootstrap(
        [1.0, -1.0, 2.0, 0.0],
        ["league-a", "league-a", "league-b", "league-b"],
        iterations=100,
        seed=7,
    )
    second = grouped_bootstrap(
        [1.0, -1.0, 2.0, 0.0],
        ["league-a", "league-a", "league-b", "league-b"],
        iterations=100,
        seed=7,
    )

    assert first == second
    assert first["groups"] == 2
    assert benjamini_hochberg({"a": 0.01, "b": 0.04, "c": None}) == {
        "a": 0.02,
        "b": 0.04,
        "c": None,
    }


def test_json_markdown_reporting_uses_only_four_exact_verdicts() -> None:
    replay = {
        "status": "CACHE_ONLY_REPLAY_VERIFIED",
        "payloads_replayed": 1,
        "receipts_verified": 1,
        "provider_calls": 0,
        "hash_identical": True,
        "hash_mismatches": 0,
        "missing_payloads": 0,
    }
    quality = {
        "exact_replay": True,
        "mismatches": [],
        "null_to_zero_conversions": 0,
        "normalization_errors": [],
    }
    ready_gates = {
        name: {"status": "READY_STRICT", "reasons": []}
        for name in (
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
        )
    }
    datasets = {
        name: {
            "dataset_hash": "a" * 64,
            "provenance_hash": "b" * 64,
            "cutoff_policy": "TEST_CUTOFF",
            "allowed_usages": ["TEST"],
            "features": ["feature"],
            "null_counts": {"feature": 0},
            "null_rate": 0.0,
            "temporal_class_counts": {"PRIOR_MATCH_USABLE": 1},
            "row_count": 1,
        }
        for name in DATASET_NAMES
    }
    provider = {"plan": "Mega", "active": True}
    backtest = {
        "status": "COMPLETE",
        "cache_only": True,
        "provider_calls": 0,
        "provider_credits": 0,
        "mode_separation_verified": True,
        "promotion": "NO_PROMOTION",
        "modes": {
            "STRICT_PREMATCH": {"folds": [{"test_rows": 1}]},
            "RECONSTRUCTED_POST_LINEUP": {"folds": []},
            "DESCRIPTIVE_POST_MATCH": {"folds": []},
        },
    }
    assert (
        determine_harvest_verdict(
            replay=replay,
            quality=quality,
            gates=ready_gates,
            datasets=datasets,
            provider=provider,
            backtest=backtest,
        )
        == HarvestVerdict.READY.value
    )
    assert (
        determine_harvest_verdict(
            replay={},
            quality={},
            gates={},
            provider={"status": "BLOCKED_PROVIDER"},
        )
        == HarvestVerdict.BLOCKED_BY_PROVIDER.value
    )
    assert (
        determine_harvest_verdict(
            replay=replay,
            quality={**quality, "normalization_errors": ["broken-row"]},
            gates=ready_gates,
            datasets=datasets,
            provider=provider,
            backtest=backtest,
        )
        == HarvestVerdict.PARTIAL.value
    )
    assert (
        determine_harvest_verdict(
            replay=replay,
            quality=quality,
            gates=ready_gates,
            datasets={
                **datasets,
                "TEAM_PREMATCH_STRICT": {
                    **datasets["TEAM_PREMATCH_STRICT"],
                    "row_count": 0,
                },
            },
            provider=provider,
            backtest=backtest,
        )
        == HarvestVerdict.PARTIAL.value
    )
    assert (
        determine_harvest_verdict(
            replay=replay,
            quality=quality,
            gates=ready_gates,
            datasets=datasets,
            provider=provider,
            backtest={
                **backtest,
                "modes": {
                    name: {"folds": []}
                    for name in (
                        "STRICT_PREMATCH",
                        "RECONSTRUCTED_POST_LINEUP",
                        "DESCRIPTIVE_POST_MATCH",
                    )
                },
            },
        )
        == HarvestVerdict.PARTIAL.value
    )
    assert (
        determine_harvest_verdict(
            replay=replay,
            quality=quality,
            gates=ready_gates,
            datasets=datasets,
            provider={"plan": "Mega", "active": False},
            backtest=backtest,
        )
        == HarvestVerdict.BLOCKED_BY_PROVIDER.value
    )
    report = build_historical_deep_report(
        replay=replay,
        quality=quality,
        datasets=datasets,
        gates=ready_gates,
        backtest=backtest,
        provider=provider,
    )

    assert report["verdict"] == HarvestVerdict.READY.value
    assert report["safety"]["promotion"] == "NO_PROMOTION"
    assert '"verdict": "HISTORICAL_DEEP_DATA_HARVEST_READY"' in render_report_json(report)
    assert "Promotion: `NO_PROMOTION`" in render_report_markdown(report)

    partial = build_historical_deep_report(
        replay=replay,
        quality=quality,
        datasets=datasets,
        gates=ready_gates,
        backtest=backtest,
        provider=provider,
        partial_reasons=("ANALYSIS_FEATURES_PARTIAL",),
    )
    assert partial["verdict"] == HarvestVerdict.PARTIAL.value
    assert partial["partial_reasons"] == ["ANALYSIS_FEATURES_PARTIAL"]
