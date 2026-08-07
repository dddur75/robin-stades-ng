"""Build the frozen E1B mission and selection from already committed evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MISSION_ID = "p0-e1b-five-league-capability-canary-v1"
SOURCE_MAIN = "b76ac9213853a52f058b33ef3cf4964798f40256"
SELECTION_POLICY = {
    "common_season_required": True,
    "finished_statuses": ["FT", "AET", "PEN"],
    "canonical_identity_required": True,
    "earliest_fixture_with_prior_finished_match_for_both_teams": True,
    "order": ["competition_id", "season", "kickoff_utc", "fixture_id"],
    "rationale": (
        "Maximize bounded calendar, form and fatigue observability without "
        "sacrificing deterministic selection."
    ),
}

# competition id, label, role, object id, payload hash, stored hash,
# logical bytes, stored bytes, receipt/task id, receipt hash
SOURCES = [
    (39, "Premier League", "CENSUS", "07e62bfd559843bc0e500c29369489fff2ca094cc579c8b92a1ddfc3ed92c48f", "b8cd15e5d83522aca0f0a8bae5109787690a93400c901ea53acee01d3eab0c8e", "e6eba644bdca4264fe8eeb366498f8586a58c8db26eae5262b397f72505bbe04", 364519, 15139, "ac46347808f65881521afde0ccb208c7251e31c6d48877ed746b17de1891fce1", "9f2ec568770e343f10b490460e2c14a7f063457538e56c07cec763ca8b31b108"),
    (39, "Premier League", "DETAIL", "90ddcef48350d19faf5e2c81cffa5e60668d0bd4d5f62293634db015492be188", "ad5b9d6d7a270488a2d65ed86150d32f7b13ac88aabb88e7157e720815815eab", "e06b5e274465ca2cd7ea052356026935737ca9771c4a7b6d2275602df9f17847", 754942, 68690, "e0ad96873a86ad878c222dc592e05320a33de3bf4a065f497179361ec52cddf8", "1431d7d9ecbecd1bc022c74e852eeb3382576b4b3ae45f80bdfabdc5d112f333"),
    (61, "Ligue 1", "CENSUS", "d7ac674b7b17398d0c3d36e2f603aabd76ac33bc154aa1e57fbbebcd18def6de", "9a61aab43ca928a9003000df6486a84344f7c84bd6f6ae5ea4c0414fac7b2007", "99ec540b33d5c4729517bbea00144d24ab3ce88a53e82cc9987f90d72779a7b2", 291497, 13121, "a4fc034de39e05985bbbbaf7f1b5844a6a90ac37b3adc2420c0c61749b8db98b", "41d1db0ec475fe28bb4c5a24ad4e5418264b84401dd1d2daaa45d8315eb95104"),
    (61, "Ligue 1", "DETAIL", "250b6e37fcafd8b525fd95c020dc1f223429a3efd77e5ed4a3582b13ca3da358", "fd8d90a354b08106b7d3d4c4ae485e23c13722db08f68899396aed8729e75c4a", "6a1681fd081e87e054b9ac5e602b1c1e61b29b1844f011d97f6770733c628802", 758509, 69909, "610e6896bc607b5a44f01c80d0eb2676eb57dfbe8a0c6082042d0b737b103a92", "413dab60441605282e0dbd2b58873cc3c0199e327783072264528c93004d7d5f"),
    (78, "Bundesliga", "CENSUS", "38b53b003e96340304c41358190f86d130b1448f7a8a7e8c0283c88fbc24e167", "7d69bf46be46d40754682fe3ace5cbcc5406a01becbde4ed386c4a19c6262bab", "328475700d0f70323d9bc4b50c73c3fff9eca71e9b2b1ba2f4602ae4c6ec7178", 295714, 12769, "fb12083a2732bd270c5b4b6281ef4c34297840ee535aee1a53f9559bb237252b", "dd558b83bcc987d6881b3745759054814b100c705f2b93dba9c07df4e5696962"),
    (78, "Bundesliga", "DETAIL", "2ed2103786c4121a4cdc85d1eacb1d6a7f88c5b29979cb0306f1009e9745b1ab", "4e9574abf14cc61096a2211d22fe6c9f4be28a69371d44fc1364d06e0831160e", "818e88c4158c010935070f7de73bbb27ff3d56adf3af6ce19a34c8dc4ff79ee1", 764807, 69616, "2238913576dbbd1a19d9eb7b7d90b83347f953ffbaf708c4252ecded89444ea1", "4269d41dfc49eaf4efe20d5e98ed70644709d2eca77bc97492ae0119aa3304dc"),
    (135, "Serie A", "CENSUS", "c9eab4bf8ca73dba0352a3ab144e25869d0b5e712c8376142f487b30dbaab6e9", "81e4cf5f807cfc1cd51daaf7aa111f35f7e509002a1e2654dddb4d0121e05141", "7e0d2118de9830e2c4460c8568ce8fcf6a88fb3956b753f4d633a8880a0b1abf", 359806, 16395, "adf19bdcf1e78c68fda9577c1c2b4860bbf6a94aa72f0d5ee8778475358531f9", "c76c74b72100b3d66f4a7d35fb4d85f36d6e6b5d02b82f4e353c94272e7a6c29"),
    (135, "Serie A", "DETAIL", "bc31d92bf0572f0b36dd6e20f4bfb6aed38503a798b5900bfc6b836fce4d84f9", "8291f5d8075eed364a1be1b16e74c8ca46383d3096ebd77af79df84fa5ffc277", "cce40ca5f89c211cee33527fb930c9d208c335a8304dad82ef9fdc3a7fbc5aed", 855947, 74752, "89ce270039a8367960e251caf376f4e42e2dfccde464dae70d5f637bd61043e5", "dbc3c30a572625e4b49a1c3719b9df17587f4f9d35ec19041369d8e1b73dd70a"),
    (140, "Liga", "CENSUS", "f110d9fa89f8f8cf9f81cb27c64fad9b92b3019b3526641a4a82e19d70060772", "821d17f7fbc0684598caff75087ac1603f36e90150d1485f641e48e3ed262cec", "f148e718d7095df35806ac9d319574e3aea91c8753cece4ad5f987545043afbe", 365417, 16852, "aac6f539267ea1f86ca846c40394a8dbca9b92ffe9c5925c1f4015b7203de42c", "26d7ff978d0930a51e6a27198164550e9078488b9e8cf40e7aab67be8cecffe5"),
    (140, "Liga", "DETAIL", "be6fc12ee202a377b417146e615c590a8ec4dfd59643d3472a691ca9be670cc4", "0a45bba4741e873a3e0774ee7e25a2e4808128eacc70d732fa7847bf6e7b8750", "e298c147ec9da03e69ef1c40243e41e052468fa4d2f043c218c247738d552ce0", 835204, 71168, "4a97eed00a58befc01f934b25c8ac97ff55a5dcebed4e196d634d921eed715f7", "8cf40adba1bf463c88aa0c357abf734ce0bdde27b13872e9dc7b10279956576d"),
]

# fixture id, competition id, label, kickoff, home id/name, away id/name,
# census fixture/source record hashes, detail fixture/source record hashes
FIXTURES = [
    (1208033, 39, "Premier League", "2024-08-24T11:30:00+00:00", 51, "Brighton", 33, "Manchester United", "816ddd68c2652f007843f3232fa4b2cbe8284ae9a37daf74b80d4a32668da2b8", "4558ec16622f17c5004e2fa7c6d5f4d291160871cfe8c89fc36ca55f6f1ddab2", "d0d2f38378a2b1dd7bf98bc430426932cbc530051153bf5db981405805583919", "3e43f2d1db2ea8d66c711858fb15bbb5a7dec19ef2806ce5f3fcf3359dc791ee"),
    (1208034, 39, "Premier League", "2024-08-24T14:00:00+00:00", 52, "Crystal Palace", 48, "West Ham", "dae0a4f8b1b1bec9be5255897901c662fd0ba9ac857a5b6ed69d261352c8ca54", "a9485867b1abe4acc46a9cd8acac0830835e0b79ac1d9c505c6fdef136295afa", "27ce599a0295ae69898629f40d221c20e52532d740953864fe23290bbd3fe95b", "b0b468b640dad9ab557a3cb5f0e38c7c1feb594e6448b9a187eb39b6de8f61db"),
    (1213756, 61, "Ligue 1", "2024-08-23T18:45:00+00:00", 85, "Paris Saint Germain", 82, "Montpellier", "4d9cfe5996842c745bfd63959f5ff12473c79b92ebe32e408b05cd1bba241bcc", "1f7fbf4d142b19bc93740aea837472619c0387b07079361b225ab02cb8db6c32", "c4b3cf60191ac2f392be0ace216b99b6c35147b904847284fa79cd84610e9f22", "569ad886b761ea4393aa0e7203bdfca50844e3f8efb5770c08cd17bbedae7ed1"),
    (1213763, 61, "Ligue 1", "2024-08-24T15:00:00+00:00", 80, "Lyon", 91, "Monaco", "3e6e267ed5305d65b47142fcd557cd866bbe83337cea08646cf2e68e9b5aebbc", "f19cec96098183110c8b711e5680d25f95a36ad1337feba309fba55d6da69ac8", "b375a8ffce1ecca45b9fc129eaf508041947677aa15c0b20ab8e888e873c96a9", "b70f2517b8aeb4c1bca237e333bdfaf06d855bb224a7af394ed34f282236a084"),
    (1223990, 78, "Bundesliga", "2024-08-30T18:30:00+00:00", 182, "Union Berlin", 186, "FC St. Pauli", "a510b23dda184ef9601e47834412d85e09801469884cbff2750fe230f00e152c", "537ec47193585e86937b08dba94e2099ccfb91eb091aaad5f45bb4af7f710d13", "c3943c953d58d642c1b3b30514c680df66b858984ed1f47059e12f3dd14ce6f6", "fbc548e3db4f7972405e04e019e5729c3d1b20983e623395b887f3db8cbf597e"),
    (1223985, 78, "Bundesliga", "2024-08-31T13:30:00+00:00", 172, "VfB Stuttgart", 164, "FSV Mainz 05", "be70b493b1750fc21eaedfd98dc7bb8b9bee505daf1e38c8559b44d91916fe49", "37562faedf332db0fd56ac01a21aa3fb697b2daadf33be7b706a43ee3f28f831", "703ac0aafd2082ea197562c9e56b9a24f3a7e91b9d729f1e78b1be4a14487f25", "5877ce8c04e64852e18f7368d0fcbb173da9a40f64577fb8040470471848801a"),
    (1223611, 135, "Serie A", "2024-08-24T16:30:00+00:00", 523, "Parma", 489, "AC Milan", "76fca8246834d07bd53ace7a016a2e724d05ac40762784a4a3a337e02ece9584", "6220cea440645b451886728d2eb9f0648ca18aaeac8a52b60abaa75fb1127f06", "cb6258728a86352b2be4799a5f2c277858aa472f6a7a9a3ce9b82021e282acf9", "bae4bafdf422ce4c9b860200f6ae405f8b855ea52731ae146bffbc8ad23eee3b"),
    (1223614, 135, "Serie A", "2024-08-24T16:30:00+00:00", 494, "Udinese", 487, "Lazio", "6c87c887fc5b92000cd307ae6ad2303f7f277cb523f6c9591e14c495631c826b", "e2fefa65b60556a8e8dac429bb7eeedef7bbd4c86761f400d97525299f8eb71c", "e451e06f19afa7732a448af509867ef1c18620a9d7654cf4f66f56e258876621", "02a9065a2ac8b84d7db5d0dd45877fa52794a3531311cd80ca159c08c5262dbb"),
    (1208504, 140, "Liga", "2024-08-23T17:00:00+00:00", 538, "Celta Vigo", 532, "Valencia", "45a9ed2aa0707b13c660db7db335a3538bcce9afed5a232bd81f7df5df0057c4", "dea86f0a5572f884742aff1af7125121771b7546b4166630e95967fd42ea1e05", "cb2cde67dc9717a10b631d3f64bb2977bf7b5ae6bd62a28e7233d83c8affb694", "e9ecf8d397547a4e98122293a72ade0a24a590f5ff0f9da5e01aae3c3c901905"),
    (1208507, 140, "Liga", "2024-08-23T19:30:00+00:00", 536, "Sevilla", 533, "Villarreal", "0fe018aa3948945c305181f00910d1bf96c0ee4b1b8250bfef4ccca554b35f1b", "76a90a90b61e8a230f0fb70abec11b93a94e0516cbcd56d92a9a1e14dd6753a5", "cd2e0a0cdd2fd3b9be58741321b78e40d8863b55cbfb4eaaeb71c604f72667b6", "5fbe83c46153604dcc83956b13727d44621b7953f244fc3724b0f9b488001a05"),
]

ARTIFACTS = [
    (39, 8875626108, "historical-deep-74d-current-r2-gate-batch-0105-30853757779-1", "sha256:b17053675296d10014386636921e57a4e3fc9b79d639dbb2d90a5920f6f4d0a9"),
    (61, 8875918562, "historical-deep-74d-current-r2-gate-batch-0142-30853757779-1", "sha256:df2759c22473640146c51034603be8c549c72ff56773d73f8573603d9f58bfed"),
    (78, 8876203323, "historical-deep-74d-current-r2-gate-batch-0179-30853757779-1", "sha256:2be7c17d8bc245cd60e4f2c6dfd4074e0c36189a1c7a28e12c3e458248d26625"),
    (135, 8875016575, "historical-deep-74d-current-r2-gate-batch-0031-30853757779-1", "sha256:f585a2de9b783b14f78214e3904e4bc9f20ec4bd8d1db19e32b6484e60906d9f"),
    (140, 8875329908, "historical-deep-74d-current-r2-gate-batch-0068-30853757779-1", "sha256:67a0f609253a84cce832b8a553104e8626a925f6ca18b6303fb9cfbce729fe4c"),
]


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8").replace("\r\n", "\n") != payload:
        raise RuntimeError(f"E1B_FROZEN_OUTPUT_DRIFT:{path}")
    path.write_text(payload, encoding="utf-8", newline="\n")


def _objects() -> list[dict[str, Any]]:
    result = []
    for (
        competition_id,
        competition,
        role,
        object_id,
        payload_hash,
        stored_hash,
        logical_bytes,
        stored_bytes,
        receipt_id,
        receipt_hash,
    ) in SOURCES:
        prefix = (
            "historical-deep-data/schema-v1/"
            f"competition=api-football:{competition_id}/season=2024/"
            f"family=fixtures/endpoint=fixtures/task={receipt_id}"
        )
        result.append(
            {
                "competition": competition,
                "competition_id": competition_id,
                "family": "fixtures",
                "historical_collection_provider_calls": 1,
                "logical_bytes": logical_bytes,
                "object_id": object_id,
                "payload_key": f"{prefix}/payload-{payload_hash}.json.gz",
                "payload_sha256": payload_hash,
                "receipt_hash": receipt_hash,
                "receipt_id": receipt_id,
                "receipt_key": f"{prefix}/receipt.json",
                "season": 2024,
                "source_role": role,
                "stored_bytes": stored_bytes,
                "stored_sha256": stored_hash,
            }
        )
    return result


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    allowed = [
        "TEAM", "TEAM_FORM", "PLAYER", "PLAYER_FORM", "LINEUP", "FORMATION",
        "STARTER_BASELINE", "EVENTS", "TEAM_STATISTICS", "PLAYER_STATISTICS",
        "DISCIPLINE_GENERIC", "INJURY_CONFIRMED", "SUSPENSION_CONFIRMED",
        "ABSENCE_GENERIC", "CALENDAR", "FATIGUE", "STANDINGS",
    ]
    mission = {
        "allowed_capabilities": allowed,
        "capability_contract_hash": "aa6f60694b7bfe1684c6fcf0faf1bbbc6fa1bb9f1001f06fee999451d1d011e8",
        "competition_count": 5,
        "external_effects": {
            "api_football_calls": 0, "deployments": 0, "odds_credits": 0,
            "promotion": False, "publications": 0, "r2_deletes": 0,
            "r2_head": 0, "r2_list": 0, "r2_writes": 0,
            "real_bets": False, "remote_sql_queries": 0,
        },
        "final_decision_ceiling": "PASS_AND_HOLD",
        "fixture_count": 10,
        "fixture_count_per_league": 2,
        "grain_catalog_hash": "5b2581e7d3a4630fd9d84be6ca954dc63cae83a602fce91d68c4847c5498cd71",
        "launch_readiness_hash": "76638a197e8bb0d0a6a9c20c6c51011c3bc39f5e0ab2e744f6964286bc78a316",
        "manifest_role": "IMMUTABLE_E1B_EXACT_KEY_EXECUTION_AUTHORITY",
        "mission_id": MISSION_ID,
        "odds_credit_budget": 0,
        "provider_budget": 0,
        "r2_byte_budget": 7244155,
        "r2_get_budget": 2000,
        "r2_write_budget": 0,
        "retry_policy": {
            "first_failure": "DIAGNOSE_AND_APPLY_MINIMAL_FIX_AT_SAME_SCOPE",
            "maximum_technical_attempts": 2,
            "scope_expansion_allowed": False,
            "second_similar_failure": "E1B_TECHNICAL_PARTIAL",
        },
        "schema_version": "p0-e1b-five-league-canary-v1",
        "season_policy": {
            "basis": "COMMON_P0_SEASON_WITH_VERIFIED_INVENTORY_AND_IDEMPOTENT_PASS_2_PROJECTION",
            "cross_league_season_uniform": True,
            "selected_season": 2024,
        },
        "selection_policy": SELECTION_POLICY,
        "source_main_sha": SOURCE_MAIN,
        "sql_budget": 0,
        "stage": "E1B",
        "stop_conditions": [
            "E2_FORBIDDEN", "R2_GET_BUDGET_EXCEEDED", "R2_BYTE_BUDGET_EXCEEDED",
            "ANY_R2_WRITE_OR_DELETE", "ANY_PROVIDER_CALL", "ANY_REMOTE_SQL_QUERY",
            "ANY_ODDS_CREDIT", "UNLISTED_R2_KEY", "MISSING_RECEIPT_OR_HASH",
            "IDENTITY_AMBIGUITY", "SECOND_SIMILAR_TECHNICAL_FAILURE",
        ],
        "stopped_capabilities": ["ABSENCE_CAUSE_EXACT"],
        "time_budget": {
            "maximum_hours": 8,
            "maximum_job_minutes": 15,
            "target_hours": [2, 6],
        },
    }
    objects = _objects()
    fixture_rows = []
    for row in FIXTURES:
        (
            fixture_id, competition_id, competition, kickoff, home_id, home_name,
            away_id, away_name, census_fixture_hash, census_source_hash,
            detail_fixture_hash, detail_source_hash,
        ) = row
        sources = [
            item for item in objects if item["competition_id"] == competition_id
        ]
        fixture_rows.append(
            {
                "allowed_object_ids": [item["object_id"] for item in sources],
                "allowed_r2_keys": [
                    key
                    for item in sources
                    for key in (item["receipt_key"], item["payload_key"])
                ],
                "away_team_display_name": away_name,
                "away_team_id": away_id,
                "competition": competition,
                "competition_id": competition_id,
                "fixture_id": fixture_id,
                "fixture_record_hashes": {
                    sources[0]["payload_sha256"]: census_fixture_hash,
                    sources[1]["payload_sha256"]: detail_fixture_hash,
                },
                "home_team_display_name": home_name,
                "home_team_id": home_id,
                "identity_policy": "PROVIDER_ID_VERIFIED_NON_POSITIONAL",
                "kickoff_utc": kickoff,
                "payload_hashes": [item["payload_sha256"] for item in sources],
                "receipt_hashes": [item["receipt_hash"] for item in sources],
                "round": "Regular Season - 2",
                "season": 2024,
                "selection_reason": (
                    "Earliest finished round-two fixture where both teams have "
                    "a prior finished league fixture in the common 2024 season."
                ),
                "source_record_hashes": {
                    sources[0]["payload_sha256"]: census_source_hash,
                    sources[1]["payload_sha256"]: detail_source_hash,
                },
                "status": "FT",
            }
        )
    selection = {
        "budgets": {
            "odds_credits": 0,
            "planned_bootstrap_bytes_upper_bound": 4194304,
            "planned_bootstrap_gets": 1,
            "planned_evidence_gets": 20,
            "planned_logical_gets_total": 21,
            "planned_network_bytes_upper_bound": 7244155,
            "planned_payload_stored_bytes": 428411,
            "planned_receipt_bytes_upper_bound": 2621440,
            "provider_calls": 0,
            "r2_byte_budget": 7244155,
            "r2_deletes": 0,
            "r2_get_budget": 2000,
            "r2_writes": 0,
            "remote_sql_queries": 0,
        },
        "cross_league_season_uniform": True,
        "fixtures": fixture_rows,
        "frozen_at": "2026-08-07T11:10:00Z",
        "gate": {
            "allowed_decisions": ["E1B_SELECTION_READY", "E1B_SELECTION_BLOCKED"],
            "mechanical_checks": {
                "ambiguous_identities": 0, "budget_within_limits": True,
                "competition_count": 5, "fixture_count": 10,
                "fixture_count_per_league": 2, "missing_keys": 0,
                "missing_payload_hashes": 0, "missing_receipt_hashes": 0,
                "provider_fallbacks": 0, "unlisted_keys": 0,
                "write_or_delete_methods_imported": 0,
            },
            "review_status": "PENDING_DP6_C2_DP5",
        },
        "mission_id": MISSION_ID,
        "ordering": ["competition_id", "season", "kickoff_utc", "fixture_id"],
        "schema_version": "p0-e1b-selection-manifest-v1",
        "season": 2024,
        "selection_policy": SELECTION_POLICY,
        "selection_source": {
            "idempotent_projection_artifacts": [
                {
                    "artifact_id": artifact_id, "competition_id": competition_id,
                    "digest": digest, "name": name,
                }
                for competition_id, artifact_id, name, digest in ARTIFACTS
            ],
            "inventory_durable_key": (
                "historical-deep-data/schema-v1/_derived/replay/inventories/"
                "continuation=p0-closure-30622258001-1/"
                "inventory=87326eba00976c8cdd00c68e7d24b98c1ccd4f109b38681228f527bcb273e28d/"
                "manifest.json.gz"
            ),
            "inventory_manifest_sha256": "87326eba00976c8cdd00c68e7d24b98c1ccd4f109b38681228f527bcb273e28d",
            "recovery_artifact": {
                "artifact_id": 8871763918,
                "authoritative": False,
                "digest": "sha256:9d6562d30502570614f8c68a7d0c72325398a43071026e7f7bcf9c633dad6864",
                "github_run_id": 30853757779,
                "name": "historical-deep-74a-current-r2-gate-30853757779-1",
                "purpose": "READ_ONLY_SELECTION_CROSS_CHECK",
            },
            "replay_head_sha": "f489971c03b53e9ea1381655f1591328ed055d41",
            "replay_pass": 2,
        },
        "source_main_sha": SOURCE_MAIN,
        "source_objects": objects,
        "stage": "E1B",
    }
    return mission, selection


def main() -> None:
    mission, selection = build()
    _write(ROOT / "configs/execution/p0-e1b-five-league-canary-v1.json", mission)
    _write(
        ROOT / "reports/evidence/e1b/e1b-selection-manifest-v1.json",
        selection,
    )


if __name__ == "__main__":
    main()
