"""Fail-closed production contracts for the Chronos V3 bootstrap."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, cast
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

import psycopg
from psycopg import Connection

from robin.recovery_v2_filesystem import (
    prepare_repository_directory as _recovery_v2_atomic_prepare_directory,
)
from robin.recovery_v2_filesystem import (
    publish_exclusive_bytes as _recovery_v2_atomic_publish_exclusive_bytes,
)
from robin.recovery_v2_filesystem import read_bytes as _recovery_v2_atomic_read_bytes
from robin.recovery_v2_filesystem import replace_bytes as _recovery_v2_atomic_replace_bytes

EXPECTED_REPOSITORY = "dddur75/robin-stades-ng"
EXPECTED_REF = "refs/heads/main"
EXPECTED_BEFORE_REVISION = "0013_historical_evidence_index"
EXPECTED_BEFORE_REVISIONS = (
    EXPECTED_BEFORE_REVISION,
    "0014_chronos_control_plane_v2",
)
EXPECTED_AFTER_REVISION = "0015_data_torrent_opportunity"
EXPECTED_ENVIRONMENT = "chronos-control-plane-production"
DATA_TORRENT_MISSION_ID = "data-torrent-ready-v1"
DATA_TORRENT_OWNER_DIRECTIVE_SHA256 = (
    "c03e218ca8f69d30f3fe998f7534d3edb11e2ba71bdd3ca022ada7ee08a2295d"
)
DATA_TORRENT_MISSION_MANIFEST_SHA256 = (
    "22e64bb33bd54aeeb528a416c7f6d0ca1c0719a27677302b8065249923ca96e7"
)
DATA_TORRENT_CONTROLLED_EFFECT_CONTRACT_SHA256 = (
    "9a9d44db699bfb39c5f8006b90ce6273a9de643be49c6e179487d4703fd09785"
)
DATA_TORRENT_ONE_SHOT_NOT_BEFORE = "2026-08-30T06:36:00Z"
DATA_TORRENT_LATEST_EFFECT_ADMISSION_AT = "2026-09-01T22:00:00Z"
DATA_TORRENT_MAXIMUM_EFFECT_RUNTIME_SECONDS = 3600
DATA_TORRENT_RECOVERY_V2_MISSION_ID = "data-torrent-recovery-v2"
DATA_TORRENT_RECOVERY_V2_START_SHA = "fcbf2a4fedd413251ee9da94ec2a444c6b917e63"
DATA_TORRENT_RECOVERY_V2_OWNER_DIRECTIVE_SHA256 = (
    "ff2e45ff7c6490919aa86900669c306e1d25c710f15db27f7c70861f1246bf31"
)
DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256 = (
    "ced1b867faa3ae57911d169f5c1edbd0db02a891ac46ccc080de7397076d349f"
)
DATA_TORRENT_RECOVERY_V2_MANIFEST_CANONICAL_SHA256 = (
    "e6ae2bcc2ea6a8cbd8a552321235f384b6776e935c259a0516ce1405ac2871b2"
)
DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_SHA256 = (
    "80bae46bbf0c4af0b223476265b283628e4950f298d09f5287ad450b367da7dc"
)
DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_CANONICAL_SHA256 = (
    "59c1c91071e8217b198de953cbc48a76e182234bc8e69f065bc14da1c496c7ee"
)
DATA_TORRENT_LIVE_V2_POSTGRESQL_CALL_GRAPH_SHA256 = (
    "8d6b14c1f9ab48b7a6b48a0ae1730b5abc3b93a9efc3ae0f21dd5f3fa083201c"
)
DATA_TORRENT_LIVE_V2_POSTGRESQL_CALL_GRAPH_CANONICAL_SHA256 = (
    "d89ddc3b202ba13b3eba1c7f678e142b5817afba954dd1d5e4119a587a6e0739"
)
DATA_TORRENT_RECOVERY_V2_NOT_BEFORE = "2026-08-30T12:46:58Z"
DATA_TORRENT_RECOVERY_V2_LATEST_EFFECT_ADMISSION_AT = "2026-09-06T12:26:58Z"
DATA_TORRENT_RECOVERY_V2_EXPIRES_AT = "2026-09-13T23:59:59Z"
DATA_TORRENT_RECOVERY_V2_MAXIMUM_EFFECT_RUNTIME_SECONDS = 1200
DATA_TORRENT_RECOVERY_V2_TIME_BUDGET_SECONDS = 604_800
DATA_TORRENT_RECOVERY_V2_TERMINAL_ATTESTATION_RESERVE_SECONDS = 210
DATA_TORRENT_RECOVERY_V2_EFFECT_DEADLINE_SECONDS_MAXIMUM = {
    "RECOVERY_IDENTITY_V2": 600,
    "DURABLE_IDENTITY_SEAL_V2": 600,
    "PRODUCTION_PREFLIGHT_V2": 900,
    "MIGRATE_0015": 900,
    "VERIFY_0015": 900,
    "LIVE_ONCE": 1_200,
}
DATA_TORRENT_RECOVERY_V2_POST_EFFECT_TERMINAL_GRACE_SECONDS = {
    "RECOVERY_IDENTITY_V2": 630,
    "DURABLE_IDENTITY_SEAL_V2": 630,
    "PRODUCTION_PREFLIGHT_V2": 930,
    "MIGRATE_0015": 930,
    "VERIFY_0015": 930,
    "LIVE_ONCE": 1_230,
}
DATA_TORRENT_RECOVERY_V2_ONE_WRITER_HOST_SHA256 = (
    "39c21f9875e88958cb2b695ef02ab92c126f687ff0d8c98df062f166a6dee7d3"
)
DATA_TORRENT_RECOVERY_V2_POSTMERGE_FINAL_GATE_PATH = (
    "scripts/verify_data_torrent_recovery_v2_postmerge_gate.py"
)
DATA_TORRENT_RECOVERY_V2_POSTMERGE_FINAL_GATE_WITNESS_SCHEMA = (
    "data-torrent-recovery-v2-final-gate-witness-v1"
)
DATA_TORRENT_RECOVERY_V2_POSTMERGE_FINAL_REPORT_SCHEMA = (
    "data-torrent-recovery-v2-terminal-report-v2"
)
DATA_TORRENT_RECOVERY_V2_SQL_CONTRACT_MARKER_PREFIX = "DATA_TORRENT_RECOVERY_V2_SQL_CONTRACT_V1:"
DATA_TORRENT_RECOVERY_V2_EXTERNAL_EFFECTS = (
    "git_remote_write_non_force_within_successor_pr_budget",
    "github_pull_request_write_up_to_3",
    "github_merge_commit_up_to_3",
    "github_actions_safe_v2_exact_head_and_postmerge_within_ci_budget",
    "github_api_read_and_artifact_download_bounded",
    "github_actions_production_workflow_enable_dispatch_disable_once_per_authorized_stage",
    "github_environment_secret_write_up_to_4",
    "neon_recovery_identity_get_up_to_25_mutations_0",
    "r2_identity_seal_put_up_to_1_get_up_to_1_object_up_to_1",
    "r2_preflight_exact_key_get_up_to_1",
    "neon_production_preflight_get_up_to_39_post_up_to_1_patch_0_delete_0",
    "neon_migrate_authority_validation_get_up_to_26_mutations_0",
    "neon_compute_wake_only_via_authorized_postgresql_stage",
    "postgresql_stage_bounded_preflight_verify_additive_migration_0015_and_live_ingest",
    "official_schedule_public_reads_up_to_50",
    "odds_provider_requests_up_to_5_and_credits_up_to_1000",
    "r2_live_exact_key_get_up_to_1_immutable_put_up_to_2_objects_up_to_2_list_0_delete_0_overwrite_0",
)
DATA_TORRENT_RECOVERY_V2_COUNCIL_ANCHOR_ID = "RCV3-20260830-193"
DATA_TORRENT_RECOVERY_V2_COUNCIL_ANCHOR_HASH = (
    "b7a3710d36025506af70355026b9033b3da9650a5c60dd6509a6b3121f1ec9dc"
)
DATA_TORRENT_RECOVERY_V2_INITIAL_RELEASE_ID = "RCV3-20260830-194"
DATA_TORRENT_RECOVERY_V2_INITIAL_RELEASE_HASH = (
    "e0a497c717222220ab7e2e1a8dc17529a08acf96000682465da9f4d659d77ffe"
)
DATA_TORRENT_RECOVERY_V2_FULL_SUITE_FAILURE_ID = "RCV3-20260830-195"
DATA_TORRENT_RECOVERY_V2_FULL_SUITE_FAILURE_HASH = (
    "be7d2db84891d723dfa82872bf9fd1e10ae3f26da3af4b977a5fac50ae8ed1ee"
)
DATA_TORRENT_RECOVERY_V2_BASE_RELEASE_ID = "RCV3-20260830-196"
DATA_TORRENT_RECOVERY_V2_BASE_RELEASE_HASH = (
    "71ee104830f589b2f0a07d8b0488a2277067285c76d4886b1d0ca69cf3d27573"
)
DATA_TORRENT_RECOVERY_V2_LEDGER_PREFIX_THROUGH_196_SHA256 = (
    "5e5b0aab97536908cbfcfbb4f364dbc41d1a882352f38097c355dae43926bc12"
)
DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_FAILURE_ID = "RCV3-20260831-197"
DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_FAILURE_HASH = (
    "c27f8627e6842f4f761b04340a4de20cba48738bed0a877dff7c07328434e013"
)
DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_RELEASE_ID = "RCV3-20260831-198"
DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_RELEASE_HASH = (
    "7fa669ba7cfd483ac83882c53cc89717810ae654197b95afd53bbb1052c30949"
)
DATA_TORRENT_RECOVERY_V2_LEDGER_PREFIX_THROUGH_198_SHA256 = (
    "6256c10acb2c1acc3fdb9a90ec8bb1561b8a557620e04c02d9465c158bf0d625"
)
DATA_TORRENT_RECOVERY_V2_LEDGER_PREFIX_THROUGH_200_SHA256 = (
    "aea44608a6f247ae4660d915ad425d412bd8644941e14561bfdf5e232ca03f44"
)
DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_RELEASE_ID = "RCV3-20260831-202"
DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_RELEASE_HASH = (
    "ecd424775b924de525b846a2fe512126ffd64ef9d89b7be39b20149d2752b2e9"
)
DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_REVIEWED_SNAPSHOT_SHA256 = (
    "66c3f26bce167666ab8d7af746b855ed2a00725b0fd7bcab272ec3e32c2f80b8"
)
DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_RUNTIME_SHA256 = (
    "28499766869ed7d2f24bc6b3257316610be0bff1f63ece5afea9c7f3bf072c47"
)
DATA_TORRENT_RECOVERY_V2_LEDGER_PREFIX_THROUGH_202_SHA256 = (
    "7709dce886d01c83570190863bc36b589d572af25574b75d6eae339872a86408"
)
DATA_TORRENT_RECOVERY_V2_POST_202_B101_FAILURE_HASH = (
    "ef8d75dd0303da10953dbb45e021b8ecba94fc60628433441afabd0f8dccf86f"
)
DATA_TORRENT_RECOVERY_V2_POST_202_B101_RELEASE_HASH = (
    "7a4c866dcd7666320e20640d47313d1d75c0e6fb58fe3bb2c67ee5775b861873"
)
DATA_TORRENT_RECOVERY_V2_POST_202_B101_REVIEWED_SNAPSHOT_SHA256 = (
    "15536e727660a602eeb3d70a0efa6ddfdb77ab92b4a8155937cc9b36243988ca"
)
DATA_TORRENT_RECOVERY_V2_POST_202_B101_RUNTIME_SHA256 = (
    "e45665fadd90259254ee5add998aff0bb332cd6828e26de74a19ef38784b0bd3"
)
DATA_TORRENT_RECOVERY_V2_LEDGER_PREFIX_THROUGH_204_SHA256 = (
    "f98bea40d1088140f69dbe1e57bb6b69582c506020ce889cb38054c7e94d9322"
)
DATA_TORRENT_RECOVERY_V2_GRAPH_CLAIMS_PREFIX_SHA256 = (
    "fda614b79d6fc7f31d3b7b2bd0db476ece9a2eb28d21f98bb5d9f4c1bdc78294"
)
DATA_TORRENT_RECOVERY_V2_GRAPH_NODES_PREFIX_SHA256 = (
    "06edb055c2fc5d6f557a0d371f8cd17a2eab9089b3249993ef8268b045dce3d0"
)
DATA_TORRENT_RECOVERY_V2_GRAPH_EDGES_PREFIX_SHA256 = (
    "ac100fdeb1bb1b073a6e48b43071aae2f544979b457bb525b46f55dfd44a6c0c"
)
DATA_TORRENT_RECOVERY_V2_STATIC_CORRECTION_REVIEWED_SNAPSHOT_SHA256 = (
    "7f9b63e9344c55d538a0a0ee4e12966ba004feabebdc814685ea138850b448cc"
)
DATA_TORRENT_RECOVERY_V2_STATIC_CORRECTION_RUNTIME_SHA256 = (
    "50e10c6e3640aaf3292cc66ccd6e7f2aea0dd975787832d7a1b4b8a046faa994"
)
DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_1_HEAD = (
    "a0a043f3222e467e6d904c90878be5718cac8ace"
)
DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_1_RUN_ID = 33420499802
DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_2_HEAD = (
    "21d6a928c5998cca86cebbb0dc078aba4cd20cb5"
)
DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_2_RUN_ID = 33433893502
DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_REVIEWED_SNAPSHOT_SHA256 = (
    "a1b409e7c2cb2c558df38e559eb4e0c8431ececc9b290de53025813925651421"
)
DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_RUNTIME_SHA256 = (
    "b0fde44d4a9a1187e99dab8ab28f31cc5f72ab64782cee1c11900bc5a7a6dd42"
)
DATA_TORRENT_RECOVERY_V2_LEDGER_PREFIX_THROUGH_195_SHA256 = (
    "79fa071386a747c8ea94a6cdcd4a0036116c1ceff5abdeee556acb99d5055419"
)
DATA_TORRENT_RECOVERY_V2_INITIAL_REVIEWED_SNAPSHOT_SHA256 = (
    "f66dfd42504975079f5e1cb2fbbac28eafe3e755b952dddf4eba643e647a000b"
)
DATA_TORRENT_RECOVERY_V2_INITIAL_REVIEW_PATHS = {
    "A2": "reports/council/data-torrent-recovery-v2-a2-review-v3.json",
    "C2": "reports/council/data-torrent-recovery-v2-c2-review-v3.json",
    "C4": "reports/council/data-torrent-recovery-v2-c4-review-v3.json",
    "DP6": "reports/council/data-torrent-recovery-v2-dp6-review-v3.json",
}
DATA_TORRENT_RECOVERY_V2_INITIAL_FINAL_REVIEW_PATH = (
    "reports/council/data-torrent-recovery-v2-final-review-v3.json"
)
DATA_TORRENT_RECOVERY_V2_REVIEW_PATHS = {
    "A2": "reports/council/data-torrent-recovery-v2-ci-correction-a2-review-v3.json",
    "C2": "reports/council/data-torrent-recovery-v2-ci-correction-c2-review-v3.json",
    "C4": "reports/council/data-torrent-recovery-v2-ci-correction-c4-review-v3.json",
    "DP6": "reports/council/data-torrent-recovery-v2-ci-correction-dp6-review-v3.json",
}
DATA_TORRENT_RECOVERY_V2_FINAL_REVIEW_PATH = (
    "reports/council/data-torrent-recovery-v2-ci-correction-final-review-v3.json"
)
DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_REVIEW_PATHS = {
    "A2": "reports/council/data-torrent-recovery-v2-post-196-correction-a2-review-v3.json",
    "C2": "reports/council/data-torrent-recovery-v2-post-196-correction-c2-review-v3.json",
    "C4": "reports/council/data-torrent-recovery-v2-post-196-correction-c4-review-v3.json",
    "DP6": "reports/council/data-torrent-recovery-v2-post-196-correction-dp6-review-v3.json",
}
DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_FINAL_REVIEW_PATH = (
    "reports/council/data-torrent-recovery-v2-post-196-correction-final-review-v3.json"
)
DATA_TORRENT_RECOVERY_V2_STATIC_CORRECTION_REVIEW_PATHS = {
    "A2": "reports/council/data-torrent-recovery-v2-post-198-static-correction-a2-review-v3.json",
    "C2": "reports/council/data-torrent-recovery-v2-post-198-static-correction-c2-review-v3.json",
    "C4": "reports/council/data-torrent-recovery-v2-post-198-static-correction-c4-review-v3.json",
    "DP6": "reports/council/data-torrent-recovery-v2-post-198-static-correction-dp6-review-v3.json",
}
DATA_TORRENT_RECOVERY_V2_STATIC_CORRECTION_FINAL_REVIEW_PATH = (
    "reports/council/data-torrent-recovery-v2-post-198-static-correction-final-review-v3.json"
)
DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_REVIEW_PATHS = {
    "A2": "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-1-a2-review-v3.json",
    "C2": "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-1-c2-review-v3.json",
    "C4": "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-1-c4-review-v3.json",
    "DP6": "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-1-dp6-review-v3.json",
}
DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_FINAL_REVIEW_PATH = (
    "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-1-final-review-v3.json"
)
DATA_TORRENT_RECOVERY_V2_POST_202_B101_REVIEW_PATHS = {
    "A2": "reports/council/data-torrent-recovery-v2-post-202-b101-correction-a2-review-v3.json",
    "C2": "reports/council/data-torrent-recovery-v2-post-202-b101-correction-c2-review-v3.json",
    "C4": "reports/council/data-torrent-recovery-v2-post-202-b101-correction-c4-review-v3.json",
    "DP6": "reports/council/data-torrent-recovery-v2-post-202-b101-correction-dp6-review-v3.json",
}
DATA_TORRENT_RECOVERY_V2_POST_202_B101_FINAL_REVIEW_PATH = (
    "reports/council/data-torrent-recovery-v2-post-202-b101-correction-final-review-v3.json"
)
DATA_TORRENT_RECOVERY_V2_CYCLE_2_CORRECTION_REVIEW_PATHS = {
    "A2": "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-2-correction-a2-review-v3.json",
    "C2": "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-2-correction-c2-review-v3.json",
    "C4": "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-2-correction-c4-review-v3.json",
    "DP6": "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-2-correction-dp6-review-v3.json",
}
DATA_TORRENT_RECOVERY_V2_CYCLE_2_CORRECTION_FINAL_REVIEW_PATH = (
    "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-2-correction-final-review-v3.json"
)
DATA_TORRENT_RECOVERY_V2_PR_B_REVIEW_PATHS = {
    "A2": "reports/council/data-torrent-recovery-v2-pr-b-a2-review-v3.json",
    "C2": "reports/council/data-torrent-recovery-v2-pr-b-c2-review-v3.json",
    "C4": "reports/council/data-torrent-recovery-v2-pr-b-c4-review-v3.json",
    "DP6": "reports/council/data-torrent-recovery-v2-pr-b-dp6-review-v3.json",
}
DATA_TORRENT_RECOVERY_V2_PR_B_FINAL_REVIEW_PATH = (
    "reports/council/data-torrent-recovery-v2-pr-b-final-review-v3.json"
)
DATA_TORRENT_RECOVERY_V2_TERMINAL_REVIEW_PATHS = {
    "A2": "reports/council/data-torrent-recovery-v2-terminal-a2-review-v3.json",
    "C2": "reports/council/data-torrent-recovery-v2-terminal-c2-review-v3.json",
    "C4": "reports/council/data-torrent-recovery-v2-terminal-c4-review-v3.json",
    "DP6": "reports/council/data-torrent-recovery-v2-terminal-dp6-review-v3.json",
}
DATA_TORRENT_RECOVERY_V2_TERMINAL_REPORT_PATH = (
    "reports/council/data-torrent-recovery-v2-terminal-report-v1.json"
)
DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR = (
    "reports/council/data-torrent-recovery-v2-terminal-evidence"
)
DATA_TORRENT_RECOVERY_V2_LIVE_BUNDLE_ATTESTATION_PATH = (
    f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/live-bundle-attestation-v2.json"
)
DATA_TORRENT_RECOVERY_V2_FINAL_QUIESCENCE_PATH = (
    f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/runtime-close-quiescence-v1.json"
)
DATA_TORRENT_RECOVERY_V2_STAGE_EVIDENCE_PATHS = {
    "RECOVERY_IDENTITY_V2": {
        "attestation": (
            f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/stages/"
            "recovery-identity-v2/github-artifact-attestation-v2.json"
        ),
        "payload": (
            f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/stages/"
            "recovery-identity-v2/neon-branch-identity-go-v2.json"
        ),
        "controller": (
            f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/stages/"
            "recovery-identity-v2/controller-cycle-v1.json"
        ),
    },
    "DURABLE_IDENTITY_SEAL_V2": {
        "attestation": (
            f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/stages/"
            "durable-identity-seal-v2/github-artifact-attestation-v2.json"
        ),
        "payload": (
            f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/stages/"
            "durable-identity-seal-v2/durable-identity-seal-v2.json"
        ),
        "controller": (
            f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/stages/"
            "durable-identity-seal-v2/controller-cycle-v1.json"
        ),
    },
    "PRODUCTION_PREFLIGHT_V2": {
        "attestation": (
            f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/stages/"
            "production-preflight-v2/github-artifact-attestation-v2.json"
        ),
        "payload": (
            f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/stages/"
            "production-preflight-v2/production-preflight-v2.json"
        ),
        "controller": (
            f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/stages/"
            "production-preflight-v2/controller-cycle-v1.json"
        ),
    },
    "MIGRATE_0015": {
        "attestation": (
            f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/stages/"
            "migrate-0015/github-artifact-attestation-v2.json"
        ),
        "payload": (
            f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/stages/"
            "migrate-0015/chronos-production-migrate-v2.json"
        ),
        "controller": (
            f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/stages/"
            "migrate-0015/controller-cycle-v1.json"
        ),
    },
    "VERIFY_0015": {
        "attestation": (
            f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/stages/"
            "verify-0015/github-artifact-attestation-v2.json"
        ),
        "payload": (
            f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/stages/"
            "verify-0015/chronos-production-verify-v2.json"
        ),
        "controller": (
            f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/stages/"
            "verify-0015/controller-cycle-v1.json"
        ),
    },
    "LIVE_ONCE": {
        "attestation": DATA_TORRENT_RECOVERY_V2_LIVE_BUNDLE_ATTESTATION_PATH,
        "payload": (
            f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/artifacts/"
            "torrent-real-batch-manifest-v1.json"
        ),
        "controller": (
            f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/stages/"
            "live-once/controller-cycle-v1.json"
        ),
    },
}
DATA_TORRENT_RECOVERY_V2_BINDINGS_EVIDENCE_PATH = (
    f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/stages/"
    "four-runtime-bindings/chronos-runtime-bindings-v2.json"
)
DATA_TORRENT_RECOVERY_V2_PROVIDER_EVIDENCE_PATH = (
    f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/stages/"
    "provider-neutralization/recovery-v2-provider-neutralization.json"
)
DATA_TORRENT_RECOVERY_V2_QUARANTINE_EVIDENCE_PATH = (
    f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/stages/"
    "postmerge-quarantine/recovery-v2-postmerge-quarantine.json"
)
DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH = (
    "reports/council/data-torrent-recovery-v2-terminal-intents/"
    "terminal-evidence-reservation-v1.json"
)
DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_EVIDENCE_PATH = (
    f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/invocation-reservation-v1.json"
)
DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_PATH = (
    "reports/council/data-torrent-recovery-v2-terminal-intents/"
    "delivery-observation-reservation-v1.json"
)
DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_EVIDENCE_PATH = (
    f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/"
    "delivery-observation-reservation-v1.json"
)
DATA_TORRENT_RECOVERY_V2_DELIVERY_EVIDENCE_PATH = (
    f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/delivery-receipt-v1.json"
)
_RECOVERY_V2_TERMINAL_ARTIFACT_NAMES = (
    "torrent-real-batch-manifest-v1.json",
    "torrent-real-batch-raw-index-v1.json",
    "torrent-real-batch-normalized-index-v1.json",
    "torrent-real-batch-quality-report-v1.json",
    "torrent-real-batch-coverage-matrix-v1.csv",
    "torrent-load-replay-report-v1.json",
    "torrent-load-replay-report-v1.md",
    "torrent-opportunity-claim-receipt-v1.json",
    "torrent-control-plane-event-chain-v1.json",
    "torrent-official-read-receipts-v1.json",
    "torrent-provider-credit-receipt-v1.json",
    "torrent-r2-inventory-v1.json",
    "torrent-raw-to-normalized-lineage-v1.json",
    "torrent-canonical-dataset-hash-v1.json",
    "torrent-qa-acceptance-matrix-v1.json",
    "robin-data-torrent-operations-pack-v1.md",
    "robin-data-torrent-recovery-pack-v1.md",
    "hypothesis-ready-field-dictionary-v1.json",
    "hypothesis-backlog-from-real-data-v1.md",
)
_RECOVERY_V2_TERMINAL_QA_GATES = (
    "baseline_identity",
    "cross_run_claim",
    "loser_replay_no_reads",
    "migration_rbac",
    "production_bindings",
    "ordering_one_shot",
    "ledger_caps",
    "forbidden_effects",
    "secret_safety",
    "temporal_safety",
    "scope_horizon",
    "official_breadth",
    "odds_breadth",
    "raw_durability",
    "normalization_lineage",
    "fixture_mapping_coverage",
    "replay",
    "load",
    "artifact_closure",
    "ops_recovery_science",
    "ci_merge_postmerge",
    "qa_terminal",
)
_RECOVERY_V2_TERMINAL_WORKFLOW_STAGES = {
    "RECOVERY_IDENTITY_V2": (
        ".github/workflows/chronos-neon-branch-identity-v2.yml",
        "NEON_BRANCH_IDENTITY_GO_V2",
        "neon-branch-identity-go-v2.json",
    ),
    "DURABLE_IDENTITY_SEAL_V2": (
        ".github/workflows/chronos-identity-seal-v2.yml",
        "DURABLE_IDENTITY_SEAL_V2",
        "durable-identity-seal-v2.json",
    ),
    "PRODUCTION_PREFLIGHT_V2": (
        ".github/workflows/chronos-production-bootstrap-v4.yml",
        "CHRONOS_MIGRATION_READY",
        "production-preflight-v2.json",
    ),
    "MIGRATE_0015": (
        ".github/workflows/chronos-production-bootstrap-v4.yml",
        "MIGRATE_0015_COMPLETE_V2",
        "chronos-production-migrate-v2.json",
    ),
    "VERIFY_0015": (
        ".github/workflows/chronos-production-bootstrap-v4.yml",
        "VERIFY_0015_COMPLETE_V2",
        "chronos-production-verify-v2.json",
    ),
    "LIVE_ONCE": (
        ".github/workflows/data-torrent-live-v2.yml",
        "DATA_TORRENT_READY",
        "torrent-real-batch-manifest-v1.json",
    ),
}
_RECOVERY_V2_BASE_RELEASE_CLAIM = (
    "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION.RELEASE.002"
)
_RECOVERY_V2_LOCAL_QA_FAILURE_CLAIM = (
    "GOV.DATA_TORRENT_RECOVERY.V2.E1.LOCAL_QA.FAILURE.001"
)
_RECOVERY_V2_LOCAL_CORRECTION_RELEASE_CLAIM = (
    "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION."
    "LOCAL_PRE_CI_CORRECTION.RELEASE.001"
)
_RECOVERY_V2_STATIC_QA_FAILURE_CLAIM = (
    "GOV.DATA_TORRENT_RECOVERY.V2.E1.PRECOMMIT.STATIC_RUNTIME_QA.FAILURE.001"
)
_RECOVERY_V2_STATIC_CORRECTION_RELEASE_CLAIM = (
    "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION."
    "PRECOMMIT_STATIC_RUNTIME_CORRECTION.RELEASE.001"
)
_RECOVERY_V2_EXACT_HEAD_CI_FAILURE_CLAIM = (
    "GOV.DATA_TORRENT_RECOVERY.V2.E1.EXACT_HEAD_SAFE_V2.CYCLE_1.FAILURE.001"
)
_RECOVERY_V2_EXACT_HEAD_CI_CORRECTION_RELEASE_CLAIM = (
    "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION."
    "EXACT_HEAD_SAFE_V2.CYCLE_1.CORRECTION.RELEASE.001"
)
_RECOVERY_V2_POST_202_B101_FAILURE_CLAIM = (
    "GOV.DATA_TORRENT_RECOVERY.V2.E1.PRECOMMIT."
    "BANDIT_SRC_ROBIN.B101.FAILURE.001"
)
_RECOVERY_V2_POST_202_B101_CORRECTION_RELEASE_CLAIM = (
    "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION.POSIX_ROLLBACK."
    "FAIL_CLOSED.CORRECTION.RELEASE.001"
)
_RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_FAILURE_CLAIM = (
    "GOV.DATA_TORRENT_RECOVERY.V2.E1.EXACT_HEAD_SAFE_V2.CYCLE_2.FAILURE.001"
)
_RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_CORRECTION_RELEASE_CLAIM = (
    "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION."
    "EXACT_HEAD_SAFE_V2.CYCLE_2.CORRECTION.RELEASE.001"
)
_RECOVERY_V2_PR_B_RELEASE_CLAIM = (
    "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION.RELEASE.003"
)
_RECOVERY_V2_RESERVATION_CLAIM = (
    "GOV.DATA_TORRENT_RECOVERY.V2.TERMINAL.RESERVED.001"
)
_RECOVERY_V2_PHASE_ONE_CLAIM = (
    "GOV.DATA_TORRENT_RECOVERY.V2.TERMINAL.PHASE_ONE.001"
)
_RECOVERY_V2_TERMINAL_CLAIM = "GOV.DATA_TORRENT_RECOVERY.V2.TERMINAL.CANDIDATE.001"


def _recovery_v2_phase_one_evidence_paths() -> tuple[str, ...]:
    """Return the exact committed runtime-evidence surface preceding delivery."""

    paths = {
        DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH,
        DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_PATH,
        DATA_TORRENT_RECOVERY_V2_FINAL_QUIESCENCE_PATH,
        DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_EVIDENCE_PATH,
        DATA_TORRENT_RECOVERY_V2_LIVE_BUNDLE_ATTESTATION_PATH,
        DATA_TORRENT_RECOVERY_V2_BINDINGS_EVIDENCE_PATH,
        DATA_TORRENT_RECOVERY_V2_PROVIDER_EVIDENCE_PATH,
        DATA_TORRENT_RECOVERY_V2_QUARANTINE_EVIDENCE_PATH,
        *(
            f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/artifacts/{name}"
            for name in _RECOVERY_V2_TERMINAL_ARTIFACT_NAMES
        ),
        *(
            relative
            for stage in DATA_TORRENT_RECOVERY_V2_STAGE_EVIDENCE_PATHS.values()
            for relative in stage.values()
        ),
    }
    result = tuple(sorted(paths))
    if len(result) != 43:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    return result
_RECOVERY_V2_TERMINAL_COMPLETION_STATES = (
    "engineering_complete",
    "runtime_ready",
    "neon_branch_identity_go",
    "durable_seal_verified",
    "migration_verified",
    "live_executed",
    "durability_verified",
    "replay_verified",
    "data_torrent_ready",
)
_RECOVERY_V2_REQUIRED_DISABLED_WORKFLOWS = (
    ".github/workflows/chronos-controlled-go-durable-seal-v1.yml",
    ".github/workflows/chronos-identity-seal-v2.yml",
    ".github/workflows/chronos-neon-branch-identity-v2.yml",
    ".github/workflows/chronos-neon-controlled-idle-wake-readonly-v1.yml",
    ".github/workflows/chronos-production-bootstrap-v3.yml",
    ".github/workflows/chronos-production-bootstrap-v4.yml",
    ".github/workflows/data-torrent-live-v1.yml",
    ".github/workflows/data-torrent-live-v2.yml",
)
_RECOVERY_V2_NONTERMINAL_RUN_COUNTS = {
    "requested": 0,
    "waiting": 0,
    "pending": 0,
    "queued": 0,
    "in_progress": 0,
}
_RECOVERY_V2_TERMINAL_ARTIFACT_PREFIXES = {
    "RECOVERY_IDENTITY_V2": "neon-branch-identity-go-v2-",
    "DURABLE_IDENTITY_SEAL_V2": "durable-identity-seal-v2-",
    "PRODUCTION_PREFLIGHT_V2": "production-preflight-v2-",
    "MIGRATE_0015": "chronos-production-migrate-v2-",
    "VERIFY_0015": "chronos-production-verify-v2-",
}
_RECOVERY_V2_CONTROLLER_ORDER = (
    "RECOVERY_IDENTITY_V2",
    "DURABLE_IDENTITY_SEAL_V2",
    "PRODUCTION_PREFLIGHT_V2",
    "MIGRATE_0015",
    "VERIFY_0015",
    "LIVE_ONCE",
)
_RECOVERY_V2_STAGE_EFFECT_FIELDS = frozenset(
    {
        "neon_gets",
        "neon_posts",
        "neon_patch",
        "neon_delete",
        "postgresql_connection_attempts_upper_bound",
        "postgresql_sql_statements_upper_bound",
        "postgresql_sql_write_statements_upper_bound",
        "postgresql_migrations",
        "postgresql_read_transactions_attempted",
        "postgresql_function_reads_attempted",
        "postgresql_mutating_function_calls_attempted",
        "postgresql_mutating_function_calls_completed",
        "postgresql_mutating_function_outcomes_ambiguous",
        "postgresql_possible_durable_mutations_upper_bound",
        "r2_puts",
        "r2_gets",
        "r2_objects",
        "r2_lists",
        "r2_deletes",
        "r2_overwrites",
        "r2_retries",
        "official_reads",
        "provider_requests",
        "provider_credits",
        "provider_retries",
        "secret_writes",
        "replay_external_effects",
        "automatic_retries",
        "purchases",
        "bet_calls",
        "hypotheses_generated",
        "edge_promotions",
        "social_publications",
        "synthetic_rows",
        "backfilled_rows",
        "leagues",
        "league_market_cells",
    }
)
_RECOVERY_V2_BOOTSTRAP_EFFECT_FIELDS = frozenset(
    {
        "effect_counter_certainty",
        "r2_gets",
        "r2_gets_exact",
        "r2_puts",
        "neon_gets",
        "neon_gets_exact",
        "neon_posts",
        "neon_posts_exact",
        "postgresql_connection_attempts",
        "postgresql_connection_attempts_exact",
        "recovery_branch_creations_upper_bound",
        "recovery_branch_creations_exact",
        "migration_dispatches",
        "migration_dispatches_exact",
        "sql_statements_upper_bound",
        "sql_statements_exact",
        "sql_write_statements_upper_bound",
        "sql_write_statements_exact",
        "automatic_retries",
        "provider_calls",
        "purchases",
        "secret_values_observed",
    }
)
_RECOVERY_V2_BOOTSTRAP_INTEGER_FIELDS = frozenset(
    {
        "r2_gets",
        "r2_puts",
        "neon_gets",
        "neon_posts",
        "postgresql_connection_attempts",
        "recovery_branch_creations_upper_bound",
        "migration_dispatches",
        "sql_statements_upper_bound",
        "sql_write_statements_upper_bound",
        "automatic_retries",
        "provider_calls",
        "purchases",
    }
)
DATA_TORRENT_RECOVERY_V2_RELEASE_EXCLUDED_PATHS = (
    "reports/council/decision-ledger.jsonl",
    "reports/evidence/evidence-graph.json",
)
DATA_TORRENT_RECOVERY_V2_RELEASE_PATHS = (
    ".gitattributes",
    ".github/workflows/chronos-identity-seal-v2.yml",
    ".github/workflows/chronos-neon-branch-identity-v2.yml",
    ".github/workflows/chronos-production-bootstrap-v4.yml",
    ".github/workflows/ci-safe-v2.yml",
    ".github/workflows/data-torrent-live-v2.yml",
    "alembic.ini",
    "configs/agents/agent-report-schema-v3.json",
    "configs/agents/mission-activation-matrix-v3.json",
    "configs/data/torrent-live-v2.json",
    "configs/execution/data-torrent-live-v2-postgresql-call-graph.json",
    "configs/execution/data-torrent-recovery-v2-effect-contract.json",
    "configs/execution/data-torrent-recovery-v2.json",
    "docs/operations/DATA-TORRENT-RECOVERY-V2.md",
    "migrations/env.py",
    "migrations/versions/0001_jalon1_foundation.py",
    "migrations/versions/0002_jalon2_shadow.py",
    "migrations/versions/0003_jalon4_durable_shadow.py",
    "migrations/versions/0004_jalon5_deep_data_factory.py",
    "migrations/versions/0005_jalon9_critical_closure.py",
    "migrations/versions/0006_jalon10_pattern_research_ledger.py",
    "migrations/versions/0007_jalon10_immutable_evidence.py",
    "migrations/versions/0008_jalon11_deep_football.py",
    "migrations/versions/0009_jalon12_prospective_observatory.py",
    "migrations/versions/0010_prequential_v1.py",
    "migrations/versions/0011_hypothesis_intelligence_v1.py",
    "migrations/versions/0012_universal_genome_v2.py",
    "migrations/versions/0013_historical_evidence_index.py",
    "migrations/versions/0014_chronos_control_plane_v2.py",
    "migrations/versions/0015_data_torrent_opportunity.py",
    "reports/council/data-torrent-recovery-v2-a2-review-v3.json",
    "reports/council/data-torrent-recovery-v2-c2-review-v3.json",
    "reports/council/data-torrent-recovery-v2-c4-review-v3.json",
    "reports/council/data-torrent-recovery-v2-ci-correction-a2-review-v3.json",
    "reports/council/data-torrent-recovery-v2-ci-correction-c2-review-v3.json",
    "reports/council/data-torrent-recovery-v2-ci-correction-c4-review-v3.json",
    "reports/council/data-torrent-recovery-v2-ci-correction-dp6-review-v3.json",
    "reports/council/data-torrent-recovery-v2-ci-correction-final-review-v3.json",
    "reports/council/data-torrent-recovery-v2-dp6-review-v3.json",
    "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-1-a2-review-v3.json",
    "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-1-c2-review-v3.json",
    "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-1-c4-review-v3.json",
    "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-1-dp6-review-v3.json",
    "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-1-final-review-v3.json",
    "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-2-correction-a2-review-v3.json",
    "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-2-correction-c2-review-v3.json",
    "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-2-correction-c4-review-v3.json",
    "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-2-correction-dp6-review-v3.json",
    "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-2-correction-final-review-v3.json",
    "reports/council/data-torrent-recovery-v2-final-review-v3.json",
    "reports/council/data-torrent-recovery-v2-post-196-correction-a2-review-v3.json",
    "reports/council/data-torrent-recovery-v2-post-196-correction-c2-review-v3.json",
    "reports/council/data-torrent-recovery-v2-post-196-correction-c4-review-v3.json",
    "reports/council/data-torrent-recovery-v2-post-196-correction-dp6-review-v3.json",
    "reports/council/data-torrent-recovery-v2-post-196-correction-final-review-v3.json",
    "reports/council/data-torrent-recovery-v2-post-198-static-correction-a2-review-v3.json",
    "reports/council/data-torrent-recovery-v2-post-198-static-correction-c2-review-v3.json",
    "reports/council/data-torrent-recovery-v2-post-198-static-correction-c4-review-v3.json",
    "reports/council/data-torrent-recovery-v2-post-198-static-correction-dp6-review-v3.json",
    "reports/council/data-torrent-recovery-v2-post-198-static-correction-final-review-v3.json",
    "reports/council/data-torrent-recovery-v2-post-202-b101-correction-a2-review-v3.json",
    "reports/council/data-torrent-recovery-v2-post-202-b101-correction-c2-review-v3.json",
    "reports/council/data-torrent-recovery-v2-post-202-b101-correction-c4-review-v3.json",
    "reports/council/data-torrent-recovery-v2-post-202-b101-correction-dp6-review-v3.json",
    "reports/council/data-torrent-recovery-v2-post-202-b101-correction-final-review-v3.json",
    "reports/evidence/evidence-graph.json",
    "requirements-chronos-canary.lock",
    "requirements-chronos-neon-readonly-v4.lock",
    "requirements-data-torrent.lock",
    "scripts/build_data_torrent_live_call_graph_v2.py",
    "scripts/check_chronos_github_hold_v3.py",
    "scripts/check_data_torrent_recovery_v2_scope.py",
    "scripts/check_no_tracked_absolute_paths.py",
    "scripts/chronos_live_path_artifact_guard_v2.py",
    "scripts/chronos_neon_branch_identity_v2.py",
    "scripts/chronos_neon_pure_readonly_preflight_v4.py",
    "scripts/chronos_production_bootstrap_v3.py",
    "scripts/chronos_production_recovery_v2.py",
    "scripts/dispatch_data_torrent_recovery_v2_stage.py",
    "scripts/github_release_attestation_v1.py",
    "scripts/github_release_attestation_v2.py",
    "scripts/install_chronos_runtime_bindings_v2.py",
    "scripts/materialize_data_torrent_recovery_v2_delivery_evidence.py",
    "scripts/materialize_data_torrent_recovery_v2_terminal_evidence.py",
    "scripts/recovery_v2_supervision.py",
    "scripts/run_chronos_dual_principal_ci_v2.py",
    "scripts/run_data_torrent_v2.py",
    "scripts/seal_chronos_identity_go_v2.py",
    "scripts/validate_data_torrent_recovery_v2_dispatch_envelope.py",
    "scripts/verify_data_torrent_recovery_v2_postmerge_gate.py",
    "src/robin/__init__.py",
    "src/robin/capture/__init__.py",
    "src/robin/capture/bootstrap_contracts.py",
    "src/robin/capture/contracts.py",
    "src/robin/capture/fixture_mapping.py",
    "src/robin/capture/global_claim_boundary.py",
    "src/robin/capture/harness.py",
    "src/robin/capture/live_contracts.py",
    "src/robin/capture/live_executor.py",
    "src/robin/capture/live_storage.py",
    "src/robin/capture/live_transport.py",
    "src/robin/capture/normalization.py",
    "src/robin/capture/official_schedule_sources.py",
    "src/robin/capture/owner_review_pack.py",
    "src/robin/capture/provider_network.py",
    "src/robin/capture/storage.py",
    "src/robin/capture/workspace_bootstrap.py",
    "src/robin/chronos_alembic.py",
    "src/robin/chronos_production.py",
    "src/robin/chronos_role_lifecycle.py",
    "src/robin/data_torrent/__init__.py",
    "src/robin/data_torrent/archive.py",
    "src/robin/data_torrent/claims.py",
    "src/robin/data_torrent/contracts.py",
    "src/robin/data_torrent/durability.py",
    "src/robin/data_torrent/live_call_graph.py",
    "src/robin/data_torrent/normalization.py",
    "src/robin/data_torrent/reporting.py",
    "src/robin/data_torrent/runtime.py",
    "src/robin/data_torrent/sources.py",
    "src/robin/deep_football/__init__.py",
    "src/robin/deep_football/contracts.py",
    "src/robin/deep_football/matchups.py",
    "src/robin/market_math/__init__.py",
    "src/robin/market_math/devig.py",
    "src/robin/market_math/truth.py",
    "src/robin/prospective_observatory/__init__.py",
    "src/robin/prospective_observatory/budgets.py",
    "src/robin/prospective_observatory/chronos_control_plane.py",
    "src/robin/prospective_observatory/chronos_postgres.py",
    "src/robin/prospective_observatory/chronos_r2.py",
    "src/robin/prospective_observatory/contracts.py",
    "src/robin/prospective_observatory/gates.py",
    "src/robin/prospective_observatory/hypotheses.py",
    "src/robin/prospective_observatory/ledger.py",
    "src/robin/prospective_observatory/r2.py",
    "src/robin/prospective_observatory/replay.py",
    "src/robin/prospective_observatory/temporal.py",
    "src/robin/recovery_v2_filesystem.py",
    "src/robin/storage/__init__.py",
    "src/robin/storage/database.py",
    "src/robin/storage/hypothesis_models.py",
    "src/robin/storage/models.py",
    "src/robin/storage/prequential_models.py",
    "src/robin/storage/prospective_models.py",
    "tests/activation/test_chronos_controlled_go_durable_seal_v1.py",
    "tests/activation/test_chronos_end_to_end_live_path_v1.py",
    "tests/activation/test_chronos_identity_seal_v2.py",
    "tests/activation/test_chronos_migrate_verify_v2.py",
    "tests/activation/test_chronos_neon_branch_identity_v2.py",
    "tests/activation/test_chronos_neon_controlled_idle_wake_readonly_v1.py",
    "tests/activation/test_chronos_neon_pure_readonly_preflight_v4.py",
    "tests/activation/test_chronos_production_bootstrap_v3.py",
    "tests/activation/test_chronos_production_preflight_v2.py",
    "tests/activation/test_chronos_runtime_bindings_v1.py",
    "tests/activation/test_chronos_runtime_bindings_v2.py",
    "tests/activation/test_github_release_attestation_v2.py",
    "tests/activation/test_recovery_v2_atomic_evidence.py",
    "tests/activation/test_recovery_v2_dispatch_envelope.py",
    "tests/activation/test_recovery_v2_supervision.py",
    "tests/chronos/test_chronos_control_plane_v2.py",
    "tests/chronos/test_chronos_dual_principal_v2.py",
    "tests/chronos/test_chronos_r2_effects_v2.py",
    "tests/council/test_data_torrent_recovery_v2_governance.py",
    "tests/council/test_real_execution_bootstrap_governance.py",
    "tests/council/test_robin_council_os_v3.py",
    "tests/data_torrent/test_ci_lock_contract_v1.py",
    "tests/data_torrent/test_contracts_normalization_v1.py",
    "tests/data_torrent/test_data_torrent_replay_v2.py",
    "tests/data_torrent/test_live_seal_provenance_v2.py",
    "tests/data_torrent/test_postgresql_v1.py",
    "tests/data_torrent/test_source_effect_lineage_v1.py",
    "tests/jalon12/test_pilot_bridge_security.py",
    "tests/portability/test_no_tracked_absolute_paths.py",
)


def data_torrent_recovery_v2_sql_contract_marker(function_definition: str) -> str:
    """Bind the deployed marker to the exact PostgreSQL 16 function definition."""

    if not function_definition:
        raise ChronosProductionError("CHRONOS_TORRENT_SQL_CONTRACT_DEFINITION_INVALID")
    return (
        DATA_TORRENT_RECOVERY_V2_SQL_CONTRACT_MARKER_PREFIX
        + hashlib.sha256(function_definition.encode("utf-8")).hexdigest()
    )


MIGRATION_TARGET = EXPECTED_AFTER_REVISION
SCOPED_LOGINS = (
    (
        "chronos_authority_runtime_login",
        "chronos_authority_executor",
        "CHRONOS_AUTHORITY_DATABASE_URL",
    ),
    (
        "chronos_effect_runtime_login",
        "chronos_runtime_writer",
        "CHRONOS_RUNTIME_DATABASE_URL",
    ),
    (
        "chronos_reader_login",
        "chronos_reader",
        "CHRONOS_READER_DATABASE_URL",
    ),
)
PRODUCTION_SAFETY_LOCKS = {
    "STORAGE_PAUSED": "true",
    "P3_P4_PAUSED": "true",
    "PRODUCTION_LOCKED": "true",
    "REAL_BETS": "false",
    "NO_BET_DEFAULT": "true",
    "PROMOTION_LOCKED": "true",
    "SOCIAL_PUBLISHING_ENABLED": "false",
    "DEMO_MODE_ENABLED": "false",
    "POSTGRESQL_PRODUCTION_DESTRUCTIVE_WRITES": "false",
    "THE_ODDS_API_HISTORICAL_CREDITS": "false",
    "API_FOOTBALL_CALLS_ALLOWED": "0",
}

_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID = re.compile(r"^[1-9][0-9]{0,17}$")
_SAFE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_SAFE_NEON_HOST = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)*\.neon\.tech$")
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")
_GENERATION_PASSWORD_ENTROPY = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_SAFE_SSL_MODES = frozenset({"require", "verify-ca", "verify-full"})
_SAFE_QUERY_KEYS = frozenset({"sslmode", "channel_binding"})
_LIBPQ_ENVIRONMENT = re.compile(r"^PG[A-Z0-9_]+$")


def _is_neon_pooler_host(host: str) -> bool:
    return host.split(".", 1)[0].endswith("-pooler")


def libpq_environment_variable_names(
    environment: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Return only ambient libpq variable names, never their values."""

    source = os.environ if environment is None else environment
    return tuple(
        sorted(
            {
                name.upper()
                for name in source
                if _LIBPQ_ENVIRONMENT.fullmatch(name.upper()) is not None
            }
        )
    )


def require_libpq_environment_clean() -> None:
    if libpq_environment_variable_names():
        raise ChronosProductionError("CHRONOS_LIBPQ_ENVIRONMENT_FORBIDDEN")


def connect_direct_postgres(
    database_url: str,
    *,
    connector: Callable[..., Connection[Any]] = psycopg.connect,
) -> Connection[Any]:
    """Open one canonical direct connection without ambient libpq influence."""

    target = validate_direct_postgres_url(database_url)
    require_libpq_environment_clean()
    return connector(
        database_url,
        host=target.host,
        port=target.port,
        dbname=target.database,
        user=target.username,
        sslmode=target.sslmode,
        channel_binding=target.channel_binding,
        connect_timeout=10,
    )


class ChronosProductionError(RuntimeError):
    """A sanitized fail-closed production contract error."""


def _exact_integer_fields(
    value: Mapping[str, object],
    fields: set[str] | frozenset[str],
) -> bool:
    """Reject JSON booleans at every counter boundary (`bool` subclasses `int`)."""

    return all(type(value.get(field)) is int for field in fields)


def _json_exact_equal(left: object, right: object) -> bool:
    """Compare JSON values without Python's ``True == 1`` coercion."""

    return json.dumps(
        left,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) == json.dumps(
        right,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _recovery_v2_council_timestamp_is_canonical(value: object) -> bool:
    """Require the append-only Council timestamp's exact second-resolution form."""

    return isinstance(value, str) and re.fullmatch(
        r"20[0-9]{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
        r"T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z",
        value,
    ) is not None


def _authority_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ChronosProductionError(f"CHRONOS_MISSION_AUTHORITY_{field.upper()}_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ChronosProductionError(f"CHRONOS_MISSION_AUTHORITY_{field.upper()}_INVALID") from None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ChronosProductionError(f"CHRONOS_MISSION_AUTHORITY_{field.upper()}_INVALID")
    return parsed.astimezone(UTC)


_RECOVERY_V2_AGENT_REPORT_FIELDS = frozenset(
    {
        "agent_id",
        "mission_id",
        "facts_verified",
        "unknowns",
        "assumptions",
        "main_objection",
        "risks",
        "minimum_decisive_test",
        "recommended_action",
        "scale_condition",
        "estimated_compute",
        "estimated_external_cost",
        "estimated_human_time",
        "maintenance_impact",
        "confidence",
    }
)


def _recovery_v2_unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON key")
        document[key] = value
    return document


def _recovery_v2_path_is_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    is_junction = getattr(path, "is_junction", None)
    return bool(attributes & reparse_flag) or path.is_symlink() or (
        callable(is_junction) and bool(is_junction())
    )


_RecoveryV2DirectoryIdentity = tuple[int, int, int, int]


def _recovery_v2_directory_identity(
    path: Path,
    *,
    repository_root: Path,
) -> _RecoveryV2DirectoryIdentity:
    """Return a stable identity for one existing no-reparse repository directory."""

    root, candidate = _recovery_v2_require_no_reparse_chain(
        path,
        repository_root=repository_root,
        allow_missing_leaf=False,
    )
    try:
        metadata = candidate.lstat()
        resolved_root = root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
    except OSError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_MISSING") from None
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    identity = (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(stat.S_IFMT(metadata.st_mode)),
        attributes,
    )
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or identity[1] <= 0
        or _recovery_v2_path_is_reparse(candidate)
        or not resolved.is_relative_to(resolved_root)
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    return identity


def _recovery_v2_require_directory_identity(
    path: Path,
    expected: _RecoveryV2DirectoryIdentity,
    *,
    repository_root: Path,
) -> None:
    """Fail closed if a repository directory was exchanged after validation."""

    if _recovery_v2_directory_identity(path, repository_root=repository_root) != expected:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")


def _recovery_v2_fsync_repository_directory(
    path: Path,
    expected: _RecoveryV2DirectoryIdentity,
    *,
    repository_root: Path,
) -> None:
    """Durably flush a directory after revalidating the exact opened directory identity."""

    _recovery_v2_require_directory_identity(
        path,
        expected,
        repository_root=repository_root,
    )
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class _ByHandleFileInformation(ctypes.Structure):
            _fields_ = [
                ("file_attributes", wintypes.DWORD),
                ("creation_time_low", wintypes.DWORD),
                ("creation_time_high", wintypes.DWORD),
                ("access_time_low", wintypes.DWORD),
                ("access_time_high", wintypes.DWORD),
                ("write_time_low", wintypes.DWORD),
                ("write_time_high", wintypes.DWORD),
                ("volume_serial_number", wintypes.DWORD),
                ("file_size_high", wintypes.DWORD),
                ("file_size_low", wintypes.DWORD),
                ("number_of_links", wintypes.DWORD),
                ("file_index_high", wintypes.DWORD),
                ("file_index_low", wintypes.DWORD),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.GetFileInformationByHandle.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ByHandleFileInformation),
        ]
        kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
        kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
        kernel32.FlushFileBuffers.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateFileW(
            str(path),
            0x40000000,  # GENERIC_WRITE
            0x00000007,  # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
            None,
            3,  # OPEN_EXISTING
            0x02200000,  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
            None,
        )
        invalid_handle = wintypes.HANDLE(-1).value
        if handle in (None, invalid_handle):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        try:
            information = _ByHandleFileInformation()
            if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(information)):
                raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
            opened_inode = (int(information.file_index_high) << 32) | int(
                information.file_index_low
            )
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            directory_flag = getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10)
            if (
                opened_inode != expected[1]
                or information.file_attributes & reparse_flag
                or not information.file_attributes & directory_flag
            ):
                raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
            _recovery_v2_require_directory_identity(
                path,
                expected,
                repository_root=repository_root,
            )
            if not kernel32.FlushFileBuffers(handle):
                raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        finally:
            kernel32.CloseHandle(handle)
        return

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    try:
        metadata = os.fstat(descriptor)
        opened = (
            int(metadata.st_dev),
            int(metadata.st_ino),
            int(stat.S_IFMT(metadata.st_mode)),
            int(getattr(metadata, "st_file_attributes", 0)),
        )
        if opened != expected:
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        _recovery_v2_require_directory_identity(
            path,
            expected,
            repository_root=repository_root,
        )
        os.fsync(descriptor)
    except OSError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    finally:
        os.close(descriptor)


def _recovery_v2_lexical_repository_path(
    path: Path,
    *,
    repository_root: Path,
) -> tuple[Path, Path, tuple[str, ...]]:
    """Confine a lexical path before any operation that could follow a reparse point."""

    root = Path(os.path.abspath(repository_root))
    candidate = Path(os.path.abspath(path))
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    if relative == Path("."):
        parts: tuple[str, ...] = ()
    else:
        parts = relative.parts
    return root, candidate, parts


def _recovery_v2_require_no_reparse_chain(
    path: Path,
    *,
    repository_root: Path,
    allow_missing_leaf: bool,
) -> tuple[Path, Path]:
    root, candidate, parts = _recovery_v2_lexical_repository_path(
        path,
        repository_root=repository_root,
    )
    current = root
    for index, part in enumerate(("", *parts)):
        if index:
            current = current / part
        try:
            current.lstat()
        except OSError:
            if allow_missing_leaf and current == candidate:
                break
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_MISSING") from None
        if _recovery_v2_path_is_reparse(current):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    return root, candidate


def _recovery_v2_require_repository_file(path: Path, *, repository_root: Path) -> None:
    root, candidate = _recovery_v2_require_no_reparse_chain(
        path,
        repository_root=repository_root,
        allow_missing_leaf=False,
    )
    try:
        resolved_root = root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
    except OSError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_MISSING") from None
    if not resolved.is_relative_to(resolved_root) or not candidate.is_file():
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")


def _recovery_v2_require_unused_repository_output(
    path: Path,
    *,
    repository_root: Path,
) -> None:
    """Require an absent leaf under an existing no-reparse repository parent."""

    root, candidate, _parts = _recovery_v2_lexical_repository_path(
        path,
        repository_root=repository_root,
    )
    _recovery_v2_require_no_reparse_chain(
        candidate.parent,
        repository_root=root,
        allow_missing_leaf=False,
    )
    try:
        candidate.lstat()
    except FileNotFoundError:
        return
    except OSError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")


def _recovery_v2_prepare_repository_directory(
    path: Path,
    *,
    repository_root: Path,
) -> None:
    """Create directories through an anchored no-reparse capability."""

    try:
        _recovery_v2_atomic_prepare_directory(path, repository_root=repository_root)
    except OSError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None


def _recovery_v2_publish_exclusive_bytes(
    path: Path,
    payload: bytes,
    *,
    repository_root: Path,
) -> None:
    """Publish complete bytes through an anchored leaf handle without replacement."""

    try:
        _recovery_v2_atomic_publish_exclusive_bytes(
            path,
            payload,
            repository_root=repository_root,
        )
    except FileExistsError:
        raise
    except OSError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None


def _recovery_v2_replace_bytes(
    path: Path,
    payload: bytes,
    *,
    repository_root: Path,
) -> None:
    """Replace one regular file through the same anchored capability."""

    try:
        _recovery_v2_atomic_replace_bytes(path, payload, repository_root=repository_root)
    except OSError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None


def _recovery_v2_read_bytes(
    path: Path,
    *,
    repository_root: Path,
    maximum_bytes: int,
) -> bytes:
    """Read one leaf through an anchored parent and a non-reparse file handle."""

    try:
        return _recovery_v2_atomic_read_bytes(
            path,
            repository_root=repository_root,
            maximum_bytes=maximum_bytes,
        )
    except FileNotFoundError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_MISSING") from None
    except OSError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None


def _recovery_v2_strict_json(
    path: Path,
    *,
    maximum_bytes: int,
    repository_root: Path | None = None,
) -> tuple[bytes, dict[str, Any]]:
    try:
        payload = (
            _recovery_v2_read_bytes(
                path,
                repository_root=repository_root,
                maximum_bytes=maximum_bytes,
            )
            if repository_root is not None
            else path.read_bytes()
        )
    except OSError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_MISSING") from None
    if (
        not payload
        or len(payload) > maximum_bytes
        or path.is_symlink()
        or payload.startswith(b"\xef\xbb\xbf")
        or b"\r" in payload
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    try:
        document = json.loads(
            payload,
            object_pairs_hook=_recovery_v2_unique_json_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    if not isinstance(document, dict):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    return payload, cast(dict[str, Any], document)


def _recovery_v2_postmerge_final_gate_definition(
    repository_root: Path,
) -> dict[str, object]:
    """Build the exact non-self-authorizing postmerge gate definition."""

    root = Path(os.path.abspath(repository_root))
    entrypoint = root / DATA_TORRENT_RECOVERY_V2_POSTMERGE_FINAL_GATE_PATH
    payload = _recovery_v2_read_bytes(
        entrypoint,
        repository_root=root,
        maximum_bytes=2 * 1024 * 1024,
    )
    if (
        not payload
        or len(payload) > 2 * 1024 * 1024
        or payload.startswith(b"\xef\xbb\xbf")
        or b"\r" in payload
        or not payload.endswith(b"\n")
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    return {
        "entrypoint": {
            "path": DATA_TORRENT_RECOVERY_V2_POSTMERGE_FINAL_GATE_PATH,
            "raw_sha256": hashlib.sha256(payload).hexdigest(),
            "witness_schema": DATA_TORRENT_RECOVERY_V2_POSTMERGE_FINAL_GATE_WITNESS_SCHEMA,
            "result_schema": DATA_TORRENT_RECOVERY_V2_POSTMERGE_FINAL_REPORT_SCHEMA,
        },
        "candidate_head_binding": (
            "LOCAL_C2_EQUALS_PR_HEAD_EQUALS_MERGE_SECOND_PARENT_AND_TREE"
        ),
        "candidate_report_role": "CANDIDATE_NOT_TERMINAL",
        "final_report_role": "FINAL_EXTERNAL_COMPOSITE_NON_DURABLE",
        "local_receipt_authoritative": False,
        "budget": {
            "invocations_exact": 1,
            "github_api_gets_exact": 34,
            "artifact_downloads_exact": 1,
            "validated_artifact_redirects_exact": 1,
            "physical_https_gets_exact": 35,
            "automatic_retries": 0,
            "second_invocation_allowed": False,
        },
        "reservation": {
            "scope": "HOST_LOCAL_OS_STATE_OUTSIDE_WORKTREE",
            "namespace": (
                "RobinCouncilOS/dddur75__robin-stades-ng/data-torrent-recovery-v2/"
                f"{DATA_TORRENT_RECOVERY_V2_START_SHA}/"
                "postmerge-final-gate-reservation-v1.json"
            ),
            "atomic_no_replace_before_first_get": True,
            "conservative_counters": True,
            "second_invocation_refused_before_get": True,
            "authoritative": False,
            "one_writer_host_pin_required": True,
            "host_identity_algorithm": "RECOVERY_V2_MACHINE_AND_OS_PRINCIPAL_V1",
            "expected_host_identity_sha256": (
                DATA_TORRENT_RECOVERY_V2_ONE_WRITER_HOST_SHA256
            ),
            "observer_chain_result_raw_sha256_required": True,
        },
        "required_observations": {
            "merge": "EXACT_TWO_PARENTS_RUNTIME_MAIN_THEN_C2_EMPTY_BODY",
            "premerge_safe_v2": {
                "cycles_exact": 2,
                "phase_one": (
                    "C1_ATTEMPT1_SCOPE_SUCCESS_GATE_STEP_FAILURE_RUN_FAILURE"
                ),
                "candidate": "C2_ATTEMPT1_SCOPE_SUCCESS_GATE_STEP_SUCCESS_RUN_SUCCESS",
                "completed_inventory_rechecked": True,
                "reruns": 0,
            },
            "postmerge_safe_v2": (
                "EXACT_MERGE_SHA_PUSH_MAIN_ATTEMPT1_SUCCESS_SCOPE_AND_WITNESS"
            ),
            "provider": "LEGACY_PROVIDER_BRANCH_EQUALS_RUNTIME_MAIN",
            "workflow_quarantine": "EXACT_REQUIRED_SET_DISABLED_MANUALLY",
            "nonterminal_run_counts": {
                "requested": 0,
                "waiting": 0,
                "pending": 0,
                "queued": 0,
                "in_progress": 0,
            },
            "stable_full_holds_exact": 2,
            "main_commit_reads_exact": 3,
            "final_local_c2_recheck": True,
        },
        "success_transition": {
            "input_report_role": "CANDIDATE_NOT_TERMINAL",
            "output_report_role": "FINAL_EXTERNAL_COMPOSITE_NON_DURABLE",
            "final_verdict": "PASS_AND_HOLD",
            "mission_complete": True,
            "data_torrent_ready": True,
            "global_quiescence": True,
            "worktree_status": "CLEAN",
            "candidate_fields_copied_byte_semantically": True,
            "all_ids_and_hashes_union_required": True,
            "local_receipt_authoritative": False,
        },
        "failure_transition": "FAIL_AND_STOP_NO_RETRY",
        "final_local_state_revalidation": True,
    }


def data_torrent_recovery_v2_postmerge_final_gate_contract(
    repository_root: Path,
) -> dict[str, object]:
    """Return the exact C2-bound conditional authority for the external final gate."""

    definition = _recovery_v2_postmerge_final_gate_definition(repository_root)
    return {
        "state": "PENDING_EXTERNAL_POSTMERGE_ATTESTATION",
        "committed_in_pr_c": False,
        "conditional_contract_sha256": hashlib.sha256(
            canonical_json_bytes(definition)
        ).hexdigest(),
        "authority": {
            "required_scale_stage": "E4",
            "manifest_raw_sha256": DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256,
            "manifest_canonical_sha256": DATA_TORRENT_RECOVERY_V2_MANIFEST_CANONICAL_SHA256,
            "effect_contract_raw_sha256": DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_SHA256,
            "effect_contract_canonical_sha256": (
                DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_CANONICAL_SHA256
            ),
            "latest_effect_admission_at": DATA_TORRENT_RECOVERY_V2_LATEST_EFFECT_ADMISSION_AT,
            "expires_at": DATA_TORRENT_RECOVERY_V2_EXPIRES_AT,
            "maximum_gate_runtime_seconds": (
                DATA_TORRENT_RECOVERY_V2_MAXIMUM_EFFECT_RUNTIME_SECONDS
            ),
            "time_budget_seconds": DATA_TORRENT_RECOVERY_V2_TIME_BUDGET_SECONDS,
        },
        **definition,
    }


def _recovery_v2_terminal_runtime_snapshot(report: Mapping[str, object]) -> str:
    """Hash the acyclic runtime evidence projection reviewed by terminal QA."""

    projection = {
        key: value
        for key, value in report.items()
        if key not in {"reviewed_runtime_snapshot_sha256", "independent_reviews"}
    }
    return hashlib.sha256(
        json.dumps(
            projection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _recovery_v2_terminal_stage_effects(value: object) -> dict[str, int]:
    if (
        not isinstance(value, dict)
        or set(value) != _RECOVERY_V2_STAGE_EFFECT_FIELDS
        or any(type(item) is not int or item < 0 for item in value.values())
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    return cast(dict[str, int], value)


def _recovery_v2_terminal_hold(
    value: object,
    *,
    runtime_main_sha: str,
) -> dict[str, Any]:
    """Validate the fresh post-LIVE GitHub quiescence observation."""

    if not isinstance(value, dict):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    hold = cast(dict[str, Any], value)
    post_merge = hold.get("post_merge_ci")
    scope_job = hold.get("recovery_v2_scope_guard")
    legacy_ci = hold.get("legacy_ci_workflow_quarantine")
    workflows = hold.get("recovery_v2_production_workflow_quarantine")
    environment = hold.get("production_environment_policy")
    nonterminal = hold.get("nonterminal_run_counts")
    expected_fields = {
        "schema_version",
        "verdict",
        "active_after",
        "disabled_after",
        "queued_after",
        "in_progress_after",
        "nonterminal_run_counts",
        "current_run_excluded",
        "unauthorized_active_workflows",
        "post_merge_ci",
        "recovery_v2_scope_guard",
        "legacy_secret_branch_sha",
        "legacy_ci_workflow_quarantine",
        "recovery_v2_production_workflow_quarantine",
        "production_environment_policy",
        "provider_calls",
        "r2_operations",
    }
    if (
        set(hold) != expected_fields
        or hold.get("schema_version") != "chronos-production-workflow-hold-live-v3"
        or hold.get("verdict") != "WORKFLOW_HOLD_ESTABLISHED"
        or type(hold.get("active_after")) is not int
        or cast(int, hold["active_after"]) < 0
        or type(hold.get("disabled_after")) is not int
        or cast(int, hold["disabled_after"]) < 8
        or not _exact_integer_fields(
            hold,
            {
                "queued_after",
                "in_progress_after",
                "current_run_excluded",
                "provider_calls",
                "r2_operations",
            },
        )
        or hold.get("queued_after") != 0
        or hold.get("in_progress_after") != 0
        or not isinstance(nonterminal, dict)
        or not _exact_integer_fields(
            nonterminal,
            set(_RECOVERY_V2_NONTERMINAL_RUN_COUNTS),
        )
        or nonterminal != _RECOVERY_V2_NONTERMINAL_RUN_COUNTS
        or hold.get("current_run_excluded") != 0
        or hold.get("unauthorized_active_workflows") != []
        or hold.get("legacy_secret_branch_sha") != runtime_main_sha
        or hold.get("provider_calls") != 0
        or hold.get("r2_operations") != 0
        or not isinstance(post_merge, dict)
        or set(post_merge)
        != {
            "workflow_path",
            "run_id",
            "run_attempt",
            "head_sha",
            "head_branch",
            "event",
            "status",
            "conclusion",
        }
        or post_merge.get("workflow_path") != ".github/workflows/ci-safe-v2.yml"
        or type(post_merge.get("run_id")) is not int
        or cast(int, post_merge["run_id"]) <= 0
        or type(post_merge.get("run_attempt")) is not int
        or post_merge.get("run_attempt") != 1
        or post_merge.get("head_sha") != runtime_main_sha
        or post_merge.get("head_branch") != "main"
        or post_merge.get("event") != "push"
        or post_merge.get("status") != "completed"
        or post_merge.get("conclusion") != "success"
        or not isinstance(scope_job, dict)
        or set(scope_job) != {"job_id", "name", "run_id", "head_sha", "status", "conclusion"}
        or type(scope_job.get("job_id")) is not int
        or cast(int, scope_job["job_id"]) <= 0
        or type(scope_job.get("run_id")) is not int
        or scope_job.get("name") != "Recovery V2 — scope guard exact"
        or scope_job.get("run_id") != post_merge.get("run_id")
        or scope_job.get("head_sha") != runtime_main_sha
        or scope_job.get("status") != "completed"
        or scope_job.get("conclusion") != "success"
        or not isinstance(legacy_ci, dict)
        or legacy_ci
        != {
            "workflow_id": cast(dict[str, object], legacy_ci).get("workflow_id"),
            "workflow_path": ".github/workflows/ci.yml",
            "state": "disabled_manually",
        }
        or type(cast(dict[str, object], legacy_ci).get("workflow_id")) is not int
        or cast(int, cast(dict[str, object], legacy_ci)["workflow_id"]) <= 0
        or not isinstance(environment, dict)
        or set(environment)
        != {
            "environment",
            "can_admins_bypass",
            "protected_branches",
            "custom_branch_policies",
            "allowed_branches",
        }
        or environment.get("environment") != "chronos-control-plane-production"
        or environment.get("can_admins_bypass") is not False
        or environment.get("protected_branches") is not False
        or environment.get("custom_branch_policies") is not True
        or environment.get("allowed_branches") != ["main"]
        or not isinstance(workflows, list)
        or len(workflows) != len(_RECOVERY_V2_REQUIRED_DISABLED_WORKFLOWS)
        or any(not isinstance(item, dict) for item in workflows)
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    rows = cast(list[dict[str, object]], workflows)
    if (
        [row.get("workflow_path") for row in rows]
        != list(_RECOVERY_V2_REQUIRED_DISABLED_WORKFLOWS)
        or any(
            set(row) != {"workflow_id", "workflow_path", "state"}
            or type(row.get("workflow_id")) is not int
            or cast(int, row["workflow_id"]) <= 0
            or row.get("state") != "disabled_manually"
            for row in rows
        )
        or len({cast(int, row["workflow_id"]) for row in rows}) != len(rows)
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    return hold


def _recovery_v2_evidence_bytes(
    path: Path,
    *,
    repository_root: Path,
    maximum_bytes: int = 2 * 1024 * 1024,
) -> bytes:
    payload = _recovery_v2_read_bytes(
        path,
        repository_root=repository_root,
        maximum_bytes=maximum_bytes,
    )
    if (
        not payload
        or len(payload) > maximum_bytes
        or path.is_symlink()
        or payload.startswith(b"\xef\xbb\xbf")
        or b"\x00" in payload
        or b"\r" in payload
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    return payload


def _recovery_v2_terminal_live_bundle(
    root: Path,
    *,
    runtime_main_sha: str,
) -> tuple[bytes, dict[str, Any], dict[str, bytes]]:
    """Validate the immutable LIVE archive attestation and its nineteen copied bytes."""

    attestation_payload, attestation = _recovery_v2_strict_json(
        root / DATA_TORRENT_RECOVERY_V2_LIVE_BUNDLE_ATTESTATION_PATH,
        maximum_bytes=262_144,
        repository_root=root,
    )
    members = attestation.get("members")
    run_id = attestation.get("run_id")
    artifact_id = attestation.get("artifact_id")
    expected_names = tuple(sorted(_RECOVERY_V2_TERMINAL_ARTIFACT_NAMES))
    if (
        set(attestation)
        != {
            "schema_version",
            "repository",
            "workflow_path",
            "run_id",
            "run_attempt",
            "head_sha",
            "head_branch",
            "event",
            "status",
            "conclusion",
            "run_completed_observed_at",
            "artifact_id",
            "artifact_name",
            "archive_sha256",
            "members",
        }
        or attestation.get("schema_version") != "github-artifact-bundle-attestation-v2"
        or attestation.get("repository") != EXPECTED_REPOSITORY
        or attestation.get("workflow_path") != ".github/workflows/data-torrent-live-v2.yml"
        or not isinstance(run_id, str)
        or _RUN_ID.fullmatch(run_id) is None
        or attestation.get("run_attempt") != "1"
        or attestation.get("head_sha") != runtime_main_sha
        or attestation.get("head_branch") != "main"
        or attestation.get("event") != "workflow_dispatch"
        or attestation.get("status") != "completed"
        or attestation.get("conclusion") != "success"
        or not isinstance(attestation.get("run_completed_observed_at"), str)
        or type(artifact_id) is not int
        or artifact_id <= 0
        or attestation.get("artifact_name") != f"data-torrent-live-v2-{run_id}"
        or not isinstance(attestation.get("archive_sha256"), str)
        or _HEX_64.fullmatch(cast(str, attestation["archive_sha256"])) is None
        or not isinstance(members, list)
        or len(members) != len(expected_names)
        or any(not isinstance(item, dict) for item in members)
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    try:
        _authority_timestamp(
            attestation.get("run_completed_observed_at"),
            field="live_run_completed_observed_at",
        )
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    rows = cast(list[dict[str, object]], members)
    if (
        tuple(cast(str, row.get("filename")) for row in rows) != expected_names
        or any(
            set(row) != {"filename", "payload_bytes", "payload_sha256"}
            or type(row.get("payload_bytes")) is not int
            or cast(int, row["payload_bytes"]) <= 0
            or not isinstance(row.get("payload_sha256"), str)
            or _HEX_64.fullmatch(cast(str, row["payload_sha256"])) is None
            for row in rows
        )
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    artifacts: dict[str, bytes] = {}
    for row in rows:
        filename = cast(str, row["filename"])
        payload = _recovery_v2_evidence_bytes(
            root / DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR / "artifacts" / filename,
            repository_root=root,
        )
        if (
            len(payload) != row["payload_bytes"]
            or not hmac.compare_digest(
                hashlib.sha256(payload).hexdigest(),
                cast(str, row["payload_sha256"]),
            )
        ):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        artifacts[filename] = payload
    try:
        manifest = json.loads(
            artifacts["torrent-real-batch-manifest-v1.json"],
            object_pairs_hook=_recovery_v2_unique_json_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        if not isinstance(manifest, dict):
            raise ValueError
        normalized_binding = cast(dict[str, Any], manifest["evidence_validity"])["binding"]
        from robin.data_torrent.runtime import _assert_final_artifact_closure

        _assert_final_artifact_closure(
            artifacts=artifacts,
            normalized_binding=normalized_binding,
        )
    except Exception:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    return attestation_payload, attestation, artifacts


def _recovery_v2_json_artifact(payload: bytes) -> dict[str, Any]:
    try:
        document = json.loads(
            payload,
            object_pairs_hook=_recovery_v2_unique_json_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    if not isinstance(document, dict):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    return cast(dict[str, Any], document)


def _recovery_v2_unsigned_signed_artifact(
    document: Mapping[str, object],
    *,
    expected_fields: set[str],
) -> dict[str, Any]:
    """Validate the public shape of an HMAC envelope without exposing its secret key."""

    if set(document) != expected_fields | {"signature"}:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    signature = document.get("signature")
    if (
        not isinstance(signature, dict)
        or set(signature) != {"algorithm", "value"}
        or signature.get("algorithm") != "HMAC-SHA256"
        or not isinstance(signature.get("value"), str)
        or _HEX_64.fullmatch(cast(str, signature["value"])) is None
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    unsigned = dict(document)
    unsigned.pop("signature")
    return cast(dict[str, Any], unsigned)


def _recovery_v2_empty_stage_effects() -> dict[str, int]:
    return {field: 0 for field in _RECOVERY_V2_STAGE_EFFECT_FIELDS}


def _recovery_v2_framed_sha256(*parts: object) -> str:
    digest = hashlib.sha256()
    for part in parts:
        text = str(part)
        encoded = text.encode("utf-8")
        digest.update(str(len(encoded)).encode("ascii") + b":" + encoded)
    return digest.hexdigest()


def _recovery_v2_pg_timestamp(value: object, *, field: str) -> str:
    timestamp = _authority_timestamp(value, field=field)
    return timestamp.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _recovery_v2_chronos_event_hash(
    event: Mapping[str, object],
    *,
    previous_event_hash: str,
) -> str:
    return _recovery_v2_framed_sha256(
        "chronos-effect-event-v1",
        event["event_seq"],
        event["operation_id"],
        event["authority_id"],
        event["event_type"],
        event["resource_kind"],
        event["resource_key"],
        event["payload_hash"],
        _recovery_v2_pg_timestamp(
            event["db_recorded_at"], field="live_r2_event_recorded_at"
        ),
        event["github_run_id"],
        event["github_run_attempt"],
        event["code_revision"],
        previous_event_hash,
    )


def _recovery_v2_terminalization_effect_reservation(
    *,
    stage: str,
    workflow_run_id: int,
    stage_inputs: Mapping[str, object],
) -> dict[str, object]:
    if (
        stage not in DATA_TORRENT_RECOVERY_V2_POST_EFFECT_TERMINAL_GRACE_SECONDS
        or type(workflow_run_id) is not int
        or workflow_run_id <= 0
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_TERMINAL_EVIDENCE_INVALID")
    raw_deadline = stage_inputs.get("recovery_v2_effect_deadline_epoch")
    if (
        not isinstance(raw_deadline, str)
        or not raw_deadline.isascii()
        or not raw_deadline.isdigit()
        or len(raw_deadline) > 12
        or str(int(raw_deadline)) != raw_deadline
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_TERMINAL_EVIDENCE_INVALID")
    effect_deadline = int(raw_deadline)
    grace = DATA_TORRENT_RECOVERY_V2_POST_EFFECT_TERMINAL_GRACE_SECONDS[stage]
    not_before = _authority_timestamp(
        DATA_TORRENT_RECOVERY_V2_NOT_BEFORE,
        field="recovery_v2_not_before",
    )
    admission_close = _authority_timestamp(
        DATA_TORRENT_RECOVERY_V2_LATEST_EFFECT_ADMISSION_AT,
        field="recovery_v2_effect_admission",
    )
    expiry = _authority_timestamp(
        DATA_TORRENT_RECOVERY_V2_EXPIRES_AT,
        field="recovery_v2_expiry",
    )
    budget_deadline = min(
        expiry,
        not_before + timedelta(seconds=DATA_TORRENT_RECOVERY_V2_TIME_BUDGET_SECONDS),
    )
    maximum_effect_deadline = int(
        (
            admission_close
            + timedelta(
                seconds=DATA_TORRENT_RECOVERY_V2_EFFECT_DEADLINE_SECONDS_MAXIMUM[stage]
            )
        ).timestamp()
    )
    controller_deadline = (
        effect_deadline
        + grace
        + DATA_TORRENT_RECOVERY_V2_TERMINAL_ATTESTATION_RESERVE_SECONDS
    )
    if (
        effect_deadline <= int(not_before.timestamp())
        or effect_deadline > maximum_effect_deadline
        or controller_deadline > int(budget_deadline.timestamp())
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_TERMINAL_EVIDENCE_INVALID")
    return {
        "reservation_status": (
            "CONSERVATIVE_UPPER_BOUNDS_RESERVED_BEFORE_FIRST_TERMINAL_GET"
        ),
        "workflow_run_id": workflow_run_id,
        "workflow_effect_deadline_epoch": effect_deadline,
        "post_effect_workflow_terminal_grace_seconds": grace,
        "controller_terminalization_deadline_epoch": (
            controller_deadline
        ),
        "terminal_artifact_attestation_reserve_seconds": (
            DATA_TORRENT_RECOVERY_V2_TERMINAL_ATTESTATION_RESERVE_SECONDS
        ),
        "workflow_run_observations_conservatively_consumed": 3,
        "artifact_attestation_gets_conservatively_consumed": 3,
        "artifact_downloads_conservatively_consumed": 1,
        "automatic_retries": 0,
        "second_terminalization_invocation_allowed": False,
    }


def _validate_recovery_v2_terminal_live_counter_closure(
    *,
    actual: Mapping[str, object],
    provider: Mapping[str, object],
    live_runtime_before: Mapping[str, object],
    live_runtime: Mapping[str, object],
) -> None:
    """Close exact DNS and PostgreSQL splits against the hashed LIVE call graph."""

    try:
        before_postgresql = cast(
            Mapping[str, object], live_runtime_before["postgresql"]
        )
        before_odds = cast(Mapping[str, object], live_runtime_before["odds"])
        final_postgresql = cast(Mapping[str, object], live_runtime["postgresql"])
        final_odds = cast(Mapping[str, object], live_runtime["odds"])
        integer_fields = {
            "read_transactions_attempted",
            "function_reads_attempted",
            "mutating_function_calls_attempted",
            "connection_attempts_upper_bound",
        }
        if (
            not isinstance(before_postgresql, Mapping)
            or not isinstance(before_odds, Mapping)
            or not isinstance(final_postgresql, Mapping)
            or not isinstance(final_odds, Mapping)
            or not _exact_integer_fields(before_postgresql, integer_fields)
            or not _exact_integer_fields(final_postgresql, integer_fields)
            or type(actual.get("odds_dns_resolutions")) is not int
            or type(provider.get("dns_resolutions")) is not int
            or type(before_odds.get("dns_resolutions_attempted")) is not int
            or type(final_odds.get("dns_resolutions_attempted")) is not int
        ):
            raise ValueError
        before_read = cast(int, before_postgresql["read_transactions_attempted"])
        before_function = cast(int, before_postgresql["function_reads_attempted"])
        before_mutating = cast(
            int, before_postgresql["mutating_function_calls_attempted"]
        )
        before_connections = cast(
            int, before_postgresql["connection_attempts_upper_bound"]
        )
        final_read = cast(int, final_postgresql["read_transactions_attempted"])
        final_function = cast(int, final_postgresql["function_reads_attempted"])
        final_mutating = cast(
            int, final_postgresql["mutating_function_calls_attempted"]
        )
        final_connections = cast(
            int, final_postgresql["connection_attempts_upper_bound"]
        )
        if (
            actual["odds_dns_resolutions"] != 5
            or provider["dns_resolutions"] != 5
            or before_odds["dns_resolutions_attempted"] != 5
            or final_odds["dns_resolutions_attempted"] != 5
            or before_read != 4
            or not 4 <= before_function <= 6
            or before_mutating != 40
            or before_connections != before_read + before_function + before_mutating
            or final_read != 6
            or final_function != before_function
            or final_mutating != 41
            or final_connections != final_read + final_function + final_mutating
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ChronosProductionError(
            "CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID"
        ) from None


_RECOVERY_V2_TERMINAL_CLOCK_SKEW = timedelta(seconds=5)


def _validate_recovery_v2_terminal_response_observation(
    *,
    retrieved_at: datetime,
    dispatched_at: datetime,
    terminal_at: datetime,
    capture_started: datetime,
    capture_ended: datetime,
) -> None:
    """Bind a raw observation to both its local capture and durable effect window."""

    try:
        if (
            not capture_started <= retrieved_at <= capture_ended
            or retrieved_at < dispatched_at - _RECOVERY_V2_TERMINAL_CLOCK_SKEW
            or retrieved_at > terminal_at + _RECOVERY_V2_TERMINAL_CLOCK_SKEW
        ):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise ChronosProductionError(
            "CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID"
        ) from None


def _validate_recovery_v2_terminal_generated_chronology(
    *,
    latest_retrieved_at: datetime,
    raw_index_generated_at: datetime,
    capture_ended: datetime,
    replay_generated_at: datetime,
    quality_generated_at: datetime,
    normalized_generated_at: datetime,
    qa_generated_at: datetime,
    manifest_generated_at: datetime,
) -> None:
    """Prove the producer's exact evidence-generation order from terminal bytes."""

    try:
        if not (
            latest_retrieved_at
            <= raw_index_generated_at
            <= capture_ended
            <= replay_generated_at
            <= quality_generated_at
            <= normalized_generated_at
            <= qa_generated_at
            <= manifest_generated_at
        ):
            raise ValueError
    except (TypeError, ValueError):
        raise ChronosProductionError(
            "CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID"
        ) from None


def _recovery_v2_terminal_expected_source_request_contract(
    *,
    family: str,
    sport_key: str,
    config: Any,
    capture_started: datetime,
) -> dict[str, Any]:
    """Independently reconstruct the only source request authorized by LIVE V2."""

    try:
        league = next(item for item in config.leagues if item.sport_key == sport_key)
        if family == "OFFICIAL":
            maximum_reads = 12 if sport_key == "soccer_spain_la_liga" else 6
            return {
                "schema_version": "robin-data-torrent-official-request-v1",
                "method": "GET",
                "sanitized_endpoint": league.official_source.url,
                "sport_key": sport_key,
                "adapter_revision": league.official_source.adapter,
                "timeout_seconds": 45,
                "maximum_redirects": (
                    0
                    if league.official_source.adapter == "LIGUE1_CALENDAR_JSON_V1"
                    else 5
                ),
                "maximum_supporting_reads": maximum_reads - 1,
                "maximum_physical_reads": maximum_reads,
                "selection_horizon_not_before_utc": capture_started.astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z"),
                "selection_horizon_expires_at_utc": (
                    capture_started.astimezone(UTC)
                    + timedelta(days=config.fallback_horizon_days)
                )
                .isoformat()
                .replace("+00:00", "Z"),
                "automatic_retries": 0,
                "certificate_verification_required": True,
            }
        if family == "ODDS":
            return {
                "schema_version": "robin-data-torrent-odds-request-v1",
                "method": "GET",
                "sanitized_endpoint": (
                    f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
                ),
                "sport_key": sport_key,
                "region": config.region,
                "markets": list(config.markets),
                "odds_format": "decimal",
                "date_format": "iso",
                "timeout_seconds": 30,
                "maximum_redirects": 0,
                "automatic_retries": 0,
                "certificate_verification_required": True,
                "environment_proxy_allowed": False,
            }
    except (AttributeError, StopIteration, TypeError, ValueError, OverflowError):
        pass
    raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")


def _recovery_v2_terminal_live_semantics(
    artifacts: Mapping[str, bytes],
    *,
    repository_root: Path,
) -> dict[str, dict[str, Any]]:
    """Derive terminal projections only from the exact copied LIVE payload bytes."""

    names = {
        "manifest": "torrent-real-batch-manifest-v1.json",
        "raw_index": "torrent-real-batch-raw-index-v1.json",
        "normalized": "torrent-real-batch-normalized-index-v1.json",
        "quality": "torrent-real-batch-quality-report-v1.json",
        "lineage": "torrent-raw-to-normalized-lineage-v1.json",
        "qa": "torrent-qa-acceptance-matrix-v1.json",
        "replay": "torrent-load-replay-report-v1.json",
        "official": "torrent-official-read-receipts-v1.json",
        "provider": "torrent-provider-credit-receipt-v1.json",
        "inventory": "torrent-r2-inventory-v1.json",
        "canonical": "torrent-canonical-dataset-hash-v1.json",
        "claim": "torrent-opportunity-claim-receipt-v1.json",
        "chain": "torrent-control-plane-event-chain-v1.json",
    }
    documents = {key: _recovery_v2_json_artifact(artifacts[value]) for key, value in names.items()}
    manifest = documents["manifest"]
    raw_index = documents["raw_index"]
    normalized = documents["normalized"]
    quality = documents["quality"]
    lineage = documents["lineage"]
    qa_matrix = documents["qa"]
    replay = documents["replay"]
    official = documents["official"]
    provider = documents["provider"]
    inventory = documents["inventory"]
    canonical = documents["canonical"]
    claim = documents["claim"]
    chain = documents["chain"]
    try:
        from robin.capture.official_schedule_sources import (
            OfficialScheduleSourceError,
            _validate_official_url,
        )
        from robin.data_torrent.archive import coverage_csv, json_artifact
        from robin.data_torrent.claims import derive_opportunity_id
        from robin.data_torrent.contracts import (
            load_torrent_config,
            validate_request_contract_safety,
            validate_response_metadata_safety,
        )
        from robin.data_torrent.normalization import (
            load_team_aliases,
            team_alias_registry_document,
        )
        from robin.data_torrent.reporting import verify_qa_matrix
        from robin.data_torrent.runtime import (
            _assert_final_artifact_closure,
            _terminal_live_effects_projection,
        )

        config_path = repository_root / "configs" / "data" / "torrent-live-v2.json"
        _recovery_v2_evidence_bytes(
            config_path,
            repository_root=repository_root,
            maximum_bytes=262_144,
        )
        config = load_torrent_config(config_path)
        alias_path = repository_root / "config" / "alias_equipes.yaml"
        _recovery_v2_evidence_bytes(
            alias_path,
            repository_root=repository_root,
            maximum_bytes=2 * 1024 * 1024,
        )
        team_aliases = load_team_aliases(alias_path)
        alias_document = team_alias_registry_document(team_aliases)
        expected_alias_binding = {
            "artifact": "config/alias_equipes.yaml",
            "archive_member": "config/team-alias-registry-v1.json",
            "entries": len(team_aliases),
            "mapping_sha256": alias_document["mapping_sha256"],
            "registry_artifact_sha256": hashlib.sha256(
                json_artifact(alias_document)
            ).hexdigest(),
            "matching_mode": "ONE_HOP_EXACT_ONLY",
        }
        verify_qa_matrix(qa_matrix)
        counts = cast(dict[str, Any], manifest["counts"])
        scope = cast(dict[str, Any], manifest["scope"])
        scope_team_aliases = cast(dict[str, Any], scope["team_aliases"])
        manifest_execution = cast(dict[str, Any], manifest["execution"])
        manifest_artifacts = cast(list[dict[str, Any]], manifest["artifacts"])
        evidence_validity = cast(dict[str, Any], manifest["evidence_validity"])
        effect_summary = cast(dict[str, Any], manifest["effect_summary"])
        effect_limits = cast(dict[str, Any], effect_summary["limits"])
        actual = cast(dict[str, Any], effect_summary["actual"])
        live_runtime_before = cast(
            dict[str, Any],
            effect_summary["live_runtime_effects_before_terminal_database_receipts"],
        )
        live_runtime = cast(dict[str, Any], effect_summary["live_runtime_effects"])
        live_projection_proof = cast(
            dict[str, Any], effect_summary["live_runtime_effects_projection_proof"]
        )
        postgresql_before = cast(dict[str, Any], live_runtime_before["postgresql"])
        live_odds_before = cast(dict[str, Any], live_runtime_before["odds"])
        postgresql = cast(dict[str, Any], live_runtime["postgresql"])
        live_official = cast(dict[str, Any], live_runtime["official"])
        live_odds = cast(dict[str, Any], live_runtime["odds"])
        live_r2 = cast(dict[str, Any], live_runtime["r2"])
        durability = cast(dict[str, Any], manifest["durability"])
        raw_object = cast(dict[str, Any], durability["raw_object"])
        normalized_binding = cast(dict[str, Any], durability["normalized_evidence_binding"])
        normalized_members = cast(list[dict[str, Any]], normalized_binding["members"])
        integrity = cast(dict[str, Any], manifest["integrity"])
        production = cast(dict[str, Any], manifest["production"])
        release_chain = cast(dict[str, Any], manifest["chronos_release_chain_proof"])
        embedded_bindings = cast(dict[str, Any], release_chain["runtime_bindings"])
        normalized_team_aliases = cast(dict[str, Any], normalized["team_aliases"])
        normalized_totals = cast(dict[str, Any], normalized["totals"])
        coverage_rows = cast(list[dict[str, Any]], normalized["league_market_counts"])
        quality_temporal = cast(dict[str, Any], quality["temporal"])
        quality_coverage = cast(dict[str, Any], quality["coverage"])
        quality_durability = cast(dict[str, Any], quality["durability"])
        quality_lineage = cast(dict[str, Any], quality["lineage"])
        quality_response = cast(dict[str, Any], quality["response_accounting"])
        quality_rejects = cast(list[dict[str, Any]], quality["rejects_by_reason"])
        quality_replay = cast(dict[str, Any], quality["replay"])
        quality_external = cast(dict[str, Any], quality["external_effects"])
        quality_gates = cast(list[dict[str, Any]], quality["gates"])
        source_accounting = cast(dict[str, Any], quality["source_unit_accounting"])
        lineage_summary = cast(dict[str, Any], lineage["summary"])
        lineage_rejects = cast(list[dict[str, Any]], lineage["rejects"])
        qa_summary = cast(dict[str, Any], qa_matrix["summary"])
        qa_gates = cast(list[dict[str, Any]], qa_matrix["gates"])
        replay_input = cast(dict[str, Any], replay["input"])
        replay_run = cast(dict[str, Any], replay["replay"])
        replay_measurement = cast(dict[str, Any], replay["measurement"])
        replay_external = cast(dict[str, Any], replay["external_effects_delta"])
        replay_acceptance = cast(dict[str, Any], replay["acceptance"])
        replay_required = cast(dict[str, Any], replay["normal_required_throughput"])
        replay_throughput = cast(dict[str, Any], replay["throughput"])
        inventory_objects = cast(list[dict[str, Any]], inventory["objects"])
        inventory_live = cast(dict[str, Any], inventory["counters"])
        inventory_mission = cast(dict[str, Any], inventory["mission_counters"])
        inventory_limits = cast(dict[str, Any], inventory["limits"])
        inventory_live_limits = cast(dict[str, Any], inventory["live_limits"])
        inventory_mission_limits = cast(dict[str, Any], inventory["mission_limits"])
        official_reads = cast(list[dict[str, Any]], official["reads"])
        provider_transitions = cast(list[dict[str, Any]], provider["credit_transitions"])
        leagues = cast(list[dict[str, Any]], scope["leagues_enabled"])
        markets = cast(list[str], scope["markets_enabled"])
        manifest_identity = cast(dict[str, Any], manifest["run_identity"])
        post_merge_proof = cast(dict[str, Any], manifest["post_merge_ci_proof"])
        manifest_horizon = cast(dict[str, Any], manifest["horizon"])
        horizon_reconciliation = cast(dict[str, Any], manifest_horizon["reconciliation"])
        reconciliation_fixture_counts = cast(
            dict[str, Any], horizon_reconciliation["fixture_counts"]
        )
        chain_events = cast(dict[str, Any], chain["events"])
        chain_summary = cast(dict[str, Any], chain["summary"])
        source_events = cast(list[dict[str, Any]], chain_events["external_sources"])
        raw_index_totals = cast(dict[str, Any], raw_index["totals"])
        raw_responses = cast(list[dict[str, Any]], raw_index["responses"])
        lineage_raw = cast(list[dict[str, Any]], lineage["raw_responses"])
        lineage_records = cast(list[dict[str, Any]], lineage["records"])
        normalized_record_types = cast(list[dict[str, Any]], normalized["record_type_counts"])
        if (
            any(
                not isinstance(value, dict)
                for value in (
                    counts,
                    scope,
                    scope_team_aliases,
                    manifest_execution,
                    evidence_validity,
                    effect_summary,
                    effect_limits,
                    actual,
                    live_runtime_before,
                    live_runtime,
                    live_projection_proof,
                    postgresql_before,
                    live_odds_before,
                    postgresql,
                    live_official,
                    live_odds,
                    live_r2,
                    durability,
                    raw_object,
                    normalized_binding,
                    integrity,
                    production,
                    release_chain,
                    embedded_bindings,
                    normalized_team_aliases,
                    normalized_totals,
                    quality_temporal,
                    quality_coverage,
                    quality_durability,
                    quality_lineage,
                    quality_response,
                    quality_replay,
                    quality_external,
                    source_accounting,
                    lineage_summary,
                    qa_summary,
                    replay_input,
                    replay_run,
                    replay_measurement,
                    replay_external,
                    replay_acceptance,
                    replay_required,
                    replay_throughput,
                    inventory_live,
                    inventory_mission,
                    inventory_limits,
                    inventory_live_limits,
                    inventory_mission_limits,
                    manifest_identity,
                    post_merge_proof,
                    manifest_horizon,
                    horizon_reconciliation,
                    reconciliation_fixture_counts,
                    chain_events,
                    raw_index_totals,
                )
            )
            or
            not isinstance(coverage_rows, list)
            or any(not isinstance(row, dict) for row in coverage_rows)
            or not isinstance(lineage_rejects, list)
            or any(not isinstance(row, dict) for row in lineage_rejects)
            or not isinstance(qa_gates, list)
            or any(not isinstance(row, dict) for row in qa_gates)
            or not isinstance(inventory_objects, list)
            or any(not isinstance(row, dict) for row in inventory_objects)
            or not isinstance(official_reads, list)
            or any(not isinstance(row, dict) for row in official_reads)
            or not isinstance(provider_transitions, list)
            or any(not isinstance(row, dict) for row in provider_transitions)
            or not isinstance(manifest_artifacts, list)
            or any(not isinstance(row, dict) for row in manifest_artifacts)
            or not isinstance(quality_rejects, list)
            or any(not isinstance(row, dict) for row in quality_rejects)
            or not isinstance(quality_gates, list)
            or any(not isinstance(row, dict) for row in quality_gates)
            or not isinstance(leagues, list)
            or any(not isinstance(row, dict) for row in leagues)
            or not isinstance(markets, list)
            or any(not isinstance(value, str) for value in markets)
            or not isinstance(normalized_members, list)
            or any(not isinstance(row, dict) for row in normalized_members)
            or not isinstance(source_events, list)
            or any(not isinstance(row, dict) for row in source_events)
            or not isinstance(raw_responses, list)
            or any(not isinstance(row, dict) for row in raw_responses)
            or not isinstance(lineage_raw, list)
            or any(not isinstance(row, dict) for row in lineage_raw)
            or not isinstance(lineage_records, list)
            or any(not isinstance(row, dict) for row in lineage_records)
            or not isinstance(normalized_record_types, list)
            or any(not isinstance(row, dict) for row in normalized_record_types)
            or not isinstance(chain_summary, dict)
        ):
            raise TypeError
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None

    try:
        _assert_final_artifact_closure(
            artifacts=dict(artifacts),
            normalized_binding=normalized_binding,
        )
    except Exception:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None

    canonical_sha = manifest.get("canonical_dataset_sha256")
    returned_markets = sorted(
        {cast(str, row.get("market")) for row in coverage_rows}
    )
    league_keys = [row.get("sport_key") for row in leagues]
    expected_coverage_cells = {
        (sport_key, market) for sport_key in league_keys for market in markets
    }
    observed_coverage_cells = {(row.get("sport_key"), row.get("market")) for row in coverage_rows}
    rejected_records = normalized_totals.get("rejected_records")
    connection_attempts = postgresql.get("connection_attempts_upper_bound")
    mutating_attempts = postgresql.get("mutating_function_calls_attempted")

    integer_boundaries: tuple[tuple[Mapping[str, object], set[str]], ...] = (
        (
            manifest,
            {"hypotheses_generated", "edge_promotions", "bet_calls", "purchases"},
        ),
        (manifest_execution, {"automatic_retries", "identical_snapshot_attempts"}),
        (scope_team_aliases, {"entries"}),
        (
            effect_limits,
            {
                "official_physical_reads_max",
                "odds_provider_requests_max",
                "odds_credits_max",
                "automatic_retries",
                "r2_puts_max",
                "r2_gets_max",
                "r2_lists_max",
                "r2_deletes_max",
                "odds_dns_resolutions_max",
            },
        ),
        (
            counts,
            {
                "leagues_enabled",
                "leagues_with_real_data",
                "fixtures_available",
                "fixtures_captured",
                "markets_requested",
                "markets_returned",
                "raw_responses",
                "raw_bytes",
                "official_physical_reads",
                "odds_provider_requests",
                "odds_credits_used",
                "odds_dns_resolutions",
                "accounted_responses",
                "silent_responses",
                "normalized_records",
                "rejected_records",
                "silent_drops",
                "logical_duplicates",
                "temporal_leakage",
            },
        ),
        (
            manifest_horizon,
            {
                "primary_days",
                "fallback_days",
                "fallback_threshold",
                "primary_fixture_count",
                "selected_days",
                "selected_fixture_count",
            },
        ),
        (
            normalized_totals,
            {
                "normalized_records",
                "rejected_records",
                "logical_duplicates",
                "canonical_bytes",
            },
        ),
        (
            replay_input,
            {
                "raw_archive_decode_count",
                "raw_payload_parse_iterations",
                "raw_bytes_per_iteration",
                "normalized_records_per_iteration",
                "rejected_records_per_iteration",
            },
        ),
        (
            replay_run,
            {
                "multiplier",
                "equivalent_normalized_records",
                "iterations_completed",
                "total_records_processed",
                "total_bytes_processed",
            },
        ),
        (
            replay_measurement,
            {
                "latency_sample_count",
                "baseline_rss_bytes",
                "peak_memory_bytes",
                "incremental_peak_memory_bytes",
                "rejects",
                "duplicates",
                "silent_losses",
            },
        ),
        (
            quality_temporal,
            {
                "timezone_missing",
                "backfill",
                "future_information",
                "post_event_as_pre_event",
                "leakage_total",
            },
        ),
        (quality_coverage, {"expected_cells", "emitted_cells", "incomplete_cells"}),
        (
            quality_lineage,
            {
                "raw_responses_covered",
                "normalized_records_covered",
                "rejected_units_covered",
            },
        ),
        (source_accounting, {"observed", "accounted", "silent"}),
        (quality_response, {"observed", "accounted", "silent"}),
        (quality_replay, {"external_reads"}),
        (
            quality_external,
            {
                "official_source_operations",
                "official_physical_reads",
                "odds_provider_operations",
                "odds_dns_resolutions",
                "odds_provider_requests",
                "r2_live_operations",
                "r2_control_plane_operations",
                "r2_mission_operations",
                "r2_objects",
                "accounted",
                "unaccounted",
            },
        ),
        (
            raw_index_totals,
            {
                "raw_responses",
                "raw_bytes",
                "official_physical_reads",
                "odds_provider_requests",
                "odds_credits_used",
                "odds_dns_resolutions",
                "accounted_responses",
                "silent_responses",
            },
        ),
        (
            lineage_summary,
            {
                "raw_responses_observed",
                "raw_responses_accounted",
                "normalized_records",
                "rejected_units",
                "silent_responses",
            },
        ),
        (inventory_live, {"puts", "gets", "lists", "deletes", "objects", "overwrites"}),
        (
            inventory_mission,
            {"puts", "gets", "lists", "deletes", "objects", "overwrites"},
        ),
        (inventory_limits, {"puts", "gets", "lists", "deletes"}),
        (inventory_live_limits, {"puts", "gets", "lists", "deletes"}),
        (inventory_mission_limits, {"puts", "gets", "lists", "deletes", "objects"}),
        (
            actual,
            {
                "official_physical_reads",
                "odds_dns_resolutions",
                "odds_provider_requests",
                "odds_credits_used",
                "puts",
                "gets",
                "lists",
                "deletes",
                "objects",
                "overwrites",
            },
        ),
        (official, {"total_physical_reads", "maximum_physical_reads", "automatic_retries"}),
        (
            provider,
            {
                "automatic_retries",
                "identical_snapshot_attempts",
                "provider_requests",
                "credits_used",
                "dns_resolutions",
                "maximum_dns_resolutions",
                "maximum_credits",
            },
        ),
        (effect_summary, {"unaccounted_external_effects"}),
        (embedded_bindings, {"secret_writes_attempted", "secret_writes_confirmed"}),
        (
            qa_summary,
            {"passed", "total", "qa_acceptance_percent", "p0", "p1", "p2", "open_threads"},
        ),
        (canonical, {"record_count", "canonical_bytes"}),
        (normalized_team_aliases, {"entries"}),
        (
            horizon_reconciliation,
            {"provider_dns", "provider_tcp", "provider_http", "secret_reads"},
        ),
        (
            live_projection_proof,
            {
                "remaining_postgresql_read_transactions",
                "remaining_postgresql_mutating_function_calls",
                "remaining_postgresql_connection_attempts",
            },
        ),
    )
    coverage_integer_fields = {
        "fixtures_available",
        "fixtures_captured",
        "markets_requested",
        "markets_returned",
        "records_normalized",
        "records_rejected",
    }
    if (
        any(not _exact_integer_fields(value, fields) for value, fields in integer_boundaries)
        or any(
            not _exact_integer_fields(row, coverage_integer_fields) for row in coverage_rows
        )
        or any(
            not _exact_integer_fields(row, {"records"}) for row in normalized_record_types
        )
        or any(
            not _exact_integer_fields(
                row,
                {"used_before", "used_after", "remaining_after", "credits_used"},
            )
            for row in provider_transitions
        )
        or any(type(value) is not int for value in reconciliation_fixture_counts.values())
        or any(
            not _exact_integer_fields(row, {"count"}) for row in quality_rejects
        )
        or any(
            not _exact_integer_fields(row, {"bytes"}) for row in manifest_artifacts
        )
        or not _exact_integer_fields(
            chain_summary, {"official_effects", "odds_effects", "r2_operations"}
        )
        or any(
            type(chain_summary.get(field)) is not bool
            for field in (
                "all_external_sources_confirmed",
                "all_embedded_r2_terminal",
                "final_r2_terminal_requires_append_only_resolution",
            )
        )
        or type(quality.get("logical_duplicates")) is not int
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")

    runtime_integer_fields = {
        "postgresql": {
            "read_transactions_attempted",
            "function_reads_attempted",
            "mutating_function_calls_attempted",
            "mutating_function_calls_completed",
            "mutating_function_outcomes_ambiguous",
            "possible_durable_mutations_upper_bound",
            "connection_attempts_upper_bound",
            "connection_attempts_maximum",
            "automatic_retries",
        },
        "official": {"physical_reads_attempted", "automatic_retries"},
        "odds": {
            "dns_resolutions_attempted",
            "provider_requests_attempted",
            "credits_used_upper_bound",
            "automatic_retries",
        },
        "r2": {
            "puts_attempted",
            "gets_attempted",
            "lists_attempted",
            "deletes_attempted",
            "put_outcomes_ambiguous_upper_bound",
            "automatic_retries",
        },
    }
    for runtime_document in (live_runtime_before, live_runtime):
        if set(runtime_document) != {
            "schema_version",
            "accounting_status",
            "postgresql",
            "official",
            "odds",
            "r2",
        }:
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        for name, fields in runtime_integer_fields.items():
            nested = runtime_document.get(name)
            if (
                not isinstance(nested, dict)
                or set(nested) != fields
                or not _exact_integer_fields(cast(dict[str, object], nested), fields)
            ):
                raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    _validate_recovery_v2_terminal_live_counter_closure(
        actual=actual,
        provider=provider,
        live_runtime_before=live_runtime_before,
        live_runtime=live_runtime,
    )
    try:
        expected_live_runtime = _terminal_live_effects_projection(live_runtime_before)
    except Exception:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    try:
        expected_member_names = {
            "config/team-alias-registry-v1.json",
            "data/normalized-records.jsonl",
            "data/rejected-records.jsonl",
            "lineage/raw-to-normalized-v1.json",
            "reports/coverage-v1.csv",
        }
        if (
            set(normalized_binding)
            != {
                "schema_version",
                "role",
                "object_key",
                "object_bytes",
                "object_sha256",
                "operation_id",
                "terminal_event",
                "terminal_event_hash",
                "archive_format",
                "members",
                "canonical_dataset_sha256",
                "terminal_artifacts_location",
            }
            or normalized_binding.get("schema_version")
            != "robin-data-torrent-normalized-evidence-binding-v2"
            or normalized_binding.get("role") != "NORMALIZED_EVIDENCE"
            or normalized_binding.get("terminal_event") != "CREATED_CONFIRMED"
            or normalized_binding.get("archive_format") != "DETERMINISTIC_USTAR_GZIP_V1"
            or normalized_binding.get("terminal_artifacts_location")
            != "GITHUB_RUN_ARTIFACT_AFTER_REPLAY_AND_TERMINAL_QA"
            or len(normalized_members) != 5
        ):
            raise ValueError
        member_index: dict[str, dict[str, Any]] = {}
        for member in normalized_members:
            member_name = member.get("name")
            if (
                set(member) != {"name", "bytes", "sha256"}
                or not isinstance(member_name, str)
                or member_name in member_index
                or type(member.get("bytes")) is not int
                or cast(int, member["bytes"]) < 0
                or not isinstance(member.get("sha256"), str)
                or _HEX_64.fullmatch(cast(str, member["sha256"])) is None
            ):
                raise ValueError
            member_index[member_name] = member
        if (
            set(member_index) != expected_member_names
            or [cast(str, row["name"]) for row in normalized_members]
            != sorted(expected_member_names)
        ):
            raise ValueError
        capture_started = _authority_timestamp(
            replay_required.get("window_started_at_utc"),
            field="live_capture_started_at",
        )
        capture_ended = _authority_timestamp(
            replay_required.get("window_ended_at_utc"),
            field="live_capture_ended_at",
        )
        horizon_anchor = _authority_timestamp(
            manifest_horizon.get("anchor_utc"),
            field="live_horizon_anchor",
        )
        horizon_not_before = _authority_timestamp(
            manifest_horizon.get("not_before_utc"),
            field="live_horizon_not_before",
        )
        horizon_expires = _authority_timestamp(
            manifest_horizon.get("expires_at_utc"),
            field="live_horizon_expires",
        )
        generated_at = _authority_timestamp(
            replay.get("generated_at_utc"),
            field="live_replay_generated_at",
        )
        if (
            capture_started != horizon_anchor
            or horizon_not_before != horizon_anchor
            or capture_ended <= capture_started
            or horizon_expires <= horizon_anchor
            or generated_at < capture_ended
        ):
            raise ValueError
        normalized_batch_fingerprint = hashlib.sha256(
            canonical_json_bytes(
                {
                    "canonical_dataset_bytes_sha256": member_index[
                        "data/normalized-records.jsonl"
                    ]["sha256"],
                    "canonical_dataset_sha256": canonical_sha,
                    "rejects_bytes_sha256": member_index[
                        "data/rejected-records.jsonl"
                    ]["sha256"],
                    "coverage_csv_sha256": hashlib.sha256(
                        artifacts["torrent-real-batch-coverage-matrix-v1.csv"]
                    ).hexdigest(),
                    "record_count": counts["normalized_records"],
                    "reject_count": rejected_records,
                    "coverage": coverage_rows,
                    "raw_events_observed": source_accounting["observed"],
                    "raw_events_accounted": source_accounting["accounted"],
                    "silent_drops": source_accounting["silent"],
                    "logical_duplicates": counts["logical_duplicates"],
                    "temporal_leakage": counts["temporal_leakage"],
                }
            )
        ).hexdigest()
    except (
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
        OverflowError,
        ChronosProductionError,
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None

    try:
        coverage_fields = {
            "league",
            "sport_key",
            "fixtures_available",
            "fixtures_captured",
            "market",
            "markets_requested",
            "markets_returned",
            "records_normalized",
            "records_rejected",
            "coverage_percentage",
            "absence_reason",
        }
        expected_cells = [
            (league.sport_key, league.name, market)
            for league in config.leagues
            for market in config.markets
        ]
        fixtures_once: dict[str, int] = {}
        odds_records = 0
        for row, (sport_key, league_name, market) in zip(
            coverage_rows, expected_cells, strict=True
        ):
            if (
                set(row) != coverage_fields
                or row.get("sport_key") != sport_key
                or row.get("league") != league_name
                or row.get("market") != market
                or type(row.get("fixtures_available")) is not int
                or cast(int, row["fixtures_available"]) <= 0
                or row.get("fixtures_captured") != row.get("fixtures_available")
                or row.get("markets_requested") != 1
                or row.get("markets_returned") != 1
                or type(row.get("records_normalized")) is not int
                or cast(int, row["records_normalized"]) <= 0
                or type(row.get("records_rejected")) is not int
                or cast(int, row["records_rejected"]) < 0
                or row.get("coverage_percentage") != 100.0
                or row.get("absence_reason") != "NONE"
            ):
                raise ValueError
            available = cast(int, row["fixtures_available"])
            if sport_key in fixtures_once and fixtures_once[sport_key] != available:
                raise ValueError
            fixtures_once[sport_key] = available
            odds_records += cast(int, row["records_normalized"])
        official_records = sum(fixtures_once.values())
        expected_record_types = [
            {"record_type": "ODDS_OUTCOME", "records": odds_records},
            {"record_type": "OFFICIAL_FIXTURE", "records": official_records},
        ]
        expected_record_types.sort(key=lambda row: cast(str, row["record_type"]))
        if (
            set(normalized)
            != {
                "schema_version",
                "mission_id",
                "generated_at_utc",
                "run_identity",
                "claim_identity",
                "archive_object",
                "members",
                "canonicalization",
                "team_aliases",
                "record_type_counts",
                "league_market_counts",
                "totals",
                "canonical_dataset_sha256",
            }
            or normalized.get("schema_version")
            != "robin-data-torrent-normalized-index-v1"
            or normalized.get("mission_id") != DATA_TORRENT_RECOVERY_V2_MISSION_ID
            or normalized.get("archive_object") != normalized_binding
            or normalized.get("members") != normalized_members
            or normalized.get("canonicalization")
            != {
                "version": "ROBIN_CANONICAL_JSON_LINES_V1",
                "sort_key": "record_id",
                "encoding": "UTF-8",
                "line_ending": "LF",
            }
            or normalized.get("team_aliases") != expected_alias_binding
            or normalized_record_types != expected_record_types
            or set(normalized_totals)
            != {
                "normalized_records",
                "rejected_records",
                "logical_duplicates",
                "canonical_bytes",
            }
            or normalized_totals.get("normalized_records")
            != official_records + odds_records
            or normalized_totals.get("canonical_bytes")
            != member_index["data/normalized-records.jsonl"]["bytes"]
        ):
            raise ValueError
        normalized_generated_at = _authority_timestamp(
            normalized.get("generated_at_utc"), field="normalized_index_generated_at"
        )
        manifest_generated_at = _authority_timestamp(
            manifest.get("generated_at_utc"), field="live_manifest_generated_at"
        )
        quality_generated_at = _authority_timestamp(
            quality.get("generated_at_utc"), field="live_quality_generated_at"
        )
        qa_generated_at = _authority_timestamp(
            qa_matrix.get("generated_at_utc"), field="live_qa_generated_at"
        )
        horizon_fields = {
            "anchor_utc",
            "not_before_utc",
            "expires_at_utc",
            "primary_days",
            "fallback_days",
            "fallback_threshold",
            "primary_fixture_count",
            "selected_days",
            "fallback_triggered",
            "selected_fixture_count",
            "no_backfill",
            "reconciliation",
        }
        fallback = manifest_horizon.get("fallback_triggered")
        primary_count = manifest_horizon.get("primary_fixture_count")
        selected_days = manifest_horizon.get("selected_days")
        selected_fixtures = manifest_horizon.get("selected_fixture_count")
        reconciliation_sources = horizon_reconciliation.get("source_sha256")
        reconciliation_adapters = horizon_reconciliation.get("adapter_revisions")
        reconciliation_sports = horizon_reconciliation.get("sport_keys")
        reconciliation_observed = _authority_timestamp(
            horizon_reconciliation.get("observed_at_utc"),
            field="live_reconciliation_observed_at",
        )
        if (
            set(manifest_horizon) != horizon_fields
            or manifest_horizon.get("primary_days") != config.primary_horizon_days
            or manifest_horizon.get("fallback_days") != config.fallback_horizon_days
            or manifest_horizon.get("fallback_threshold")
            != config.fallback_if_fixtures_below
            or type(primary_count) is not int
            or primary_count < 0
            or type(fallback) is not bool
            or fallback != (primary_count < config.fallback_if_fixtures_below)
            or selected_days
            != (config.fallback_horizon_days if fallback else config.primary_horizon_days)
            or type(selected_fixtures) is not int
            or selected_fixtures != official_records
            or manifest_horizon.get("no_backfill") is not True
            or horizon_not_before != horizon_anchor
            or horizon_expires != horizon_anchor + timedelta(days=cast(int, selected_days))
            or counts.get("fixtures_captured") != selected_fixtures
            or set(horizon_reconciliation)
            != {
                "schema_version",
                "observed_at_utc",
                "sport_keys",
                "fixture_counts",
                "source_sha256",
                "adapter_revisions",
                "complete_official_horizon",
                "provider_dns",
                "provider_tcp",
                "provider_http",
                "secret_reads",
            }
            or horizon_reconciliation.get("schema_version")
            != "robin-official-schedule-reconciliation-v1"
            or reconciliation_sports != league_keys
            or set(reconciliation_fixture_counts) != set(league_keys)
            or reconciliation_fixture_counts != fixtures_once
            or not isinstance(reconciliation_sources, dict)
            or set(reconciliation_sources) != set(league_keys)
            or any(
                not isinstance(value, str) or _HEX_64.fullmatch(value) is None
                for value in reconciliation_sources.values()
            )
            or not isinstance(reconciliation_adapters, dict)
            or reconciliation_adapters
            != {league.sport_key: league.official_source.adapter for league in config.leagues}
            or horizon_reconciliation.get("complete_official_horizon") is not True
            or any(
                horizon_reconciliation.get(field) != 0
                for field in ("provider_dns", "provider_tcp", "provider_http", "secret_reads")
            )
            or not capture_started <= reconciliation_observed <= capture_ended
        ):
            raise ValueError
    except (
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
        OverflowError,
        ChronosProductionError,
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None

    def finite_number(value: object) -> bool:
        if type(value) not in {int, float}:
            return False
        try:
            return math.isfinite(float(cast(int | float, value)))
        except (OverflowError, ValueError):
            return False

    def exact_float(actual_value: object, expected_value: float) -> bool:
        return finite_number(actual_value) and math.isclose(
            float(cast(int | float, actual_value)),
            expected_value,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )

    replay_wall_value = replay_measurement.get("wall_clock_seconds")
    if (
        type(counts.get("normalized_records")) is not int
        or cast(int, counts["normalized_records"]) <= 0
        or type(counts.get("raw_bytes")) is not int
        or cast(int, counts["raw_bytes"]) <= 0
        or type(rejected_records) is not int
        or rejected_records < 0
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    replay_wall = (
        float(cast(int | float, replay_wall_value))
        if finite_number(replay_wall_value)
        else -1.0
    )
    equivalent_records = cast(int, counts["normalized_records"]) * 100
    total_replay_bytes = cast(int, counts["raw_bytes"]) * 100
    capture_seconds = (capture_ended - capture_started).total_seconds()
    required_rps = cast(int, counts["normalized_records"]) / capture_seconds
    required_bps = cast(int, counts["raw_bytes"]) / capture_seconds
    measured_rps = equivalent_records / replay_wall if replay_wall > 0 else -1.0
    measured_bps = total_replay_bytes / replay_wall if replay_wall > 0 else -1.0
    records_ratio = measured_rps / required_rps
    bytes_ratio = measured_bps / required_bps
    minimum_ratio = min(records_ratio, bytes_ratio)
    expected_replay_external_fields = {
        "official_reads",
        "odds_dns_resolutions",
        "odds_provider_dispatches",
        "odds_credits",
        "r2_puts",
        "r2_gets",
        "r2_lists",
        "r2_deletes",
        "postgresql_read_transactions",
        "postgresql_function_reads",
        "postgresql_mutating_function_calls",
    }
    expected_replay_acceptance = {
        "raw_archive_binding_pass": True,  # nosec B105
        "volume_pass": True,  # nosec B105
        "throughput_pass": minimum_ratio >= config.minimum_throughput_ratio,
        "canonical_equality_pass": True,  # nosec B105
        "idempotence_pass": True,  # nosec B105
        "no_external_effect_pass": True,  # nosec B105
    }
    expected_identity_fields = {
        "github_repository",
        "github_run_id",
        "github_run_attempt",
        "github_sha",
        "github_ref",
        "github_workflow_ref",
        "github_workflow_sha",
        "workflow_path",
        "workflow_file_sha256",
        "code_revision",
        "runner_os",
        "runner_arch",
        "post_merge_ci_sha",
    }
    expected_claim_fields = {
        "schema_version",
        "mission_id",
        "run_identity",
        "opportunity_id",
        "opportunity_kind",
        "canonical_key",
        "mission_manifest_sha256",
        "mission_source_sha256",
        "torrent_config_sha256",
        "acquired_now",
        "winner_authority_id",
        "winner_github_run_id",
        "winner_github_run_attempt",
        "db_claimed_at_utc",
        "postgres_server_epoch_utc",
        "claim_receipt_hash",
        "first_external_permit_at_utc",
        "claim_before_first_external_effect",
        "cross_run_contract_proof",
        "chronos_release_chain_proof",
    }
    if any(
        set(row) != {"reason_code", "count"}
        or not isinstance(row.get("reason_code"), str)
        or not cast(str, row["reason_code"])
        for row in quality_rejects
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    expected_reason_counts: dict[str, int] = {}
    for row in lineage_rejects:
        reason = row.get("reason")
        if not isinstance(reason, str) or not reason:
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        expected_reason_counts[reason] = expected_reason_counts.get(reason, 0) + 1
    expected_quality_rejects = [
        {"reason_code": reason, "count": count}
        for reason, count in sorted(expected_reason_counts.items())
    ]
    expected_quality_gates = [
        {"gate_id": "silent_drops", "status": "PASS", "observed": 0, "required": 0},
        {
            "gate_id": "logical_duplicates",
            "status": "PASS",
            "observed": 0,
            "required": 0,
        },
        {
            "gate_id": "temporal_leakage",
            "status": "PASS",
            "observed": 0,
            "required": 0,
        },
        {
            "gate_id": "replay_multiplier",
            "status": "PASS",
            "observed": 100,
            "required": 100,
        },
        {
            "gate_id": "throughput_ratio",
            "status": "PASS",
            "observed": minimum_ratio,
            "required": config.minimum_throughput_ratio,
        },
        {
            "gate_id": "unaccounted_external_effects",
            "status": "PASS",
            "observed": 0,
            "required": 0,
        },
    ]
    if (
        len(quality_gates) != len(expected_quality_gates)
        or any(set(row) != {"gate_id", "status", "observed", "required"} for row in quality_gates)
        or any(
            not _exact_integer_fields(row, {"observed", "required"})
            for index, row in enumerate(quality_gates)
            if index != 4
        )
        or not finite_number(quality_gates[4].get("observed"))
        or not finite_number(quality_gates[4].get("required"))
        or quality_gates[:4] != expected_quality_gates[:4]
        or quality_gates[4].get("gate_id") != "throughput_ratio"
        or quality_gates[4].get("status") != "PASS"
        or not exact_float(quality_gates[4].get("observed"), minimum_ratio)
        or not exact_float(
            quality_gates[4].get("required"), config.minimum_throughput_ratio
        )
        or quality_gates[5:] != expected_quality_gates[5:]
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    canonical_opportunity_key = canonical_json_bytes(
        {
            "mission_id": DATA_TORRENT_RECOVERY_V2_MISSION_ID,
            "authorization_source_sha256": DATA_TORRENT_RECOVERY_V2_OWNER_DIRECTIVE_SHA256,
        }
    ).decode("utf-8")
    expected_opportunity_id = derive_opportunity_id(
        opportunity_kind="DATA_TORRENT_MISSION_AUTHORIZATION",
        canonical_key=canonical_opportunity_key,
    )
    if (
        set(manifest)
        != {
            "schema_version",
            "mission_id",
            "generated_at_utc",
            "status",
            "evidence_validity",
            "config_sha256",
            "run_identity",
            "post_merge_ci_proof",
            "chronos_release_chain_proof",
            "claim_identity",
            "production",
            "scope",
            "horizon",
            "execution",
            "counts",
            "effect_summary",
            "durability",
            "integrity",
            "artifacts",
            "canonical_dataset_sha256",
            "data_torrent_ready",
            "hypotheses_generated",
            "purchases",
            "missed_windows",
            "edge_promotions",
            "bet_calls",
        }
        or manifest.get("schema_version")
        != "robin-data-torrent-real-batch-manifest-v1"
        or manifest.get("mission_id") != DATA_TORRENT_RECOVERY_V2_MISSION_ID
        or manifest.get("config_sha256") != config.canonical_sha256
        or evidence_validity
        != {
            "mode": "DIRECT_CREATED_DURABLE_BINDING_V2",
            "binding": normalized_binding,
            "unbound_status": "INVALID",
        }
        or set(scope)
        != {
            "season",
            "region",
            "leagues_enabled",
            "markets_enabled",
            "minimum_fixture_coverage_percentage",
            "team_aliases",
        }
        or scope_team_aliases
        != {
            "artifact": "config/alias_equipes.yaml",
            "entries": len(team_aliases),
            "mapping_sha256": alias_document["mapping_sha256"],
            "registry_artifact_sha256": expected_alias_binding[
                "registry_artifact_sha256"
            ],
            "matching_mode": "ONE_HOP_EXACT_ONLY",
        }
        or manifest_execution
        != {
            "official_batch_status": "SUCCESS",
            "odds_snapshot_status": "SUCCESS",
            "odds_selection_mode": "FULL",
            "automatic_retries": 0,
            "identical_snapshot_attempts": 1,
            "safety_locks": dict(PRODUCTION_SAFETY_LOCKS),
        }
        or set(effect_summary)
        != {
            "limits",
            "actual",
            "live_runtime_effects_before_terminal_database_receipts",
            "live_runtime_effects",
            "live_runtime_effects_projection_proof",
            "unaccounted_external_effects",
        }
        or effect_limits
        != {
            "official_physical_reads_max": config.budgets.official_physical_reads_max,
            "odds_provider_requests_max": config.budgets.odds_provider_requests_max,
            "odds_credits_max": config.budgets.odds_credits_max,
            "automatic_retries": config.budgets.automatic_retries,
            "r2_puts_max": config.budgets.r2_puts_max,
            "r2_gets_max": config.budgets.r2_gets_max,
            "r2_lists_max": config.budgets.r2_lists_max,
            "r2_deletes_max": config.budgets.r2_deletes_max,
            "odds_dns_resolutions_max": len(config.leagues),
        }
        or set(manifest_identity) != expected_identity_fields
        or manifest_identity.get("github_repository") != EXPECTED_REPOSITORY
        or type(manifest_identity.get("github_run_id")) is not int
        or cast(int, manifest_identity["github_run_id"]) <= 0
        or type(manifest_identity.get("github_run_attempt")) is not int
        or manifest_identity.get("github_run_attempt") != 1
        or manifest_identity.get("github_ref") != EXPECTED_REF
        or manifest_identity.get("workflow_path")
        != ".github/workflows/data-torrent-live-v2.yml"
        or manifest_identity.get("runner_os") != "Linux"
        or manifest_identity.get("runner_arch") != "X64"
        or manifest_identity.get("github_sha") != manifest_identity.get("code_revision")
        or manifest_identity.get("github_sha") != manifest_identity.get("post_merge_ci_sha")
        or manifest_identity.get("github_sha") != manifest_identity.get("github_workflow_sha")
        or manifest_identity.get("github_workflow_ref")
        != (
            f"{EXPECTED_REPOSITORY}/.github/workflows/data-torrent-live-v2.yml@"
            "refs/heads/main"
        )
        or not isinstance(manifest_identity.get("workflow_file_sha256"), str)
        or _HEX_64.fullmatch(cast(str, manifest_identity["workflow_file_sha256"])) is None
        or scope.get("season") != config.season
        or scope.get("region") != config.region
        or scope.get("minimum_fixture_coverage_percentage") != 100.0
        or leagues
        != [
            {"sport_key": item.sport_key, "name": item.name}
            for item in config.leagues
        ]
        or markets != list(config.markets)
        or manifest.get("status") != "SUCCESS"
        or manifest.get("data_torrent_ready") is not True
        or manifest.get("hypotheses_generated") != 0
        or manifest.get("edge_promotions") != 0
        or manifest.get("bet_calls") != 0
        or manifest.get("purchases") != 0
        or manifest.get("missed_windows") != "MISSED_NOT_BACKDATED"
        or len(leagues) != 5
        or any(
            not isinstance(row.get("sport_key"), str)
            or not cast(str, row["sport_key"]).strip()
            or not isinstance(row.get("name"), str)
            or not cast(str, row["name"]).strip()
            for row in leagues
        )
        or len(set(league_keys)) != 5
        or markets != ["h2h", "totals"]
        or set(counts)
        != {
            "leagues_enabled",
            "leagues_with_real_data",
            "fixtures_available",
            "fixtures_captured",
            "markets_requested",
            "markets_returned",
            "raw_responses",
            "raw_bytes",
            "official_physical_reads",
            "odds_provider_requests",
            "odds_credits_used",
            "odds_dns_resolutions",
            "accounting_status",
            "accounted_responses",
            "silent_responses",
            "normalized_records",
            "rejected_records",
            "silent_drops",
            "logical_duplicates",
            "temporal_leakage",
        }
        or counts.get("leagues_enabled") != 5
        or counts.get("leagues_with_real_data") != 5
        or counts.get("fixtures_available") != official_records
        or counts.get("fixtures_captured") != official_records
        or cast(int, counts["fixtures_captured"]) <= 0
        or counts.get("markets_requested") != 2
        or counts.get("markets_returned") != 2
        or counts.get("official_physical_reads") != official.get("total_physical_reads")
        or counts.get("odds_provider_requests") != provider.get("provider_requests")
        or counts.get("odds_credits_used") != provider.get("credits_used")
        or counts.get("odds_dns_resolutions") != provider.get("dns_resolutions")
        or counts.get("accounting_status") != "COMPLETE"
        or counts.get("accounted_responses") != counts.get("raw_responses")
        or counts.get("silent_responses") != 0
        or len(coverage_rows) != 10
        or returned_markets != ["h2h", "totals"]
        or len(observed_coverage_cells) != 10
        or observed_coverage_cells != expected_coverage_cells
        or any(
            not isinstance(row, dict)
            or row.get("markets_requested") != 1
            or row.get("markets_returned") != 1
            or type(row.get("fixtures_captured")) is not int
            or cast(int, row["fixtures_captured"]) <= 0
            or row.get("absence_reason") != "NONE"
            or row.get("coverage_percentage") != 100.0
            for row in coverage_rows
        )
        or any(
            type(counts.get(field)) is not int or cast(int, counts[field]) <= 0
            for field in ("raw_responses", "raw_bytes", "normalized_records")
        )
        or type(rejected_records) is not int
        or rejected_records < 0
        or counts.get("normalized_records") != normalized_totals.get("normalized_records")
        or counts.get("rejected_records") != rejected_records
        or counts.get("logical_duplicates") != normalized_totals.get("logical_duplicates")
        or any(counts.get(field) != 0 for field in ("silent_drops", "logical_duplicates", "temporal_leakage"))
        or not isinstance(canonical_sha, str)
        or _HEX_64.fullmatch(canonical_sha) is None
        or normalized.get("canonical_dataset_sha256") != canonical_sha
        or set(canonical)
        != {
            "schema_version",
            "algorithm",
            "canonicalization",
            "record_count",
            "canonical_bytes",
            "original_sha256",
            "replay_sha256",
            "equality",
        }
        or canonical.get("schema_version")
        != "robin-data-torrent-canonical-dataset-hash-v1"
        or canonical.get("algorithm") != "SHA-256"
        or canonical.get("canonicalization") != "ROBIN_CANONICAL_JSON_LINES_V1"
        or canonical.get("original_sha256") != canonical_sha
        or canonical.get("replay_sha256") != canonical_sha
        or canonical.get("equality") is not True
        or canonical.get("record_count") != counts.get("normalized_records")
        or canonical.get("canonical_bytes") != normalized_totals.get("canonical_bytes")
        or normalized_binding.get("canonical_dataset_sha256") != canonical_sha
        or member_index["data/normalized-records.jsonl"].get("sha256") != canonical_sha
        or member_index["reports/coverage-v1.csv"].get("sha256")
        != hashlib.sha256(artifacts["torrent-real-batch-coverage-matrix-v1.csv"]).hexdigest()
        or artifacts["torrent-real-batch-coverage-matrix-v1.csv"]
        != coverage_csv(coverage_rows)
        or replay_input.get("canonical_dataset_sha256") != canonical_sha
        or replay_input.get("normalized_batch_fingerprint") != normalized_batch_fingerprint
        or replay_measurement.get("unique_normalized_batch_fingerprints")
        != [normalized_batch_fingerprint]
        or replay_input.get("raw_archive_sha256") != raw_object.get("object_sha256")
        or replay_input.get("replay_source")
        != "LOCALLY_RETAINED_RAW_ARCHIVE_BYTES_AFTER_RAW_AND_NORMALIZED_CREATED_CONFIRMED"
        or replay_input.get("raw_archive_decode_count") != 100
        or replay_input.get("raw_payload_parse_iterations") != 100
        or replay_input.get("raw_bytes_per_iteration") != counts.get("raw_bytes")
        or replay_input.get("normalized_records_per_iteration")
        != counts.get("normalized_records")
        or replay_input.get("rejected_records_per_iteration") != rejected_records
        or replay_input.get("normalized_durable_binding") != normalized_binding
        or replay_measurement.get("unique_canonical_hashes") != [canonical_sha]
        or replay.get("schema_version") != "robin-data-torrent-load-replay-report-v1"
        or set(replay)
        != {
            "schema_version",
            "mission_id",
            "generated_at_utc",
            "input",
            "normal_required_throughput",
            "replay",
            "measurement",
            "throughput",
            "external_effects_delta",
            "acceptance",
            "status",
            "cross_run_loser_contract_proof",
            "chronos_release_chain_proof",
        }
        or set(replay_input)
        != {
            "raw_archive_sha256",
            "replay_source",
            "raw_archive_decode_count",
            "raw_payload_parse_iterations",
            "raw_bytes_per_iteration",
            "canonical_dataset_sha256",
            "normalized_batch_fingerprint",
            "normalized_records_per_iteration",
            "rejected_records_per_iteration",
            "normalized_durable_binding",
        }
        or set(replay_required)
        != {
            "basis",
            "window_started_at_utc",
            "window_ended_at_utc",
            "elapsed_seconds",
            "records_per_second",
            "bytes_per_second",
        }
        or set(replay_run)
        != {
            "multiplier",
            "equivalent_normalized_records",
            "iterations_completed",
            "total_records_processed",
            "total_bytes_processed",
        }
        or set(replay_measurement)
        != {
            "wall_clock_seconds",
            "records_per_second",
            "bytes_per_second",
            "latency_sample_unit",
            "latency_sample_count",
            "p50_latency_ms",
            "p95_latency_ms",
            "baseline_rss_bytes",
            "peak_memory_bytes",
            "incremental_peak_memory_bytes",
            "rejects",
            "duplicates",
            "silent_losses",
            "unique_canonical_hashes",
            "unique_normalized_batch_fingerprints",
        }
        or set(replay_throughput)
        != {"records_ratio", "bytes_ratio", "minimum_ratio", "required_minimum_ratio"}
        or set(replay_acceptance)
        != {
            "raw_archive_binding_pass",
            "volume_pass",
            "throughput_pass",
            "canonical_equality_pass",
            "idempotence_pass",
            "no_external_effect_pass",
        }
        or any(type(value) is not bool for value in replay_acceptance.values())
        or replay.get("mission_id") != DATA_TORRENT_RECOVERY_V2_MISSION_ID
        or replay.get("status") != "PASS"
        or replay_run.get("multiplier") != 100
        or replay_run.get("iterations_completed") != 100
        or replay_run.get("equivalent_normalized_records")
        != cast(int, counts["normalized_records"]) * 100
        or replay_run.get("total_records_processed") != equivalent_records
        or replay_run.get("total_bytes_processed") != total_replay_bytes
        or replay_required.get("basis") != "REAL_BATCH_CAPTURE_WINDOW"
        or not exact_float(replay_required.get("elapsed_seconds"), capture_seconds)
        or not exact_float(replay_required.get("records_per_second"), required_rps)
        or not exact_float(replay_required.get("bytes_per_second"), required_bps)
        or replay_wall <= 0
        or not exact_float(replay_measurement.get("records_per_second"), measured_rps)
        or not exact_float(replay_measurement.get("bytes_per_second"), measured_bps)
        or replay_measurement.get("latency_sample_unit") != "BATCH_REPLAY_ITERATION"
        or replay_measurement.get("latency_sample_count") != 100
        or type(replay_measurement.get("records_per_second")) not in {int, float}
        or cast(float, replay_measurement["records_per_second"]) <= 0
        or type(replay_measurement.get("p95_latency_ms")) not in {int, float}
        or cast(float, replay_measurement["p95_latency_ms"]) < 0
        or not finite_number(replay_measurement.get("p50_latency_ms"))
        or not finite_number(replay_measurement.get("p95_latency_ms"))
        or not 0
        <= float(cast(int | float, replay_measurement["p50_latency_ms"]))
        <= float(cast(int | float, replay_measurement["p95_latency_ms"]))
        <= replay_wall * 1000.0
        or type(replay_measurement.get("peak_memory_bytes")) is not int
        or cast(int, replay_measurement["peak_memory_bytes"]) <= 0
        or type(replay_measurement.get("baseline_rss_bytes")) is not int
        or cast(int, replay_measurement["baseline_rss_bytes"]) < 0
        or cast(int, replay_measurement["peak_memory_bytes"])
        < cast(int, replay_measurement["baseline_rss_bytes"])
        or type(replay_measurement.get("incremental_peak_memory_bytes")) is not int
        or cast(int, replay_measurement["incremental_peak_memory_bytes"]) < 0
        or replay_measurement.get("rejects") != rejected_records * 100
        or set(replay_external) != expected_replay_external_fields
        or any(type(value) is not int or value != 0 for value in replay_external.values())
        or replay_acceptance != expected_replay_acceptance
        or not exact_float(replay_throughput.get("records_ratio"), records_ratio)
        or not exact_float(replay_throughput.get("bytes_ratio"), bytes_ratio)
        or not exact_float(replay_throughput.get("minimum_ratio"), minimum_ratio)
        or replay_throughput.get("required_minimum_ratio") != config.minimum_throughput_ratio
        or minimum_ratio < config.minimum_throughput_ratio
        or replay_measurement.get("duplicates") != 0
        or replay_measurement.get("silent_losses") != 0
        or replay.get("cross_run_loser_contract_proof") != post_merge_proof
        or replay.get("chronos_release_chain_proof") != release_chain
        or manifest.get("claim_identity") != claim
        or normalized.get("claim_identity") != claim.get("opportunity_id")
        or quality.get("claim_identity") != claim.get("opportunity_id")
        or raw_index.get("claim_identity") != claim.get("opportunity_id")
        or normalized.get("run_identity") != manifest_identity
        or quality.get("run_identity") != manifest_identity
        or raw_index.get("run_identity") != manifest_identity
        or set(claim) != expected_claim_fields
        or claim.get("schema_version")
        != "robin-data-torrent-opportunity-claim-receipt-v1"
        or claim.get("mission_id") != DATA_TORRENT_RECOVERY_V2_MISSION_ID
        or claim.get("mission_manifest_sha256") != DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256
        or claim.get("mission_source_sha256")
        != DATA_TORRENT_RECOVERY_V2_OWNER_DIRECTIVE_SHA256
        or claim.get("torrent_config_sha256") != config.canonical_sha256
        or claim.get("opportunity_kind") != "DATA_TORRENT_MISSION_AUTHORIZATION"
        or claim.get("canonical_key") != canonical_opportunity_key
        or claim.get("opportunity_id") != expected_opportunity_id
        or claim.get("run_identity") != manifest_identity
        or claim.get("winner_github_run_id") != manifest_identity.get("github_run_id")
        or claim.get("winner_github_run_attempt")
        != manifest_identity.get("github_run_attempt")
        or claim.get("acquired_now") is not True
        or claim.get("claim_before_first_external_effect") is not True
        or claim.get("cross_run_contract_proof") != post_merge_proof
        or claim.get("chronos_release_chain_proof") != release_chain
        or not isinstance(claim.get("claim_receipt_hash"), str)
        or _HEX_64.fullmatch(cast(str, claim["claim_receipt_hash"])) is None
        or set(quality)
        != {
            "schema_version",
            "mission_id",
            "generated_at_utc",
            "run_identity",
            "claim_identity",
            "response_accounting",
            "source_unit_accounting",
            "rejects_by_reason",
            "logical_duplicates",
            "temporal",
            "coverage",
            "durability",
            "lineage",
            "replay",
            "external_effects",
            "gates",
            "quality_status",
        }
        or quality.get("schema_version") != "robin-data-torrent-quality-report-v1"
        or quality.get("mission_id") != DATA_TORRENT_RECOVERY_V2_MISSION_ID
        or quality.get("quality_status") != "PASS"
        or quality_response
        != {
            "observed": counts.get("raw_responses"),
            "accounted": counts.get("raw_responses"),
            "silent": 0,
        }
        or source_accounting
        != {
            "observed": counts.get("raw_responses"),
            "accounted": counts.get("raw_responses"),
            "silent": 0,
        }
        or quality_rejects != expected_quality_rejects
        or set(quality_temporal)
        != {
            "timezone_missing",
            "backfill",
            "future_information",
            "post_event_as_pre_event",
            "leakage_total",
            "missed_windows",
        }
        or quality_temporal.get("leakage_total") != 0
        or quality_temporal.get("timezone_missing") != 0
        or quality_temporal.get("backfill") != 0
        or quality_temporal.get("future_information") != 0
        or quality_temporal.get("post_event_as_pre_event") != 0
        or quality_temporal.get("missed_windows") != "MISSED_NOT_BACKDATED"
        or quality_coverage.get("expected_cells") != 10
        or quality_coverage.get("emitted_cells") != 10
        or quality_coverage.get("incomplete_cells") != 0
        or set(quality_coverage)
        != {
            "expected_cells",
            "emitted_cells",
            "minimum_fixture_coverage_percentage",
            "minimum_observed_fixture_coverage_percentage",
            "incomplete_cells",
        }
        or not exact_float(
            quality_coverage.get("minimum_fixture_coverage_percentage"), 100.0
        )
        or not exact_float(
            quality_coverage.get("minimum_observed_fixture_coverage_percentage"),
            min(float(cast(int | float, row["coverage_percentage"])) for row in coverage_rows),
        )
        or not _json_exact_equal(
            quality_durability,
            {
                "raw_verified": True,
                "normalized_verified": "DIRECT_CREATED_CONFIRMED_BEFORE_REPLAY_V2",
                "normalized_evidence_binding": normalized_binding,
            },
        )
        or quality_lineage
        != {
            "raw_responses_covered": counts.get("raw_responses"),
            "normalized_records_covered": counts.get("normalized_records"),
            "rejected_units_covered": rejected_records,
        }
        or not _json_exact_equal(
            quality_replay,
            {"canonical_equality": True, "external_reads": 0, "report": replay},
        )
        or quality_external
        != {
            "official_source_operations": 5,
            "official_physical_reads": official.get("total_physical_reads"),
            "odds_provider_operations": 5,
            "odds_dns_resolutions": 5,
            "odds_provider_requests": 5,
            "r2_live_operations": 3,
            "r2_control_plane_operations": 3,
            "r2_mission_operations": 6,
            "r2_objects": 3,
            "accounted": cast(int, official["total_physical_reads"]) + 16,
            "unaccounted": 0,
        }
        or quality.get("logical_duplicates") != 0
        or raw_index_totals.get("raw_responses") != counts.get("raw_responses")
        or raw_index_totals.get("raw_bytes") != counts.get("raw_bytes")
        or raw_index_totals.get("accounted_responses") != counts.get("raw_responses")
        or raw_index_totals.get("silent_responses") != 0
        or raw_index_totals.get("accounting_status") != "COMPLETE"
        or lineage_summary.get("raw_responses_observed")
        != lineage_summary.get("raw_responses_accounted")
        or lineage_summary.get("raw_responses_observed") != counts.get("raw_responses")
        or lineage_summary.get("normalized_records") != counts.get("normalized_records")
        or lineage_summary.get("rejected_units") != rejected_records
        or lineage_summary.get("silent_responses") != 0
        or len(lineage_rejects) != rejected_records
        or any(not isinstance(row.get("reason"), str) or not row["reason"] for row in lineage_rejects)
        or set(integrity)
        != {
            "raw_response_accounting",
            "raw_to_normalized_lineage",
            "canonical_replay_equality",
            "idempotent_replay",
            "temporal_validity",
        }
        or integrity.get("raw_response_accounting") != "COMPLETE"
        or integrity.get("raw_to_normalized_lineage") != "COMPLETE"
        or integrity.get("canonical_replay_equality") is not True
        or integrity.get("idempotent_replay") is not True
        or integrity.get("temporal_validity") != "PASS"
        or set(durability)
        != {
            "raw_object",
            "normalized_evidence_binding",
            "verification_status",
        }
        or durability.get("verification_status") != "CREATED_CONFIRMED_BEFORE_REPLAY"
        or raw_object.get("role") != "RAW"
        or raw_object.get("terminal_event") != "CREATED_CONFIRMED"
        or normalized_binding.get("role") != "NORMALIZED_EVIDENCE"
        or normalized_binding.get("terminal_event") != "CREATED_CONFIRMED"
        or set(inventory)
        != {
            "schema_version",
            "objects",
            "counters",
            "control_plane_release",
            "mission_counters",
            "limits",
            "live_limits",
            "mission_limits",
        }
        or inventory.get("schema_version") != "robin-data-torrent-r2-inventory-v1"
        or inventory_objects != [raw_object, normalized_binding]
        or inventory.get("control_plane_release") != release_chain.get("identity_seal")
        or inventory_live
        != {
            "puts": 2,
            "gets": 1,
            "lists": 0,
            "deletes": 0,
            "objects": 2,
            "overwrites": 0,
            "validity": "DIRECT_CREATED_RECEIPT_V2",
        }
        or inventory_mission
        != {"puts": 3, "gets": 3, "lists": 0, "deletes": 0, "objects": 3, "overwrites": 0}
        or inventory_limits
        != {"puts": 2, "gets": 1, "lists": 0, "deletes": 0}
        or inventory_live_limits != inventory_limits
        or inventory_mission_limits
        != {"puts": 3, "gets": 3, "objects": 3, "lists": 0, "deletes": 0}
        or set(actual)
        != {
            "official_physical_reads",
            "odds_dns_resolutions",
            "odds_provider_requests",
            "odds_credits_used",
            "puts",
            "gets",
            "lists",
            "deletes",
            "objects",
            "overwrites",
        }
        or actual.get("official_physical_reads") != official.get("total_physical_reads")
        or actual.get("odds_dns_resolutions") != provider.get("dns_resolutions")
        or actual.get("odds_dns_resolutions") != 5
        or actual.get("odds_provider_requests") != provider.get("provider_requests")
        or actual.get("odds_credits_used") != provider.get("credits_used")
        or actual.get("puts") != 3
        or actual.get("gets") != 3
        or actual.get("objects") != 3
        or actual.get("lists") != 0
        or actual.get("deletes") != 0
        or actual.get("overwrites") != 0
        or live_runtime != expected_live_runtime
        or live_projection_proof
        != {
            "certainty": "EXACT_SUCCESSFUL_PATH_POSTCONDITION",
            "remaining_postgresql_read_transactions": 2,
            "remaining_postgresql_mutating_function_calls": 1,
            "remaining_postgresql_connection_attempts": 3,
            "postgresql_call_graph_raw_sha256": (
                DATA_TORRENT_LIVE_V2_POSTGRESQL_CALL_GRAPH_SHA256
            ),
            "postgresql_call_graph_canonical_sha256": (
                DATA_TORRENT_LIVE_V2_POSTGRESQL_CALL_GRAPH_CANONICAL_SHA256
            ),
            "observed_before_projection_sha256": hashlib.sha256(
                json.dumps(
                    live_runtime_before,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "final_projection_sha256": hashlib.sha256(
                json.dumps(
                    live_runtime,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        }
        or set(official)
        != {
            "schema_version",
            "reads",
            "total_physical_reads",
            "maximum_physical_reads",
            "automatic_retries",
        }
        or official.get("schema_version")
        != "robin-data-torrent-official-read-receipts-v1"
        or official_reads != [row for row in raw_responses if row.get("family") != "ODDS"]
        or official.get("maximum_physical_reads")
        != config.budgets.official_physical_reads_max
        or official.get("automatic_retries") != 0
        or not 1 <= cast(int, official.get("total_physical_reads", 0)) <= 50
        or set(provider)
        != {
            "schema_version",
            "selection_mode",
            "contracts_requested",
            "markets",
            "credit_transitions",
            "credit_accounting",
            "credit_anomalies",
            "automatic_retries",
            "identical_snapshot_attempts",
            "provider_requests",
            "credits_used",
            "dns_resolutions",
            "maximum_dns_resolutions",
            "maximum_credits",
            "errors",
        }
        or provider.get("schema_version")
        != "robin-data-torrent-provider-credit-receipt-v1"
        or provider.get("selection_mode") != "FULL"
        or provider.get("contracts_requested") != league_keys
        or provider.get("markets") != markets
        or provider.get("credit_accounting") != "EXACT"
        or provider.get("credit_anomalies") != []
        or provider.get("identical_snapshot_attempts") != 1
        or provider.get("provider_requests") != 5
        or not 1 <= cast(int, provider.get("credits_used", 0)) <= 1_000
        or provider.get("dns_resolutions") != 5
        or provider.get("maximum_dns_resolutions") != 5
        or provider.get("maximum_credits") != config.budgets.odds_credits_max
        or provider.get("automatic_retries") != 0
        or provider.get("errors") != []
        or len(provider_transitions) != 5
        or [row.get("sport_key") for row in provider_transitions] != league_keys
        or any(
            set(row)
            != {
                "sport_key",
                "used_before",
                "used_after",
                "remaining_after",
                "credits_used",
            }
            or cast(int, row["used_before"]) < 0
            or cast(int, row["used_after"]) < cast(int, row["used_before"])
            or cast(int, row["remaining_after"]) < 0
            or cast(int, row["credits_used"]) < 0
            or cast(int, row["used_after"]) - cast(int, row["used_before"])
            != cast(int, row["credits_used"])
            for row in provider_transitions
        )
        or sum(cast(int, row["credits_used"]) for row in provider_transitions)
        != provider.get("credits_used")
        or live_runtime.get("schema_version") != "robin-data-torrent-live-runtime-effects-v1"
        or live_runtime.get("accounting_status") != "COMPLETE_CONSERVATIVE"
        or type(connection_attempts) is not int
        or not 51 <= connection_attempts <= 53
        or postgresql.get("read_transactions_attempted") != 6
        or not 4 <= cast(int, postgresql.get("function_reads_attempted", -1)) <= 6
        or type(mutating_attempts) is not int
        or mutating_attempts != 41
        or connection_attempts
        != cast(int, postgresql["read_transactions_attempted"])
        + cast(int, postgresql["function_reads_attempted"])
        + mutating_attempts
        or postgresql_before.get("read_transactions_attempted") != 4
        or not 4
        <= cast(int, postgresql_before.get("function_reads_attempted", -1))
        <= 6
        or postgresql_before.get("mutating_function_calls_attempted") != 40
        or postgresql_before.get("connection_attempts_upper_bound")
        != cast(int, postgresql_before["read_transactions_attempted"])
        + cast(int, postgresql_before["function_reads_attempted"])
        + cast(int, postgresql_before["mutating_function_calls_attempted"])
        or postgresql.get("mutating_function_calls_completed") != 41
        or postgresql.get("mutating_function_outcomes_ambiguous") != 0
        or postgresql.get("possible_durable_mutations_upper_bound") != 41
        or postgresql.get("connection_attempts_maximum") != 53
        or postgresql.get("automatic_retries") != 0
        or live_official
        != {"physical_reads_attempted": official["total_physical_reads"], "automatic_retries": 0}
        or live_odds.get("provider_requests_attempted") != 5
        or live_odds.get("dns_resolutions_attempted") != 5
        or live_odds_before.get("dns_resolutions_attempted") != 5
        or live_odds.get("credits_used_upper_bound") != provider.get("credits_used")
        or live_odds.get("automatic_retries") != 0
        or live_r2.get("puts_attempted") != 2
        or live_r2.get("gets_attempted") != 1
        or live_r2.get("lists_attempted") != 0
        or live_r2.get("deletes_attempted") != 0
        or live_r2.get("put_outcomes_ambiguous_upper_bound") != 0
        or live_r2.get("automatic_retries") != 0
        or effect_summary.get("unaccounted_external_effects") != 0
        or set(production)
        != {"database_revision", "runtime_bindings_present", "cloud_runtime"}
        or production.get("database_revision") != EXPECTED_AFTER_REVISION
        or production.get("runtime_bindings_present")
        != [
            "CHRONOS_AUTHORITY_DATABASE_URL",
            "CHRONOS_RUNTIME_DATABASE_URL",
            "CHRONOS_READER_DATABASE_URL",
            "CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
        ]
        or production.get("cloud_runtime") != "ubuntu-latest"
        or embedded_bindings.get("secret_writes_attempted") != 4
        or embedded_bindings.get("secret_writes_confirmed") != 4
        or qa_summary
        != {
            "passed": 22,
            "total": 22,
            "qa_acceptance_percent": 100,
            "p0": 0,
            "p1": 0,
            "p2": 0,
            "open_threads": 0,
        }
        or [row.get("gate_id") for row in qa_gates] != list(_RECOVERY_V2_TERMINAL_QA_GATES)
        or any(row.get("status") != "PASS" for row in qa_gates)
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")

    try:
        claim_time = _authority_timestamp(
            claim.get("db_claimed_at_utc"), field="live_claimed_at"
        )
        first_permit_time = _authority_timestamp(
            claim.get("first_external_permit_at_utc"), field="live_first_permit_at"
        )
        claim_epoch = _authority_timestamp(
            claim.get("postgres_server_epoch_utc"), field="live_claim_server_epoch"
        )
        claim_epoch_text = claim_epoch.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        claim_time_text = claim_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        winner_run_id = claim.get("winner_github_run_id")
        winner_run_attempt = claim.get("winner_github_run_attempt")
        winner_authority_id = claim.get("winner_authority_id")
        code_revision = manifest_identity.get("code_revision")
        if (
            type(winner_run_id) is not int
            or winner_run_id <= 0
            or type(winner_run_attempt) is not int
            or winner_run_attempt != 1
            or not isinstance(winner_authority_id, str)
            or not winner_authority_id
            or not isinstance(code_revision, str)
            or claim.get("claim_receipt_hash")
            != _recovery_v2_framed_sha256(
                "data-torrent-opportunity-claim-v1",
                claim["opportunity_id"],
                winner_authority_id,
                winner_run_id,
                winner_run_attempt,
                code_revision,
                claim_time_text,
                claim_epoch_text,
            )
        ):
            raise ValueError
        if claim_time > first_permit_time:
            raise ValueError
        if (
            set(chain) != {"schema_version", "events", "summary"}
            or chain.get("schema_version")
            != "robin-data-torrent-control-plane-event-chain-v1"
            or set(chain_events)
            != {"external_sources", "r2", "normalized_evidence_terminal_resolver"}
            or len(source_events) != 10
            or chain_events.get("normalized_evidence_terminal_resolver")
            != normalized_binding
            or chain.get("summary")
            != {
                "official_effects": 5,
                "odds_effects": 5,
                "r2_operations": 2,
                "all_external_sources_confirmed": True,
                "all_embedded_r2_terminal": True,
                "final_r2_terminal_requires_append_only_resolution": False,
            }
        ):
            raise ValueError
        expected_sports = [item.sport_key for item in config.leagues]
        family_sequences: dict[str, list[tuple[int, str]]] = {
            "OFFICIAL": [],
            "ODDS": [],
        }
        operation_ids: set[str] = set()
        source_by_operation: dict[str, dict[str, Any]] = {}
        operation_windows: dict[str, tuple[datetime, datetime]] = {}
        official_reads_from_chain = 0
        odds_requests_from_chain = 0
        odds_credits_from_chain = 0
        permit_times: list[datetime] = []
        for source_event in source_events:
            if set(source_event) != {
                "family",
                "sport_key",
                "request_contract",
                "permit",
                "dispatched",
                "terminal",
            }:
                raise ValueError
            family = source_event.get("family")
            source_sport_key = source_event.get("sport_key")
            request_contract = source_event.get("request_contract")
            permit = source_event.get("permit")
            dispatched = source_event.get("dispatched")
            terminal = source_event.get("terminal")
            if (
                family not in family_sequences
                or not isinstance(source_sport_key, str)
                or not isinstance(request_contract, dict)
                or not isinstance(permit, dict)
                or not isinstance(dispatched, dict)
                or not isinstance(terminal, dict)
                or set(permit)
                != {
                    "operation_id",
                    "effect_family",
                    "effect_sequence",
                    "request_hash",
                    "max_official_reads",
                    "max_odds_requests",
                    "max_odds_credits",
                    "created_now",
                    "db_permitted_at",
                    "postgres_server_epoch",
                    "permit_hash",
                }
            ):
                raise ValueError
            operation_id = permit.get("operation_id")
            effect_sequence = permit.get("effect_sequence")
            if (
                not isinstance(operation_id, str)
                or _HEX_64.fullmatch(operation_id) is None
                or operation_id in operation_ids
                or type(effect_sequence) is not int
                or not 1 <= effect_sequence <= 5
                or source_sport_key != expected_sports[effect_sequence - 1]
                or request_contract.get("sport_key") != source_sport_key
                or permit.get("effect_family") != family
                or permit.get("request_hash")
                != hashlib.sha256(canonical_json_bytes(request_contract)).hexdigest()
                or permit.get("created_now") is not True
                or not isinstance(permit.get("permit_hash"), str)
                or _HEX_64.fullmatch(cast(str, permit["permit_hash"])) is None
            ):
                raise ValueError
            if request_contract != _recovery_v2_terminal_expected_source_request_contract(
                family=cast(str, family),
                sport_key=source_sport_key,
                config=config,
                capture_started=capture_started,
            ):
                raise ValueError
            permit_time = _authority_timestamp(
                permit.get("db_permitted_at"), field="live_effect_permitted_at"
            )
            permit_epoch = _authority_timestamp(
                permit.get("postgres_server_epoch"), field="live_effect_server_epoch"
            )
            expected_maxima = (
                (12 if source_sport_key == "soccer_spain_la_liga" else 6, 0, 0)
                if family == "OFFICIAL"
                else (0, 1, 200)
            )
            expected_operation_id = _recovery_v2_framed_sha256(
                "data-torrent-external-effect-v1",
                claim["opportunity_id"],
                winner_run_id,
                winner_run_attempt,
                family,
                effect_sequence,
                permit["request_hash"],
            )
            expected_permit_hash = _recovery_v2_framed_sha256(
                "data-torrent-external-effect-permit-v1",
                expected_operation_id,
                claim["opportunity_id"],
                family,
                effect_sequence,
                permit["request_hash"],
                *expected_maxima,
                permit_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                permit_epoch.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            )
            if (
                permit_time < claim_time
                or permit_epoch != claim_epoch
                or operation_id != expected_operation_id
                or any(
                    type(permit.get(field)) is not int
                    for field in (
                        "max_official_reads",
                        "max_odds_requests",
                        "max_odds_credits",
                    )
                )
                or (
                    permit.get("max_official_reads"),
                    permit.get("max_odds_requests"),
                    permit.get("max_odds_credits"),
                )
                != expected_maxima
                or permit.get("permit_hash") != expected_permit_hash
            ):
                raise ValueError
            permit_times.append(permit_time)
            operation_ids.add(operation_id)
            source_by_operation[operation_id] = source_event
            family_sequences[cast(str, family)].append((effect_sequence, source_sport_key))
            expected_event_fields = {
                "operation_id",
                "event_seq",
                "event_type",
                "actual_official_reads",
                "actual_odds_requests",
                "actual_odds_credits",
                "db_recorded_at",
                "postgres_server_epoch",
                "previous_event_hash",
                "event_hash",
            }
            if (
                set(dispatched) != expected_event_fields
                or set(terminal) != expected_event_fields
                or dispatched.get("operation_id") != operation_id
                or terminal.get("operation_id") != operation_id
                or type(dispatched.get("event_seq")) is not int
                or type(terminal.get("event_seq")) is not int
                or dispatched.get("event_seq") != 1
                or terminal.get("event_seq") != 2
                or dispatched.get("event_type") != "DISPATCHED"
                or terminal.get("event_type") != "CONFIRMED"
                or terminal.get("previous_event_hash") != dispatched.get("event_hash")
                or any(
                    not isinstance(event.get(field), str)
                    or _HEX_64.fullmatch(cast(str, event[field])) is None
                    for event in (dispatched, terminal)
                    for field in ("event_hash",)
                )
                or any(
                    type(event.get(field)) is not int
                    or cast(int, event[field]) < 0
                    for event in (dispatched, terminal)
                    for field in (
                        "actual_official_reads",
                        "actual_odds_requests",
                        "actual_odds_credits",
                    )
                )
                or any(dispatched.get(field) != 0 for field in (
                    "actual_official_reads",
                    "actual_odds_requests",
                    "actual_odds_credits",
                ))
            ):
                raise ValueError
            dispatched_at = _authority_timestamp(
                dispatched.get("db_recorded_at"), field="live_effect_dispatched_at"
            )
            terminal_at = _authority_timestamp(
                terminal.get("db_recorded_at"), field="live_effect_terminal_at"
            )
            dispatched_epoch = _authority_timestamp(
                dispatched.get("postgres_server_epoch"), field="live_effect_server_epoch"
            )
            terminal_epoch = _authority_timestamp(
                terminal.get("postgres_server_epoch"), field="live_effect_server_epoch"
            )
            expected_dispatch_hash = _recovery_v2_framed_sha256(
                "data-torrent-external-effect-event-v1",
                operation_id,
                1,
                "DISPATCHED",
                0,
                0,
                0,
                dispatched_at.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                dispatched_epoch.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                expected_permit_hash,
            )
            expected_terminal_hash = _recovery_v2_framed_sha256(
                "data-torrent-external-effect-event-v1",
                operation_id,
                2,
                "CONFIRMED",
                terminal["actual_official_reads"],
                terminal["actual_odds_requests"],
                terminal["actual_odds_credits"],
                terminal_at.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                terminal_epoch.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                expected_dispatch_hash,
            )
            terminal_accounting = (
                1 <= cast(int, terminal["actual_official_reads"]) <= expected_maxima[0]
                and terminal["actual_odds_requests"] == 0
                and terminal["actual_odds_credits"] == 0
                if family == "OFFICIAL"
                else terminal["actual_official_reads"] == 0
                and terminal["actual_odds_requests"] == 1
                and 0 <= cast(int, terminal["actual_odds_credits"]) <= expected_maxima[2]
            )
            if (
                dispatched_at < permit_time
                or terminal_at < dispatched_at
                or dispatched_epoch != claim_epoch
                or terminal_epoch != claim_epoch
                or dispatched.get("previous_event_hash") != expected_permit_hash
                or dispatched.get("event_hash") != expected_dispatch_hash
                or terminal.get("previous_event_hash") != expected_dispatch_hash
                or terminal.get("event_hash") != expected_terminal_hash
                or not terminal_accounting
            ):
                raise ValueError
            operation_windows[operation_id] = (dispatched_at, terminal_at)
            official_reads_from_chain += cast(int, terminal["actual_official_reads"])
            odds_requests_from_chain += cast(int, terminal["actual_odds_requests"])
            odds_credits_from_chain += cast(int, terminal["actual_odds_credits"])
        expected_sequence_pairs = list(enumerate(expected_sports, start=1))
        if (
            sorted(family_sequences["OFFICIAL"]) != expected_sequence_pairs
            or sorted(family_sequences["ODDS"]) != expected_sequence_pairs
            or min(permit_times) != first_permit_time
            or official_reads_from_chain != official.get("total_physical_reads")
            or odds_requests_from_chain != provider.get("provider_requests")
            or odds_credits_from_chain != provider.get("credits_used")
        ):
            raise ValueError

        response_fields = {
            "response_id",
            "family",
            "sport_key",
            "source",
            "request_contract",
            "retrieved_at_utc",
            "http_status",
            "content_type",
            "response_headers",
            "raw_bytes",
            "raw_sha256",
            "response_sequence",
            "run_identity",
            "claim_identity",
            "effect_accounting",
            "archive_path",
            "disposition",
            "rejection_reason",
        }
        accounting_fields = {
            "effect_id",
            "permit_hash",
            "dispatch_event_hash",
            "confirmation_event_hash",
            "sequence",
            "attempt",
            "physical_reads",
            "provider_requests",
            "provider_credits",
            "automatic_retries",
        }
        expected_run_text = (
            f"github:{EXPECTED_REPOSITORY}:{winner_run_id}:{winner_run_attempt}:"
            f"{code_revision}"
        )
        responses_by_operation: dict[str, list[dict[str, Any]]] = {
            operation_id: [] for operation_id in operation_ids
        }
        response_index: dict[str, dict[str, Any]] = {}
        raw_bytes_total = 0
        physical_reads_total = 0
        provider_requests_total = 0
        provider_credits_total = 0
        response_retrieved_times: list[datetime] = []
        official_source_by_sport = {
            league.sport_key: league.official_source for league in config.leagues
        }
        for expected_sequence, response in enumerate(raw_responses, start=1):
            accounting = response.get("effect_accounting")
            response_id = response.get("response_id")
            raw_sha = response.get("raw_sha256")
            family = response.get("family")
            operation_id = (
                accounting.get("effect_id") if isinstance(accounting, dict) else None
            )
            matched_source_event = source_by_operation.get(cast(str, operation_id))
            if (
                set(response) != response_fields
                or not isinstance(accounting, dict)
                or set(accounting) != accounting_fields
                or not isinstance(response_id, str)
                or _HEX_64.fullmatch(response_id) is None
                or response_id in response_index
                or not isinstance(raw_sha, str)
                or _HEX_64.fullmatch(raw_sha) is None
                or family not in {"OFFICIAL", "OFFICIAL_SUPPORTING", "ODDS"}
                or type(response.get("response_sequence")) is not int
                or response.get("response_sequence") != expected_sequence
                or response.get("run_identity") != expected_run_text
                or response.get("claim_identity") != claim.get("opportunity_id")
                or type(response.get("http_status")) is not int
                or not 100 <= cast(int, response["http_status"]) <= 599
                or type(response.get("raw_bytes")) is not int
                or cast(int, response["raw_bytes"]) <= 0
                or not isinstance(response.get("request_contract"), dict)
                or not isinstance(response.get("response_headers"), dict)
                or any(
                    type(key) is not str or type(value) is not str
                    for key, value in cast(
                        dict[object, object], response["response_headers"]
                    ).items()
                )
                or not isinstance(response.get("source"), str)
                or not cast(str, response["source"])
                or not isinstance(response.get("content_type"), str)
                or not cast(str, response["content_type"])
                or response.get("archive_path")
                != f"responses/{expected_sequence:03d}-{response_id}.bin"
                or response.get("disposition") not in {"ACCEPTED", "REJECTED"}
                or (response.get("disposition") == "ACCEPTED")
                != (response.get("rejection_reason") is None)
                or (
                    response.get("rejection_reason") is not None
                    and not isinstance(response.get("rejection_reason"), str)
                )
                or matched_source_event is None
                or accounting.get("permit_hash")
                != cast(dict[str, Any], matched_source_event["permit"])["permit_hash"]
                or accounting.get("dispatch_event_hash")
                != cast(dict[str, Any], matched_source_event["dispatched"])["event_hash"]
                or accounting.get("confirmation_event_hash")
                != cast(dict[str, Any], matched_source_event["terminal"])["event_hash"]
                or accounting.get("sequence")
                != cast(dict[str, Any], matched_source_event["permit"])["effect_sequence"]
                or any(
                    type(accounting.get(field)) is not int
                    for field in (
                        "sequence",
                        "attempt",
                        "physical_reads",
                        "provider_requests",
                        "provider_credits",
                        "automatic_retries",
                    )
                )
                or accounting.get("attempt") != 1
                or accounting.get("physical_reads") != 1
                or accounting.get("automatic_retries") != 0
                or any(
                    type(accounting.get(field)) is not int
                    or cast(int, accounting[field]) < 0
                    for field in (
                        "provider_requests",
                        "provider_credits",
                    )
                )
                or response_id
                != hashlib.sha256(
                    canonical_json_bytes(
                        {
                            "family": family,
                            "sport_key": response.get("sport_key"),
                            "sequence": expected_sequence,
                            "raw_sha256": raw_sha,
                        }
                    )
                ).hexdigest()
            ):
                raise ValueError
            retrieved_at = _authority_timestamp(
                response.get("retrieved_at_utc"), field="raw_response_retrieved_at"
            )
            validate_request_contract_safety(response.get("request_contract"))
            validate_response_metadata_safety(
                source=response.get("source"),
                response_headers=response.get("response_headers"),
            )
            dispatched_at, terminal_at = operation_windows[cast(str, operation_id)]
            _validate_recovery_v2_terminal_response_observation(
                retrieved_at=retrieved_at,
                dispatched_at=dispatched_at,
                terminal_at=terminal_at,
                capture_started=capture_started,
                capture_ended=capture_ended,
            )
            if family != "ODDS":
                try:
                    _validate_official_url(
                        cast(str, response["source"]),
                        official_source_by_sport[cast(str, response["sport_key"])],
                    )
                except (KeyError, OfficialScheduleSourceError):
                    raise ValueError from None
            responses_by_operation[cast(str, operation_id)].append(response)
            response_index[response_id] = response
            response_retrieved_times.append(retrieved_at)
            raw_bytes_total += cast(int, response["raw_bytes"])
            physical_reads_total += cast(int, accounting["physical_reads"])
            provider_requests_total += cast(int, accounting["provider_requests"])
            provider_credits_total += cast(int, accounting["provider_credits"])
        for operation_id, responses in responses_by_operation.items():
            source_event = source_by_operation[operation_id]
            source_family = cast(str, source_event["family"])
            terminal = cast(dict[str, Any], source_event["terminal"])
            request_contract = cast(dict[str, Any], source_event["request_contract"])
            if not responses:
                raise ValueError
            for physical_index, response in enumerate(responses):
                accounting = cast(dict[str, Any], response["effect_accounting"])
                expected_contract = (
                    request_contract
                    if source_family == "ODDS"
                    else {
                        **request_contract,
                        "sanitized_endpoint": response["source"],
                        "physical_response_index": physical_index,
                        "logical_request_endpoint": request_contract["sanitized_endpoint"],
                    }
                )
                if (
                    response.get("sport_key") != source_event["sport_key"]
                    or response.get("family")
                    not in (
                        {"ODDS"}
                        if source_family == "ODDS"
                        else {"OFFICIAL", "OFFICIAL_SUPPORTING"}
                    )
                    or response.get("request_contract") != expected_contract
                    or response.get("source") != expected_contract.get("sanitized_endpoint")
                    or (
                        accounting.get("provider_requests"),
                        accounting.get("provider_credits"),
                    )
                    != (
                        (1, terminal["actual_odds_credits"])
                        if source_family == "ODDS"
                        else (0, 0)
                    )
                ):
                    raise ValueError
            if (
                sum(cast(int, row["effect_accounting"]["physical_reads"]) for row in responses)
                != terminal["actual_official_reads"] + terminal["actual_odds_requests"]
                or sum(
                    cast(int, row["effect_accounting"]["provider_requests"])
                    for row in responses
                )
                != terminal["actual_odds_requests"]
                or sum(
                    cast(int, row["effect_accounting"]["provider_credits"])
                    for row in responses
                )
                != terminal["actual_odds_credits"]
            ):
                raise ValueError
        expected_raw_totals = {
            "raw_responses": len(raw_responses),
            "raw_bytes": raw_bytes_total,
            "official_physical_reads": sum(
                1 for response in raw_responses if response["family"] != "ODDS"
            ),
            "odds_provider_requests": provider_requests_total,
            "odds_credits_used": provider_credits_total,
            "odds_dns_resolutions": len(config.leagues),
            "accounting_status": "COMPLETE",
            "accounted_responses": len(raw_responses),
            "silent_responses": 0,
        }
        if (
            set(raw_index)
            != {
                "schema_version",
                "mission_id",
                "generated_at_utc",
                "run_identity",
                "claim_identity",
                "responses",
                "totals",
                "archive_object",
            }
            or raw_index_totals != expected_raw_totals
            or raw_index.get("archive_object")
            != {
                "object_key": raw_object.get("object_key"),
                "bytes": raw_object.get("object_bytes"),
                "sha256": raw_object.get("object_sha256"),
                "media_type": "application/gzip",
                "format": "DETERMINISTIC_USTAR_GZIP_V1",
            }
            or physical_reads_total != len(raw_responses)
        ):
            raise ValueError
        raw_index_generated_at = _authority_timestamp(
            raw_index.get("generated_at_utc"), field="raw_index_generated_at"
        )
        _validate_recovery_v2_terminal_generated_chronology(
            latest_retrieved_at=max(response_retrieved_times),
            raw_index_generated_at=raw_index_generated_at,
            capture_ended=capture_ended,
            replay_generated_at=generated_at,
            quality_generated_at=quality_generated_at,
            normalized_generated_at=normalized_generated_at,
            qa_generated_at=qa_generated_at,
            manifest_generated_at=manifest_generated_at,
        )

        lineage_raw_fields = {
            "response_id",
            "response_sequence",
            "family",
            "raw_sha256",
            "disposition",
            "rejection_reason",
            "external_operation_id",
            "external_effect_sequence",
            "accounting_role",
            "normalized_records",
            "rejected_units",
            "linked_primary_response_id",
            "accounted",
        }
        record_fields = {
            "record_id",
            "source_response_id",
            "source_raw_sha256",
            "source_pointer",
            "source_pointer_domain",
            "source_adapter_revision",
        }
        reject_fields = {
            "reject_id",
            "source_response_id",
            "source_raw_sha256",
            "source_pointer",
            "reason",
        }
        normalized_counts: dict[str, int] = {response_id: 0 for response_id in response_index}
        reject_counts: dict[str, int] = {response_id: 0 for response_id in response_index}
        record_ids: list[str] = []
        reject_ids: list[str] = []
        for row in lineage_records:
            source_id = row.get("source_response_id")
            if (
                set(row) != record_fields
                or not isinstance(row.get("record_id"), str)
                or not cast(str, row["record_id"])
                or not isinstance(source_id, str)
                or source_id not in response_index
                or row.get("source_raw_sha256") != response_index[source_id]["raw_sha256"]
                or not isinstance(row.get("source_pointer"), str)
                or any(
                    value is not None and not isinstance(value, str)
                    for value in (
                        row.get("source_pointer_domain"),
                        row.get("source_adapter_revision"),
                    )
                )
            ):
                raise ValueError
            record_ids.append(cast(str, row["record_id"]))
            normalized_counts[source_id] += 1
        for row in lineage_rejects:
            source_id = row.get("source_response_id")
            if (
                set(row) != reject_fields
                or not isinstance(row.get("reject_id"), str)
                or not cast(str, row["reject_id"])
                or not isinstance(source_id, str)
                or source_id not in response_index
                or row.get("source_raw_sha256") != response_index[source_id]["raw_sha256"]
                or not isinstance(row.get("source_pointer"), str)
                or not isinstance(row.get("reason"), str)
                or not cast(str, row["reason"])
            ):
                raise ValueError
            reject_ids.append(cast(str, row["reject_id"]))
            reject_counts[source_id] += 1
        if (
            record_ids != sorted(record_ids)
            or len(record_ids) != len(set(record_ids))
            or reject_ids != sorted(reject_ids)
            or len(reject_ids) != len(set(reject_ids))
        ):
            raise ValueError
        primary_by_operation = {
            cast(str, row["effect_accounting"]["effect_id"]): cast(str, row["response_id"])
            for row in raw_responses
            if row["family"] == "OFFICIAL"
        }
        expected_lineage_rows: list[dict[str, Any]] = []
        for response in raw_responses:
            response_id = cast(str, response["response_id"])
            normalized_count = normalized_counts[response_id]
            rejected_count = reject_counts[response_id]
            operation_id = cast(str, response["effect_accounting"]["effect_id"])
            supporting_primary = (
                primary_by_operation.get(operation_id)
                if response["family"] == "OFFICIAL_SUPPORTING"
                else None
            )
            role = (
                "NORMALIZED_WITH_EXPLICIT_REJECTS"
                if normalized_count and rejected_count
                else "NORMALIZED_SOURCE"
                if normalized_count
                else "EXPLICIT_REJECT_SOURCE"
                if rejected_count
                else "SUPPORTING_PHYSICAL_EVIDENCE"
                if supporting_primary is not None
                else "PRIMARY_OFFICIAL_SELECTION_EVIDENCE"
                if response["family"] == "OFFICIAL"
                else "UNACCOUNTED"
            )
            expected_lineage_rows.append(
                {
                    "response_id": response_id,
                    "response_sequence": response["response_sequence"],
                    "family": response["family"],
                    "raw_sha256": response["raw_sha256"],
                    "disposition": response["disposition"],
                    "rejection_reason": response["rejection_reason"],
                    "external_operation_id": operation_id,
                    "external_effect_sequence": response["effect_accounting"]["sequence"],
                    "accounting_role": role,
                    "normalized_records": normalized_count,
                    "rejected_units": rejected_count,
                    "linked_primary_response_id": supporting_primary,
                    "accounted": role != "UNACCOUNTED",
                }
            )
        if (
            set(lineage) != {"schema_version", "raw_responses", "records", "rejects", "summary"}
            or lineage.get("schema_version")
            != "robin-data-torrent-raw-to-normalized-lineage-v1"
            or any(set(row) != lineage_raw_fields for row in lineage_raw)
            or any(
                not _exact_integer_fields(
                    row,
                    {
                        "response_sequence",
                        "external_effect_sequence",
                        "normalized_records",
                        "rejected_units",
                    },
                )
                for row in lineage_raw
            )
            or lineage_raw != expected_lineage_rows
            or any(row["accounted"] is not True for row in lineage_raw)
            or lineage_summary
            != {
                "raw_responses_observed": len(raw_responses),
                "raw_responses_accounted": len(raw_responses),
                "normalized_records": len(lineage_records),
                "rejected_units": len(lineage_rejects),
                "silent_responses": 0,
            }
            or len(lineage_records) != normalized_totals["normalized_records"]
            or len(lineage_rejects) != normalized_totals["rejected_records"]
        ):
            raise ValueError
        r2_events = chain_events.get("r2")
        raw_events = raw_object.get("events")
        if (
            not isinstance(r2_events, list)
            or not isinstance(raw_events, list)
            or len(r2_events) != 6
            or len(raw_events) != 3
            or r2_events[:3] != raw_events
            or any(not isinstance(event, dict) for event in r2_events)
            or [cast(dict[str, Any], event).get("event_seq") for event in r2_events[:3]]
            != [1, 2, 3]
            or [cast(dict[str, Any], event).get("event_type") for event in r2_events[:3]]
            != ["EFFECT_RESERVED", "PUT_DISPATCHED", "CREATED_CONFIRMED"]
            or [cast(dict[str, Any], event).get("event_seq") for event in r2_events[3:]]
            != [1, 2, 3]
            or [cast(dict[str, Any], event).get("event_type") for event in r2_events[3:]]
            != ["EFFECT_RESERVED", "PUT_DISPATCHED", "CREATED_CONFIRMED"]
            or cast(dict[str, Any], r2_events[-1]).get("operation_id")
            != normalized_binding.get("operation_id")
            or cast(dict[str, Any], r2_events[-1]).get("event_hash")
            != normalized_binding.get("terminal_event_hash")
            or cast(dict[str, Any], r2_events[-1]).get("event_type") != "CREATED_CONFIRMED"
        ):
            raise ValueError
        if (
            set(raw_object)
            != {
                "role",
                "object_key",
                "object_bytes",
                "object_sha256",
                "operation_id",
                "authority_id",
                "authority_receipt_hash",
                "terminal_event",
                "terminal_event_hash",
                "etag",
                "events",
            }
            or type(raw_object.get("object_bytes")) is not int
            or cast(int, raw_object["object_bytes"]) <= 0
            or not isinstance(raw_object.get("object_sha256"), str)
            or _HEX_64.fullmatch(cast(str, raw_object["object_sha256"])) is None
            or not isinstance(raw_object.get("authority_id"), str)
            or not cast(str, raw_object["authority_id"])
            or not isinstance(raw_object.get("authority_receipt_hash"), str)
            or _HEX_64.fullmatch(cast(str, raw_object["authority_receipt_hash"])) is None
            or not isinstance(raw_object.get("etag"), str)
            or not cast(str, raw_object["etag"])
            or type(normalized_binding.get("object_bytes")) is not int
            or cast(int, normalized_binding["object_bytes"]) <= 0
        ):
            raise ValueError
        r2_event_fields = {
            "event_id",
            "event_seq",
            "operation_id",
            "authority_id",
            "event_type",
            "resource_kind",
            "resource_key",
            "payload_hash",
            "db_recorded_at",
            "github_run_id",
            "github_run_attempt",
            "code_revision",
            "previous_event_hash",
            "event_hash",
        }
        r2_segments = (
            (
                cast(list[dict[str, Any]], r2_events[:3]),
                raw_object,
                f"{DATA_TORRENT_RECOVERY_V2_MISSION_ID}-raw-r2",
            ),
            (
                cast(list[dict[str, Any]], r2_events[3:]),
                normalized_binding,
                f"{DATA_TORRENT_RECOVERY_V2_MISSION_ID}-normalized-evidence-r2",
            ),
        )
        seen_r2_operations: set[str] = set()
        seen_r2_events: set[str] = set()
        for segment, binding, r2_mission_id in r2_segments:
            object_key = binding.get("object_key")
            payload_hash = binding.get("object_sha256")
            expected_object_key = (
                f"data-torrent/recovery-v2/{claim['opportunity_id']}/raw.tar.gz"
                if r2_mission_id.endswith("-raw-r2")
                else (
                    f"data-torrent/recovery-v2/{claim['opportunity_id']}/"
                    "normalized-evidence.tar.gz"
                )
            )
            if (
                not isinstance(object_key, str)
                or object_key != expected_object_key
                or not isinstance(payload_hash, str)
                or _HEX_64.fullmatch(payload_hash) is None
            ):
                raise ValueError
            expected_operation = _recovery_v2_framed_sha256(
                r2_mission_id,
                winner_run_id,
                winner_run_attempt,
                "R2_OBJECT",
                object_key,
                payload_hash,
            )
            if (
                expected_operation in seen_r2_operations
                or binding.get("operation_id") != expected_operation
            ):
                raise ValueError
            seen_r2_operations.add(expected_operation)
            authority_id = segment[0].get("authority_id")
            if not isinstance(authority_id, str) or not authority_id:
                raise ValueError
            grant_template = dict(segment[0])
            grant_template.update(
                {
                    "event_seq": 0,
                    "event_type": "AUTHORITY_GRANTED",
                    "previous_event_hash": None,
                }
            )
            previous_hash = _recovery_v2_chronos_event_hash(
                grant_template,
                previous_event_hash="",
            )
            previous_time: datetime | None = None
            for expected_seq, expected_type, event in zip(
                (1, 2, 3),
                ("EFFECT_RESERVED", "PUT_DISPATCHED", "CREATED_CONFIRMED"),
                segment,
                strict=True,
            ):
                recorded_at = _authority_timestamp(
                    event.get("db_recorded_at"), field="live_r2_event_recorded_at"
                )
                computed_hash = _recovery_v2_chronos_event_hash(
                    event,
                    previous_event_hash=previous_hash,
                )
                if (
                    set(event) != r2_event_fields
                    or not _exact_integer_fields(
                        event, {"event_seq", "github_run_id", "github_run_attempt"}
                    )
                    or event.get("event_seq") != expected_seq
                    or event.get("operation_id") != expected_operation
                    or event.get("authority_id") != authority_id
                    or event.get("event_type") != expected_type
                    or event.get("resource_kind") != "R2_OBJECT"
                    or event.get("resource_key") != object_key
                    or event.get("payload_hash") != payload_hash
                    or event.get("github_run_id") != winner_run_id
                    or event.get("github_run_attempt") != winner_run_attempt
                    or event.get("code_revision") != code_revision
                    or event.get("previous_event_hash") != previous_hash
                    or event.get("event_hash") != computed_hash
                    or event.get("event_id") != f"chronos-event:{computed_hash}"
                    or computed_hash in seen_r2_events
                    or (previous_time is not None and recorded_at < previous_time)
                ):
                    raise ValueError
                seen_r2_events.add(computed_hash)
                previous_hash = computed_hash
                previous_time = recorded_at
            if (
                binding.get("terminal_event") != "CREATED_CONFIRMED"
                or binding.get("terminal_event_hash") != previous_hash
                or (
                    binding is raw_object
                    and binding.get("authority_id") != authority_id
                )
            ):
                raise ValueError
    except (
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
        OverflowError,
        ChronosProductionError,
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None

    live_effects = {field: 0 for field in _RECOVERY_V2_STAGE_EFFECT_FIELDS}
    live_effects.update(
        {
            "postgresql_connection_attempts_upper_bound": connection_attempts,
            "postgresql_read_transactions_attempted": cast(
                int, postgresql["read_transactions_attempted"]
            ),
            "postgresql_function_reads_attempted": cast(
                int, postgresql["function_reads_attempted"]
            ),
            "postgresql_mutating_function_calls_attempted": mutating_attempts,
            "postgresql_mutating_function_calls_completed": cast(
                int, postgresql["mutating_function_calls_completed"]
            ),
            "postgresql_mutating_function_outcomes_ambiguous": cast(
                int, postgresql["mutating_function_outcomes_ambiguous"]
            ),
            "postgresql_possible_durable_mutations_upper_bound": cast(
                int, postgresql["possible_durable_mutations_upper_bound"]
            ),
            "r2_puts": 2,
            "r2_gets": 1,
            "r2_objects": 2,
            "official_reads": cast(int, official["total_physical_reads"]),
            "provider_requests": 5,
            "provider_credits": cast(int, provider["credits_used"]),
            "leagues": 5,
            "league_market_cells": 10,
        }
    )
    replay_effects = {field: 0 for field in _RECOVERY_V2_STAGE_EFFECT_FIELDS}
    return {
        "production_state": {
            "production_database_revision": EXPECTED_AFTER_REVISION,
            "runtime_bindings_present": production["runtime_bindings_present"],
            "binding_writes": 4,
        },
        "data_metrics": {
            "leagues_enabled": 5,
            "leagues_with_real_data": 5,
            "fixtures_captured": counts["fixtures_captured"],
            "markets_requested": markets,
            "markets_returned": returned_markets,
            "league_market_cells": 10,
            "league_market_cells_non_empty": True,
            "official_physical_reads": official["total_physical_reads"],
            "odds_provider_requests": provider["provider_requests"],
            "odds_credits_used": provider["credits_used"],
            "raw_responses": counts["raw_responses"],
            "raw_bytes": counts["raw_bytes"],
            "normalized_records": counts["normalized_records"],
            "rejected_records": rejected_records,
            "rejected_records_reason_coded": True,
            "silent_drops": 0,
            "logical_duplicates": 0,
            "temporal_leakage": 0,
            "canonical_dataset_sha256": canonical_sha,
            "raw_durable": True,
            "normalized_durable": True,
            "lineage_complete": True,
            "missed_windows": "MISSED_NOT_BACKDATED",
        },
        "qa": {
            "acceptance_percent": 100,
            "p0": 0,
            "p1": 0,
            "p2": 0,
            "open_threads": 0,
            "gates": [
                {"name": cast(str, row["gate_id"]), "status": "PASS"} for row in qa_gates
            ],
        },
        "live_effects": live_effects,
        "replay_effects": replay_effects,
        "replay": {
            "iterations_exact": 100,
            "equivalent_records": replay_run["equivalent_normalized_records"],
            "external_effects": 0,
            "output_sha256": canonical_sha,
            "payload_filename": "torrent-load-replay-report-v1.json",
            "payload_sha256": hashlib.sha256(
                artifacts["torrent-load-replay-report-v1.json"]
            ).hexdigest(),
            "records_per_second": replay_measurement["records_per_second"],
            "p95_latency_ms": replay_measurement["p95_latency_ms"],
            "peak_memory_bytes": replay_measurement["peak_memory_bytes"],
            "idempotent": True,
        },
        "embedded_runtime_bindings": embedded_bindings,
        "release_chain": release_chain,
        "run_identity": manifest_identity,
        "post_merge_ci_proof": post_merge_proof,
        "claim": claim,
    }


def _recovery_v2_terminal_stage_evidence(
    root: Path,
    *,
    runtime_main_sha: str,
    live_attestation: Mapping[str, object],
    live_artifact_payloads: Mapping[str, bytes],
    live_semantics: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    """Derive every runtime-stage proof from copied immutable bytes and controller journals."""

    # Reuse the controller's pure structural validators so the terminal Council
    # proof cannot silently accept a weaker artifact than the one admitted at
    # dispatch time.  The import is deliberately local: the controller imports
    # this module, but terminal validation only runs after both modules load.
    try:
        from robin.chronos_role_lifecycle import EXECUTOR_TOMBSTONE_MARKER
        from scripts.dispatch_data_torrent_recovery_v2_stage import (
            _validate_migration_target,
            _validate_verify_identities,
            _validated_post_merge_hold,
        )
    except ImportError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None

    singleton_attestations: dict[str, dict[str, Any]] = {}
    singleton_documents: dict[str, dict[str, Any]] = {}
    singleton_payloads: dict[str, bytes] = {}
    controller_documents: dict[str, dict[str, Any]] = {}
    controller_payloads: dict[str, bytes] = {}
    evidence_payload_hashes: set[str] = set()
    evidence_archive_hashes: set[str] = set()
    evidence_run_ids: set[int] = set()
    evidence_artifact_ids: set[int] = set()

    for stage in _RECOVERY_V2_CONTROLLER_ORDER:
        paths = DATA_TORRENT_RECOVERY_V2_STAGE_EVIDENCE_PATHS[stage]
        controller_payload, controller = _recovery_v2_strict_json(
            root / paths["controller"],
            maximum_bytes=2 * 1024 * 1024,
            repository_root=root,
        )
        controller_documents[stage] = controller
        controller_payloads[stage] = controller_payload
        evidence_payload_hashes.add(hashlib.sha256(controller_payload).hexdigest())
        if stage == "LIVE_ONCE":
            continue
        attestation_payload, attestation = _recovery_v2_strict_json(
            root / paths["attestation"],
            maximum_bytes=262_144,
            repository_root=root,
        )
        payload = _recovery_v2_evidence_bytes(
            root / paths["payload"],
            repository_root=root,
            maximum_bytes=10 * 1024 * 1024,
        )
        workflow_path, _semantic_verdict, payload_filename = (
            _RECOVERY_V2_TERMINAL_WORKFLOW_STAGES[stage]
        )
        run_id = attestation.get("run_id")
        artifact_id = attestation.get("artifact_id")
        if (
            set(attestation)
            != {
                "schema_version",
                "repository",
                "workflow_path",
                "run_id",
                "run_attempt",
                "head_sha",
                "artifact_id",
                "artifact_name",
                "payload_sha256",
                "archive_sha256",
            }
            or attestation.get("schema_version") != "github-artifact-attestation-v2"
            or attestation.get("repository") != EXPECTED_REPOSITORY
            or attestation.get("workflow_path") != workflow_path
            or not isinstance(run_id, str)
            or _RUN_ID.fullmatch(run_id) is None
            or run_id == "0"
            or attestation.get("run_attempt") != "1"
            or attestation.get("head_sha") != runtime_main_sha
            or type(artifact_id) is not int
            or artifact_id <= 0
            or attestation.get("artifact_name")
            != _RECOVERY_V2_TERMINAL_ARTIFACT_PREFIXES[stage] + run_id
            or attestation.get("payload_sha256") != hashlib.sha256(payload).hexdigest()
            or not isinstance(attestation.get("archive_sha256"), str)
            or _HEX_64.fullmatch(cast(str, attestation["archive_sha256"])) is None
            or Path(paths["payload"]).name != payload_filename
        ):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        singleton_attestations[stage] = attestation
        singleton_payloads[stage] = payload
        singleton_documents[stage] = _recovery_v2_json_artifact(payload)
        evidence_payload_hashes.update(
            {
                hashlib.sha256(attestation_payload).hexdigest(),
                hashlib.sha256(payload).hexdigest(),
            }
        )
        evidence_archive_hashes.add(cast(str, attestation["archive_sha256"]))
        if int(run_id) in evidence_run_ids or artifact_id in evidence_artifact_ids:
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        evidence_run_ids.add(int(run_id))
        evidence_artifact_ids.add(artifact_id)

    bindings_payload, bindings_document = _recovery_v2_strict_json(
        root / DATA_TORRENT_RECOVERY_V2_BINDINGS_EVIDENCE_PATH,
        maximum_bytes=262_144,
        repository_root=root,
    )
    evidence_payload_hashes.add(hashlib.sha256(bindings_payload).hexdigest())
    provider_payload, provider_receipt = _recovery_v2_strict_json(
        root / DATA_TORRENT_RECOVERY_V2_PROVIDER_EVIDENCE_PATH,
        maximum_bytes=512 * 1024,
        repository_root=root,
    )
    quarantine_payload, quarantine_receipt = _recovery_v2_strict_json(
        root / DATA_TORRENT_RECOVERY_V2_QUARANTINE_EVIDENCE_PATH,
        maximum_bytes=512 * 1024,
        repository_root=root,
    )
    provider_sha256 = hashlib.sha256(provider_payload).hexdigest()
    quarantine_sha256 = hashlib.sha256(quarantine_payload).hexdigest()
    evidence_payload_hashes.update({provider_sha256, quarantine_sha256})
    provider_fields = {
        "schema_version",
        "verdict",
        "branch",
        "required_current_sha",
        "target_main_sha",
        "fast_forward_ancestry_confirmed",
        "push_mode",
        "push_attempts",
        "remote_ref_observations",
        "non_fast_forward_updates",
        "branch_deletes",
        "automatic_retries",
        "pre_hold",
        "pre_hold_sha256",
        "confirmed_sha",
        "post_hold",
        "post_hold_sha256",
    }
    provider_pre_hold = provider_receipt.get("pre_hold")
    provider_post_hold = provider_receipt.get("post_hold")
    if (
        set(provider_receipt) != provider_fields
        or provider_receipt.get("schema_version")
        != "data-torrent-recovery-v2-provider-neutralization-v1"
        or provider_receipt.get("verdict") != "LEGACY_PROVIDER_BRANCH_NEUTRALIZED"
        or provider_receipt.get("branch") != "codex/jalon-12-prospective-deep-data-observatory"
        or provider_receipt.get("required_current_sha") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or provider_receipt.get("target_main_sha") != runtime_main_sha
        or provider_receipt.get("confirmed_sha") != runtime_main_sha
        or provider_receipt.get("fast_forward_ancestry_confirmed") is not True
        or provider_receipt.get("push_mode") != "ORDINARY_NON_FORCE_FAST_FORWARD"
        or not _exact_integer_fields(
            provider_receipt,
            {
                "push_attempts",
                "remote_ref_observations",
                "non_fast_forward_updates",
                "branch_deletes",
                "automatic_retries",
            },
        )
        or provider_receipt.get("push_attempts") != 1
        or provider_receipt.get("remote_ref_observations") != 2
        or provider_receipt.get("non_fast_forward_updates") != 0
        or provider_receipt.get("branch_deletes") != 0
        or provider_receipt.get("automatic_retries") != 0
        or not isinstance(provider_pre_hold, dict)
        or not isinstance(provider_post_hold, dict)
        or provider_receipt.get("pre_hold_sha256")
        != hashlib.sha256(canonical_json_bytes(provider_pre_hold)).hexdigest()
        or provider_receipt.get("post_hold_sha256")
        != hashlib.sha256(canonical_json_bytes(provider_post_hold)).hexdigest()
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    try:
        _validated_post_merge_hold(
            provider_pre_hold,
            main_sha=runtime_main_sha,
            allow_new_active=True,
            expected_legacy_sha=DATA_TORRENT_RECOVERY_V2_START_SHA,
        )
        _validated_post_merge_hold(
            provider_post_hold,
            main_sha=runtime_main_sha,
            allow_new_active=True,
        )
    except Exception:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    quarantine_fields = {
        "schema_version",
        "verdict",
        "main_sha",
        "automatic_retries",
        "pre_effect_proof",
        "pre_effect_proof_sha256",
        "initial_workflows",
        "disable_attempted_paths",
        "disable_confirmed_paths",
        "disable_outcomes",
        "unconfirmed_paths",
        "already_disabled_paths",
        "post_hold",
        "post_hold_sha256",
        "github_api_gets_upper_bound",
        "disable_attempts_maximum",
        "enable_mutations",
        "dispatch_mutations",
        "provider_neutralization_provenance",
    }
    quarantine_proof = quarantine_receipt.get("pre_effect_proof")
    quarantine_post_hold = quarantine_receipt.get("post_hold")
    initial_workflows = quarantine_receipt.get("initial_workflows")
    attempted_paths = quarantine_receipt.get("disable_attempted_paths")
    confirmed_paths = quarantine_receipt.get("disable_confirmed_paths")
    disable_outcomes = quarantine_receipt.get("disable_outcomes")
    unconfirmed_paths = quarantine_receipt.get("unconfirmed_paths")
    already_disabled = quarantine_receipt.get("already_disabled_paths")
    new_workflows = tuple(
        sorted(
            {
                ".github/workflows/chronos-identity-seal-v2.yml",
                ".github/workflows/chronos-neon-branch-identity-v2.yml",
                ".github/workflows/chronos-production-bootstrap-v4.yml",
                ".github/workflows/data-torrent-live-v2.yml",
            }
        )
    )
    if (
        set(quarantine_receipt) != quarantine_fields
        or quarantine_receipt.get("schema_version")
        != "data-torrent-recovery-v2-postmerge-quarantine-v1"
        or quarantine_receipt.get("verdict") != "POSTMERGE_QUARANTINE_CONFIRMED"
        or quarantine_receipt.get("main_sha") != runtime_main_sha
        or not _exact_integer_fields(
            quarantine_receipt,
            {
                "automatic_retries",
                "github_api_gets_upper_bound",
                "disable_attempts_maximum",
                "enable_mutations",
                "dispatch_mutations",
            },
        )
        or quarantine_receipt.get("automatic_retries") != 0
        or quarantine_receipt.get("github_api_gets_upper_bound") != 25
        or quarantine_receipt.get("disable_attempts_maximum") != 4
        or quarantine_receipt.get("enable_mutations") != 0
        or quarantine_receipt.get("dispatch_mutations") != 0
        or not _json_exact_equal(
            quarantine_receipt.get("provider_neutralization_provenance"),
            {
                "path": ".torrent/release/recovery-v2-provider-neutralization.json",
                "sha256": provider_sha256,
                "verdict": "LEGACY_PROVIDER_BRANCH_NEUTRALIZED",
            },
        )
        or not isinstance(initial_workflows, list)
        or len(initial_workflows) != 4
        or any(not isinstance(item, dict) for item in initial_workflows)
        or tuple(cast(dict[str, Any], item).get("workflow_path") for item in initial_workflows)
        != new_workflows
        or any(
            set(cast(dict[str, Any], item)) != {"workflow_id", "workflow_path", "state"}
            or type(cast(dict[str, Any], item).get("workflow_id")) is not int
            or cast(int, cast(dict[str, Any], item)["workflow_id"]) <= 0
            or cast(dict[str, Any], item).get("state") not in {"active", "disabled_manually"}
            for item in initial_workflows
        )
        or not isinstance(attempted_paths, list)
        or not isinstance(confirmed_paths, list)
        or attempted_paths != confirmed_paths
        or attempted_paths
        != [
            cast(str, cast(dict[str, Any], item)["workflow_path"])
            for item in initial_workflows
            if cast(dict[str, Any], item)["state"] == "active"
        ]
        or disable_outcomes
        != [
            {"workflow_path": path, "outcome": "CONFIRMED"}
            for path in cast(list[str], attempted_paths)
        ]
        or unconfirmed_paths != []
        or not isinstance(already_disabled, list)
        or already_disabled
        != [
            cast(str, cast(dict[str, Any], item)["workflow_path"])
            for item in initial_workflows
            if cast(dict[str, Any], item)["state"] == "disabled_manually"
        ]
        or not isinstance(quarantine_proof, dict)
        or quarantine_receipt.get("pre_effect_proof_sha256")
        != hashlib.sha256(canonical_json_bytes(quarantine_proof)).hexdigest()
        or not isinstance(quarantine_post_hold, dict)
        or quarantine_receipt.get("post_hold_sha256")
        != hashlib.sha256(canonical_json_bytes(quarantine_post_hold)).hexdigest()
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    _recovery_v2_terminal_hold(quarantine_post_hold, runtime_main_sha=runtime_main_sha)
    binding_fields = {
        "schema_version",
        "verdict",
        "repository",
        "environment",
        "main_sha",
        "preflight_run_id",
        "preflight_hash",
        "preflight_controller_receipt_sha256",
        "secret_writes_attempted",
        "secret_writes_confirmed",
        "secret_names_in_order",
        "secret_value_readbacks",
        "automatic_retries",
        "global_hold_full_validations",
        "concurrent_run_inventory_validations",
        "github_api_gets_upper_bound",
        "github_api_gets_exact",
        "github_cli_version",
        "github_cli_sha256",
        "effect_admission_deadline_seconds",
        "stage_outer_timeout_seconds",
        "generation_hash",
        "installed_at",
        "secret_values_observed",
    }
    unsigned_bindings = _recovery_v2_unsigned_signed_artifact(
        bindings_document,
        expected_fields=binding_fields,
    )
    expected_secret_names = [
        "CHRONOS_AUTHORITY_DATABASE_URL",
        "CHRONOS_RUNTIME_DATABASE_URL",
        "CHRONOS_READER_DATABASE_URL",
        "CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
    ]
    preflight_attestation = singleton_attestations["PRODUCTION_PREFLIGHT_V2"]
    preflight_document = singleton_documents["PRODUCTION_PREFLIGHT_V2"]
    if (
        unsigned_bindings.get("schema_version") != "chronos-runtime-bindings-v2"
        or unsigned_bindings.get("verdict") != "FOUR_RUNTIME_BINDINGS_INSTALLED_V2"
        or unsigned_bindings.get("repository") != EXPECTED_REPOSITORY
        or unsigned_bindings.get("environment") != EXPECTED_ENVIRONMENT
        or unsigned_bindings.get("main_sha") != runtime_main_sha
        or unsigned_bindings.get("preflight_run_id") != preflight_attestation["run_id"]
        or unsigned_bindings.get("preflight_hash") != preflight_document.get("preflight_hash")
        or unsigned_bindings.get("preflight_controller_receipt_sha256")
        != hashlib.sha256(controller_payloads["PRODUCTION_PREFLIGHT_V2"]).hexdigest()
        or not _exact_integer_fields(
            unsigned_bindings,
            {
                "secret_writes_attempted",
                "secret_writes_confirmed",
                "secret_value_readbacks",
                "automatic_retries",
                "global_hold_full_validations",
                "concurrent_run_inventory_validations",
                "github_api_gets_upper_bound",
                "effect_admission_deadline_seconds",
                "stage_outer_timeout_seconds",
            },
        )
        or unsigned_bindings.get("secret_writes_attempted") != 4
        or unsigned_bindings.get("secret_writes_confirmed") != 4
        or unsigned_bindings.get("secret_names_in_order") != expected_secret_names
        or unsigned_bindings.get("secret_value_readbacks") != 0
        or unsigned_bindings.get("automatic_retries") != 0
        or unsigned_bindings.get("global_hold_full_validations") != 2
        or unsigned_bindings.get("concurrent_run_inventory_validations") != 4
        or unsigned_bindings.get("github_api_gets_upper_bound") != 55
        or unsigned_bindings.get("github_api_gets_exact") is not False
        or unsigned_bindings.get("github_cli_version") != "2.96.0"
        or unsigned_bindings.get("github_cli_sha256")
        != "cd79f16203f1fbe56937c4c96e2b6eadd10549418dcb241d91576ac77af0ac8b"
        or unsigned_bindings.get("effect_admission_deadline_seconds") != 480
        or unsigned_bindings.get("stage_outer_timeout_seconds") != 600
        or not isinstance(unsigned_bindings.get("generation_hash"), str)
        or _HEX_64.fullmatch(cast(str, unsigned_bindings["generation_hash"])) is None
        or unsigned_bindings.get("secret_values_observed") is not False
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    try:
        _authority_timestamp(unsigned_bindings.get("installed_at"), field="terminal_bindings_at")
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None

    identity = validate_neon_branch_identity_go_v2(
        singleton_documents["RECOVERY_IDENTITY_V2"], main_sha=runtime_main_sha
    )
    identity_run_id = cast(str, singleton_attestations["RECOVERY_IDENTITY_V2"]["run_id"])
    if cast(dict[str, Any], identity["source"]).get("run_id") != identity_run_id:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    seal = validate_identity_seal_v2(
        singleton_documents["DURABLE_IDENTITY_SEAL_V2"],
        main_sha=runtime_main_sha,
        expected_identity_run_id=identity_run_id,
    )
    seal_run_id = cast(str, singleton_attestations["DURABLE_IDENTITY_SEAL_V2"]["run_id"])
    seal_identity_binding = cast(dict[str, Any], seal["identity_go"])
    attestation_fields = {
        "schema_version",
        "repository",
        "workflow_path",
        "run_id",
        "run_attempt",
        "head_sha",
        "artifact_id",
        "artifact_name",
        "payload_sha256",
        "archive_sha256",
    }
    if (
        cast(dict[str, Any], seal["source"]).get("run_id") != seal_run_id
        or seal_identity_binding.get("payload_sha256")
        != singleton_attestations["RECOVERY_IDENTITY_V2"]["payload_sha256"]
        or {field: seal_identity_binding.get(field) for field in attestation_fields}
        != {
            field: singleton_attestations["RECOVERY_IDENTITY_V2"].get(field)
            for field in attestation_fields
        }
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    try:
        from scripts.chronos_production_recovery_v2 import validate_preflight_artifact_v2

        preflight = validate_preflight_artifact_v2(
            preflight_document,
            main_sha=runtime_main_sha,
        )
    except Exception:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    preflight_run_id = cast(str, preflight_attestation["run_id"])
    if (
        preflight.get("preflight_run_id") != preflight_run_id
        or preflight.get("identity_run_id") != identity_run_id
        or preflight.get("seal_run_id") != seal_run_id
        or preflight.get("identity_seal") != seal
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    preflight_effects = preflight.get("effects")
    expected_preflight_connections = (
        4 if preflight.get("current_revision") == EXPECTED_AFTER_REVISION else 3
    )
    if (
        not isinstance(preflight_effects, dict)
        or set(preflight_effects) != _RECOVERY_V2_BOOTSTRAP_EFFECT_FIELDS
        or not _exact_integer_fields(
            preflight_effects,
            _RECOVERY_V2_BOOTSTRAP_INTEGER_FIELDS,
        )
        or preflight_effects.get("effect_counter_certainty")
        != "CONSERVATIVE_UPPER_BOUNDS"
        or preflight_effects.get("r2_gets") != 1
        or preflight_effects.get("r2_gets_exact") is not True
        or preflight_effects.get("r2_puts") != 0
        or type(preflight_effects.get("neon_gets")) is not int
        or not 1 <= cast(int, preflight_effects["neon_gets"]) <= 39
        or preflight_effects.get("neon_gets_exact") is not True
        or preflight_effects.get("neon_posts") != 1
        or preflight_effects.get("neon_posts_exact") is not True
        or preflight_effects.get("postgresql_connection_attempts")
        != expected_preflight_connections
        or preflight_effects.get("postgresql_connection_attempts_exact") is not True
        or preflight_effects.get("recovery_branch_creations_upper_bound") != 1
        or preflight_effects.get("recovery_branch_creations_exact") is not True
        or preflight_effects.get("migration_dispatches") != 0
        or preflight_effects.get("migration_dispatches_exact") is not True
        or preflight_effects.get("sql_statements_upper_bound") != 128
        or preflight_effects.get("sql_statements_exact") is not False
        or preflight_effects.get("sql_write_statements_upper_bound") != 0
        or preflight_effects.get("sql_write_statements_exact") is not True
        or preflight_effects.get("automatic_retries") != 0
        or preflight_effects.get("provider_calls") != 0
        or preflight_effects.get("purchases") != 0
        or preflight_effects.get("secret_values_observed") is not False
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")

    migration_fields = {
        "schema_version",
        "database_host",
        "database_port",
        "database_name",
        "sslmode",
        "channel_binding",
        "authority_username",
        "runtime_username",
        "reader_username",
        "non_secret_generation_id",
        "generation_hash",
        "server_epoch",
        "revision",
        "migration_dispatches",
        "migration_outcome",
        "project_id",
        "production_branch_id",
        "recovery_branch_id",
        "main_sha",
        "workflow_sha",
        "post_merge_ci_sha",
        "preflight_run_id",
        "preflight_hash",
        "migration_run_id",
        "migration_run_attempt",
        "effects",
        "identity_seal",
        "runtime_bindings",
        "bootstrap_executor_terminal",
    }
    migration = _recovery_v2_unsigned_signed_artifact(
        singleton_documents["MIGRATE_0015"],
        expected_fields=migration_fields,
    )
    migration_effects = migration.get("effects")
    migration_run_id = cast(str, singleton_attestations["MIGRATE_0015"]["run_id"])
    migration_dispatches = migration.get("migration_dispatches")
    expected_executor_terminal = {
        "schema_version": "chronos-bootstrap-executor-terminal-v2",
        "executor_role": "chronos_bootstrap_executor_recoveryv2",
        "state": "NEUTRALIZED",
        "marker": EXECUTOR_TOMBSTONE_MARKER,
        "can_login": False,
        "inherit": False,
        "password_null": True,  # nosec B105
        "valid_until_epoch": True,
        "connection_limit": 0,
        "membership_count": 0,
        "session_count": 0,
        "effective_chronos_privilege_count": 0,
    }
    if (
        migration.get("schema_version") != "chronos-production-migrate-v2"
        or migration.get("main_sha") != runtime_main_sha
        or migration.get("workflow_sha") != runtime_main_sha
        or migration.get("post_merge_ci_sha") != runtime_main_sha
        or migration.get("revision") != EXPECTED_AFTER_REVISION
        or migration.get("preflight_run_id") != preflight_run_id
        or migration.get("preflight_hash") != preflight.get("preflight_hash")
        or migration.get("migration_run_id") != migration_run_id
        or migration.get("migration_run_attempt") != "1"
        or migration.get("generation_hash") != unsigned_bindings["generation_hash"]
        or migration.get("non_secret_generation_id")
        != cast(str, unsigned_bindings["generation_hash"])[:16]
        or migration.get("identity_seal") != seal
        or migration.get("runtime_bindings") != bindings_document
        or not isinstance(migration.get("bootstrap_executor_terminal"), dict)
        or not _exact_integer_fields(
            cast(dict[str, object], migration["bootstrap_executor_terminal"]),
            {
                "connection_limit",
                "membership_count",
                "session_count",
                "effective_chronos_privilege_count",
            },
        )
        or any(
            type(cast(dict[str, object], migration["bootstrap_executor_terminal"]).get(field))
            is not bool
            for field in {"can_login", "inherit", "password_null", "valid_until_epoch"}
        )
        or migration.get("bootstrap_executor_terminal") != expected_executor_terminal
        or type(migration_dispatches) is not int
        or migration_dispatches not in {0, 1}
        or migration.get("migration_outcome")
        != {0: "MIGRATION_RESUMED", 1: "MIGRATION_CONFIRMED"}[migration_dispatches]
        or not isinstance(migration_effects, dict)
        or set(migration_effects) != _RECOVERY_V2_BOOTSTRAP_EFFECT_FIELDS
        or not _exact_integer_fields(
            migration_effects,
            _RECOVERY_V2_BOOTSTRAP_INTEGER_FIELDS,
        )
        or migration_effects.get("effect_counter_certainty") != "CONSERVATIVE_UPPER_BOUNDS"
        or migration_effects.get("neon_gets_exact") is not True
        or type(migration_effects.get("neon_gets")) is not int
        or not 1 <= cast(int, migration_effects.get("neon_gets", 0)) <= 26
        or migration_effects.get("neon_posts") != 0
        or migration_effects.get("neon_posts_exact") is not True
        or migration_effects.get("r2_gets") != 0
        or migration_effects.get("r2_gets_exact") is not True
        or migration_effects.get("r2_puts") != 0
        or migration_effects.get("postgresql_connection_attempts")
        != {0: 5, 1: 10}[migration_dispatches]
        or migration_effects.get("postgresql_connection_attempts_exact")
        is not (migration_dispatches == 0)
        or migration_effects.get("recovery_branch_creations_upper_bound") != 0
        or migration_effects.get("recovery_branch_creations_exact") is not True
        or migration_effects.get("migration_dispatches") != migration_dispatches
        or migration_effects.get("migration_dispatches_exact") is not True
        or migration_effects.get("sql_statements_upper_bound") != 2_048
        or migration_effects.get("sql_statements_exact") is not False
        or migration_effects.get("sql_write_statements_upper_bound") != 1_024
        or migration_effects.get("sql_write_statements_exact") is not False
        or migration_effects.get("automatic_retries") != 0
        or migration_effects.get("provider_calls") != 0
        or migration_effects.get("purchases") != 0
        or migration_effects.get("secret_values_observed") is not False
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    try:
        _validate_migration_target(migration)
    except Exception:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None

    verify_fields = {
        "schema_version",
        "verdict",
        "revision",
        "identities",
        "business_data_modified",
        "forbidden_membership",
        "migrator_runtime_membership",
        "runtime_effective_bootstrap_edge",
        "provider_calls",
        "r2_operations",
        "main_sha",
        "workflow_sha",
        "post_merge_ci_sha",
        "generation_hash",
        "preflight_run_id",
        "preflight_hash",
        "migration_run_id",
        "migration_run_attempt",
        "verify_run_id",
        "verify_run_attempt",
        "migration_output_signature_algorithm",
        "effects",
        "identity_seal",
        "runtime_bindings",
        "production_database_revision_verified",
        "chronos_opportunity_claim_active",
        "torrent_recovery_v2_contract_active",
        "runtime_bindings_present",
    }
    verify_document = singleton_documents["VERIFY_0015"]
    verify = _recovery_v2_unsigned_signed_artifact(
        verify_document,
        expected_fields=verify_fields,
    )
    verify_effects = verify.get("effects")
    verify_run_id = cast(str, singleton_attestations["VERIFY_0015"]["run_id"])
    release_chain = live_semantics["release_chain"]
    if (
        verify.get("schema_version") != "chronos-production-verify-v2"
        or verify.get("verdict") != "VERIFY_0015_COMPLETE_V2"
        or verify.get("revision") != EXPECTED_AFTER_REVISION
        or verify.get("main_sha") != runtime_main_sha
        or verify.get("workflow_sha") != runtime_main_sha
        or verify.get("post_merge_ci_sha") != runtime_main_sha
        or verify.get("generation_hash") != unsigned_bindings["generation_hash"]
        or verify.get("preflight_run_id") != preflight_run_id
        or verify.get("preflight_hash") != preflight.get("preflight_hash")
        or verify.get("migration_run_id") != migration_run_id
        or verify.get("migration_run_attempt") != "1"
        or verify.get("verify_run_id") != verify_run_id
        or verify.get("verify_run_attempt") != "1"
        or verify.get("migration_output_signature_algorithm") != "HMAC-SHA256"
        or verify.get("identity_seal") != seal
        or verify.get("runtime_bindings") != bindings_document
        or verify.get("production_database_revision_verified") is not True
        or verify.get("chronos_opportunity_claim_active") is not True
        or verify.get("torrent_recovery_v2_contract_active") is not True
        or type(verify.get("runtime_bindings_present")) is not int
        or verify.get("runtime_bindings_present") != 4
        or verify.get("business_data_modified") is not False
        or not _exact_integer_fields(
            verify,
            {
                "forbidden_membership",
                "migrator_runtime_membership",
                "runtime_effective_bootstrap_edge",
                "provider_calls",
                "r2_operations",
            },
        )
        or any(
            verify.get(field) != 0
            for field in (
                "forbidden_membership",
                "migrator_runtime_membership",
                "runtime_effective_bootstrap_edge",
                "provider_calls",
                "r2_operations",
            )
        )
        or not isinstance(verify_effects, dict)
        or set(verify_effects) != _RECOVERY_V2_BOOTSTRAP_EFFECT_FIELDS
        or not _exact_integer_fields(
            verify_effects,
            _RECOVERY_V2_BOOTSTRAP_INTEGER_FIELDS,
        )
        or verify_effects.get("effect_counter_certainty")
        != "CONSERVATIVE_UPPER_BOUNDS"
        or verify_effects.get("r2_gets") != 0
        or verify_effects.get("r2_gets_exact") is not True
        or verify_effects.get("r2_puts") != 0
        or verify_effects.get("neon_gets") != 0
        or verify_effects.get("neon_gets_exact") is not True
        or verify_effects.get("neon_posts") != 0
        or verify_effects.get("neon_posts_exact") is not True
        or verify_effects.get("postgresql_connection_attempts") != 4
        or verify_effects.get("postgresql_connection_attempts_exact") is not True
        or verify_effects.get("recovery_branch_creations_upper_bound") != 0
        or verify_effects.get("recovery_branch_creations_exact") is not True
        or verify_effects.get("migration_dispatches") != 0
        or verify_effects.get("migration_dispatches_exact") is not True
        or verify_effects.get("sql_statements_upper_bound") != 128
        or verify_effects.get("sql_statements_exact") is not False
        or verify_effects.get("sql_write_statements_upper_bound") != 0
        or verify_effects.get("sql_write_statements_exact") is not True
        or verify_effects.get("automatic_retries") != 0
        or verify_effects.get("provider_calls") != 0
        or verify_effects.get("purchases") != 0
        or verify_effects.get("secret_values_observed") is not False
        or live_semantics["embedded_runtime_bindings"] != bindings_document
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    try:
        _validate_verify_identities(verify.get("identities"))
    except Exception:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    verify_identities = cast(dict[str, dict[str, object]], verify["identities"])
    authority_identity = verify_identities["authority"]
    expected_release_chain = {
        "receipt_sha256": singleton_attestations["VERIFY_0015"]["payload_sha256"],
        "schema_version": verify["schema_version"],
        "verdict": verify["verdict"],
        "revision": verify["revision"],
        "main_sha": verify["main_sha"],
        "post_merge_ci_sha": verify["post_merge_ci_sha"],
        "generation_hash": verify["generation_hash"],
        "preflight_run_id": verify["preflight_run_id"],
        "preflight_hash": verify["preflight_hash"],
        "migration_run_id": verify["migration_run_id"],
        "verify_run_id": verify["verify_run_id"],
        "verify_run_attempt": 1,
        "signature_algorithm": "HMAC-SHA256",
        "database_target": {
            "host": authority_identity["database_host"],
            "port": authority_identity["database_port"],
            "database": authority_identity["database_name"],
            "sslmode": authority_identity["sslmode"],
            "channel_binding": authority_identity["channel_binding"],
            "server_epoch": authority_identity["server_epoch"],
        },
        "identity_seal": seal,
        "runtime_bindings": bindings_document,
        "torrent_recovery_v2_contract_active": True,
    }
    if release_chain != expected_release_chain:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")

    expected_prior_runs = {
        "RECOVERY_IDENTITY_V2": [],
        "DURABLE_IDENTITY_SEAL_V2": [],
        "PRODUCTION_PREFLIGHT_V2": [],
        "MIGRATE_0015": [int(preflight_run_id)],
        "VERIFY_0015": [int(preflight_run_id), int(migration_run_id)],
        "LIVE_ONCE": [],
    }
    successor_pairs = {
        "RECOVERY_IDENTITY_V2": "DURABLE_IDENTITY_SEAL_V2",
        "DURABLE_IDENTITY_SEAL_V2": "PRODUCTION_PREFLIGHT_V2",
        "PRODUCTION_PREFLIGHT_V2": "MIGRATE_0015",
        "MIGRATE_0015": "VERIFY_0015",
        "VERIFY_0015": "LIVE_ONCE",
    }
    stage_attestations: dict[str, Mapping[str, object]] = {
        **singleton_attestations,
        "LIVE_ONCE": live_attestation,
    }
    live_run_id = int(cast(str, live_attestation["run_id"]))
    live_artifact_id = cast(int, live_attestation["artifact_id"])
    if live_run_id in evidence_run_ids or live_artifact_id in evidence_artifact_ids:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    evidence_run_ids.add(live_run_id)
    evidence_artifact_ids.add(live_artifact_id)
    common_proof_fields = {
        "stage_inputs",
        "predecessor_kind",
        "predecessor_attestation",
        "predecessor_semantic_verdict",
        "predecessor_controller_receipt_sha256",
        "expected_prior_run_ids",
        "authority_window_not_before",
        "expected_prior_dispatches",
        "observed_prior_dispatches",
        "observed_prior_run_ids",
        "post_merge_ci_run_id",
        "global_hold_full_validations",
        "live_postmerge_holds",
        "live_postmerge_hold_sha256",
        "current_main_sha",
    }
    input_fields = {
        "RECOVERY_IDENTITY_V2": {"expected_main_sha"},
        "DURABLE_IDENTITY_SEAL_V2": {"expected_main_sha", "identity_run_id"},
        "PRODUCTION_PREFLIGHT_V2": {
            "mode",
            "expected_main_sha",
            "post_merge_ci_sha",
            "identity_run_id",
            "seal_run_id",
        },
        "MIGRATE_0015": {
            "mode",
            "expected_main_sha",
            "post_merge_ci_sha",
            "preflight_run_id",
            "runtime_bindings_receipt_b64",
        },
        "VERIFY_0015": {
            "mode",
            "expected_main_sha",
            "post_merge_ci_sha",
            "migration_run_id",
        },
        "LIVE_ONCE": {
            "expected_main_sha",
            "expected_workflow_sha256",
            "expected_mission_manifest_sha256",
            "expected_generation_hash",
            "post_merge_ci_sha",
            "identity_run_id",
            "verify_run_id",
        },
    }
    dispatch_binding_fields = {
        "recovery_v2_effect_deadline_epoch",
        "recovery_v2_dispatch_nonce",
    }
    live_workflow_payload = _recovery_v2_evidence_bytes(
        root / ".github" / "workflows" / "data-torrent-live-v2.yml",
        repository_root=root,
        maximum_bytes=2 * 1024 * 1024,
    )
    ci_workflow_payload = _recovery_v2_evidence_bytes(
        root / ".github" / "workflows" / "ci-safe-v2.yml",
        repository_root=root,
        maximum_bytes=2 * 1024 * 1024,
    )
    live_identity = live_semantics["run_identity"]
    post_merge_proof = live_semantics["post_merge_ci_proof"]
    if (
        live_identity.get("github_run_id") != live_run_id
        or live_identity.get("github_run_attempt") != 1
        or live_identity.get("github_sha") != runtime_main_sha
        or live_identity.get("github_workflow_sha") != runtime_main_sha
        or live_identity.get("code_revision") != runtime_main_sha
        or live_identity.get("post_merge_ci_sha") != runtime_main_sha
        or live_identity.get("workflow_path")
        != ".github/workflows/data-torrent-live-v2.yml"
        or live_identity.get("workflow_file_sha256")
        != hashlib.sha256(live_workflow_payload).hexdigest()
        or set(post_merge_proof)
        != {
            "receipt_sha256",
            "workflow_path",
            "workflow_file_sha256",
            "run_id",
            "run_attempt",
            "head_sha",
            "head_branch",
            "event",
            "status",
            "conclusion",
            "cross_run_test_contract",
        }
        or not isinstance(post_merge_proof.get("receipt_sha256"), str)
        or _HEX_64.fullmatch(cast(str, post_merge_proof["receipt_sha256"])) is None
        or post_merge_proof.get("workflow_path") != ".github/workflows/ci-safe-v2.yml"
        or post_merge_proof.get("workflow_file_sha256")
        != hashlib.sha256(ci_workflow_payload).hexdigest()
        or type(post_merge_proof.get("run_id")) is not int
        or cast(int, post_merge_proof["run_id"]) <= 0
        or type(post_merge_proof.get("run_attempt")) is not int
        or post_merge_proof.get("run_attempt") != 1
        or post_merge_proof.get("head_sha") != runtime_main_sha
        or post_merge_proof.get("head_branch") != "main"
        or post_merge_proof.get("event") != "push"
        or post_merge_proof.get("status") != "completed"
        or post_merge_proof.get("conclusion") != "success"
        or post_merge_proof.get("cross_run_test_contract")
        != (
            "tests/data_torrent/test_postgresql_v1.py::"
            "test_cross_run_claim_has_one_winner_and_loser_has_zero_permits"
        )
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    expected_inputs = {
        "RECOVERY_IDENTITY_V2": {"expected_main_sha": runtime_main_sha},
        "DURABLE_IDENTITY_SEAL_V2": {
            "expected_main_sha": runtime_main_sha,
            "identity_run_id": identity_run_id,
        },
        "PRODUCTION_PREFLIGHT_V2": {
            "mode": "PREFLIGHT",
            "expected_main_sha": runtime_main_sha,
            "post_merge_ci_sha": runtime_main_sha,
            "identity_run_id": identity_run_id,
            "seal_run_id": seal_run_id,
        },
        "MIGRATE_0015": {
            "mode": "MIGRATE",
            "expected_main_sha": runtime_main_sha,
            "post_merge_ci_sha": runtime_main_sha,
            "preflight_run_id": preflight_run_id,
            "runtime_bindings_receipt_b64": base64.b64encode(bindings_payload).decode("ascii"),
        },
        "VERIFY_0015": {
            "mode": "VERIFY",
            "expected_main_sha": runtime_main_sha,
            "post_merge_ci_sha": runtime_main_sha,
            "migration_run_id": migration_run_id,
        },
        "LIVE_ONCE": {
            "expected_main_sha": runtime_main_sha,
            "expected_workflow_sha256": hashlib.sha256(live_workflow_payload).hexdigest(),
            "expected_mission_manifest_sha256": DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256,
            "expected_generation_hash": unsigned_bindings["generation_hash"],
            "post_merge_ci_sha": runtime_main_sha,
            "identity_run_id": identity_run_id,
            "verify_run_id": verify_run_id,
        },
    }
    predecessor_contract = {
        "RECOVERY_IDENTITY_V2": (
            "LIVE_GITHUB_POSTMERGE_HOLD_V2",
            "LIVE_GITHUB_HOLD_REPROVED_BY_CONTROLLER",
        ),
        "DURABLE_IDENTITY_SEAL_V2": ("IDENTITY", "NEON_BRANCH_IDENTITY_GO_V2"),
        "PRODUCTION_PREFLIGHT_V2": ("IDENTITY_SEAL", "DURABLE_IDENTITY_SEAL_V2"),
        "MIGRATE_0015": ("PREFLIGHT", "CHRONOS_MIGRATION_READY"),
        "VERIFY_0015": ("MIGRATION", "MIGRATE_0015_COMPLETE_V2"),
        "LIVE_ONCE": ("VERIFY", "VERIFY_0015_COMPLETE_V2"),
    }
    controller_postmerge_run_ids: set[int] = set()
    for stage, controller in controller_documents.items():
        proof = controller.get("pre_effect_proof")
        controller_attestation = stage_attestations[stage]
        terminal_evidence = controller.get("terminal_evidence")
        terminalization_reservation = controller.get("terminalization_effect_reservation")
        stage_inputs = proof.get("stage_inputs") if isinstance(proof, dict) else None
        try:
            expected_terminalization_reservation = (
                _recovery_v2_terminalization_effect_reservation(
                    stage=stage,
                    workflow_run_id=int(cast(str, controller_attestation["run_id"])),
                    stage_inputs=(
                        cast(dict[str, object], stage_inputs)
                        if isinstance(stage_inputs, dict)
                        else {}
                    ),
                )
            )
            terminal_run = (
                terminal_evidence.get("terminal_run")
                if isinstance(terminal_evidence, dict)
                else None
            )
            terminal_updated_at = _authority_timestamp(
                terminal_run.get("updated_at") if isinstance(terminal_run, dict) else None,
                field="controller_terminal_updated_at",
            )
            terminalization_completed_at = _authority_timestamp(
                controller.get("terminalization_completed_at"),
                field="controller_terminalization_completed_at",
            )
            terminal_deadline = datetime.fromtimestamp(
                cast(
                    int,
                    expected_terminalization_reservation[
                        "controller_terminalization_deadline_epoch"
                    ],
                ),
                tz=UTC,
            )
            if not (
                _authority_timestamp(
                    DATA_TORRENT_RECOVERY_V2_NOT_BEFORE,
                    field="recovery_v2_not_before",
                )
                <= terminal_updated_at
                <= terminalization_completed_at
                <= terminal_deadline
            ):
                raise ValueError
        except (ChronosProductionError, KeyError, TypeError, ValueError):
            raise ValueError from None
        if (
            set(controller)
            != {
                "schema_version",
                "verdict",
                "stage",
                "main_sha",
                "inputs_sha256",
                "automatic_retries",
                "mutations_attempted",
                "mutations_confirmed",
                "pre_effect_proof",
                "pre_effect_proof_sha256",
                "workflow_path",
                "workflow_run_id",
                "terminalization_effect_reservation",
                "terminalization_completed_at",
                "terminal_evidence",
            }
            or controller.get("schema_version")
            != "data-torrent-recovery-v2-controller-cycle-v1"
            or controller.get("verdict") != "TERMINAL_SUCCESS_CONFIRMED"
            or controller.get("stage") != stage
            or controller.get("main_sha") != runtime_main_sha
            or type(controller.get("automatic_retries")) is not int
            or controller.get("automatic_retries") != 0
            or controller.get("mutations_attempted") != ["ENABLE", "DISPATCH", "DISABLE"]
            or controller.get("mutations_confirmed") != ["ENABLE", "DISPATCH", "DISABLE"]
            or controller.get("workflow_path")
            != _RECOVERY_V2_TERMINAL_WORKFLOW_STAGES[stage][0]
            or type(controller.get("workflow_run_id")) is not int
            or controller.get("workflow_run_id")
            != int(cast(str, controller_attestation["run_id"]))
            or not isinstance(terminalization_reservation, dict)
            or not _exact_integer_fields(
                terminalization_reservation,
                {
                    "workflow_run_id",
                    "workflow_effect_deadline_epoch",
                    "post_effect_workflow_terminal_grace_seconds",
                    "controller_terminalization_deadline_epoch",
                    "terminal_artifact_attestation_reserve_seconds",
                    "workflow_run_observations_conservatively_consumed",
                    "artifact_attestation_gets_conservatively_consumed",
                    "artifact_downloads_conservatively_consumed",
                    "automatic_retries",
                },
            )
            or terminalization_reservation.get("second_terminalization_invocation_allowed")
            is not False
            or terminalization_reservation != expected_terminalization_reservation
            or not isinstance(terminal_evidence, dict)
            or not isinstance(proof, dict)
            or set(proof)
            != common_proof_fields
            | ({"quarantine_journal_provenance"} if stage == "RECOVERY_IDENTITY_V2" else set())
            or controller.get("pre_effect_proof_sha256")
            != hashlib.sha256(canonical_json_bytes(proof)).hexdigest()
            or controller.get("inputs_sha256")
            != hashlib.sha256(
                canonical_json_bytes(cast(dict[str, Any], proof.get("stage_inputs")))
            ).hexdigest()
            or proof.get("authority_window_not_before") != DATA_TORRENT_RECOVERY_V2_NOT_BEFORE
            or proof.get("expected_prior_dispatches") != len(expected_prior_runs[stage])
            or proof.get("observed_prior_dispatches") != len(expected_prior_runs[stage])
            or proof.get("expected_prior_run_ids") != expected_prior_runs[stage]
            or proof.get("observed_prior_run_ids") != expected_prior_runs[stage]
            or proof.get("global_hold_full_validations") != 2
            or proof.get("current_main_sha") != runtime_main_sha
            or not isinstance(proof.get("stage_inputs"), dict)
            or set(cast(dict[str, object], proof["stage_inputs"]))
            != input_fields[stage] | dispatch_binding_fields
            or {
                key: cast(dict[str, object], proof["stage_inputs"]).get(key)
                for key in input_fields[stage]
            }
            != expected_inputs[stage]
            or not isinstance(
                cast(dict[str, object], proof["stage_inputs"]).get(
                    "recovery_v2_dispatch_nonce"
                ),
                str,
            )
            or _HEX_64.fullmatch(
                cast(
                    str,
                    cast(dict[str, object], proof["stage_inputs"])[
                        "recovery_v2_dispatch_nonce"
                    ],
                )
            )
            is None
            or proof.get("predecessor_kind") != predecessor_contract[stage][0]
            or proof.get("predecessor_semantic_verdict") != predecessor_contract[stage][1]
            or not isinstance(proof.get("live_postmerge_holds"), list)
            or len(cast(list[object], proof["live_postmerge_holds"])) != 2
            or cast(list[object], proof["live_postmerge_holds"])[0]
            != cast(list[object], proof["live_postmerge_holds"])[1]
            or proof.get("live_postmerge_hold_sha256")
            != hashlib.sha256(
                canonical_json_bytes(
                    cast(
                        dict[str, Any],
                        cast(list[object], proof["live_postmerge_holds"])[0],
                    )
                )
            ).hexdigest()
        ):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        terminal_run = cast(dict[str, Any], terminal_evidence).get("terminal_run")
        expected_terminal_fields = {
            "outcome",
            "terminal_run",
            "run_observations",
            "attestation",
            "semantic_verdict",
        } | ({"semantic_projection_sha256"} if stage == "LIVE_ONCE" else set())
        if (
            set(cast(dict[str, Any], terminal_evidence)) != expected_terminal_fields
            or cast(dict[str, Any], terminal_evidence).get("outcome") != "SUCCESS"
            or type(cast(dict[str, Any], terminal_evidence).get("run_observations"))
            is not int
            or not 1
            <= cast(int, cast(dict[str, Any], terminal_evidence)["run_observations"])
            <= 3
            or cast(dict[str, Any], terminal_evidence).get("attestation")
            != controller_attestation
            or cast(dict[str, Any], terminal_evidence).get("semantic_verdict")
            != _RECOVERY_V2_TERMINAL_WORKFLOW_STAGES[stage][1]
            or not isinstance(terminal_run, dict)
            or set(terminal_run)
            != {
                "run_id",
                "run_attempt",
                "workflow_path",
                "head_sha",
                "head_branch",
                "event",
                "status",
                "conclusion",
                "updated_at",
            }
            or type(terminal_run.get("run_id")) is not int
            or terminal_run.get("run_id")
            != int(cast(str, controller_attestation["run_id"]))
            or type(terminal_run.get("run_attempt")) is not int
            or terminal_run.get("run_attempt") != 1
            or terminal_run.get("workflow_path")
            != _RECOVERY_V2_TERMINAL_WORKFLOW_STAGES[stage][0]
            or terminal_run.get("head_sha") != runtime_main_sha
            or terminal_run.get("head_branch") != "main"
            or terminal_run.get("event") != "workflow_dispatch"
            or terminal_run.get("status") != "completed"
            or terminal_run.get("conclusion") != "success"
            or not isinstance(terminal_run.get("updated_at"), str)
            or (
                stage == "LIVE_ONCE"
                and cast(dict[str, Any], terminal_evidence).get(
                    "semantic_projection_sha256"
                )
                != hashlib.sha256(
                    canonical_json_bytes(cast(dict[str, Any], live_semantics))
                ).hexdigest()
            )
        ):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        try:
            _authority_timestamp(
                terminal_run["updated_at"], field="controller_terminal_updated_at"
            )
        except ChronosProductionError:
            raise ChronosProductionError(
                "CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID"
            ) from None
        _recovery_v2_terminal_hold(
            cast(list[Mapping[str, object]], proof["live_postmerge_holds"])[0],
            runtime_main_sha=runtime_main_sha,
        )
        hold_post_merge = cast(
            dict[str, Any],
            cast(list[Mapping[str, object]], proof["live_postmerge_holds"])[0][
                "post_merge_ci"
            ],
        )
        if proof.get("post_merge_ci_run_id") != hold_post_merge.get("run_id"):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        controller_postmerge_run_ids.add(cast(int, hold_post_merge["run_id"]))
        if stage == "RECOVERY_IDENTITY_V2":
            if (
                proof.get("predecessor_attestation") is not None
                or proof.get("predecessor_controller_receipt_sha256") is not None
                or not _json_exact_equal(
                    proof.get("quarantine_journal_provenance"),
                    {
                        "path": ".torrent/release/recovery-v2-postmerge-quarantine.json",
                        "sha256": quarantine_sha256,
                        "authoritative": False,
                    },
                )
            ):
                raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        else:
            predecessor_stage = next(
                predecessor
                for predecessor, successor in successor_pairs.items()
                if successor == stage
            )
            if proof.get("predecessor_controller_receipt_sha256") != hashlib.sha256(
                controller_payloads[predecessor_stage]
            ).hexdigest():
                raise ChronosProductionError(
                    "CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID"
                )
    if (
        controller_postmerge_run_ids != {cast(int, post_merge_proof["run_id"])}
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    live_controller_proof = cast(
        dict[str, Any], controller_documents["LIVE_ONCE"]["pre_effect_proof"]
    )
    live_holds = cast(list[Mapping[str, object]], live_controller_proof["live_postmerge_holds"])
    live_runtime_hold = dict(live_holds[0])
    live_runtime_hold["current_run_excluded"] = int(
        cast(str, stage_attestations["LIVE_ONCE"]["run_id"])
    )
    expected_live_hold_receipt_sha256 = hashlib.sha256(
        (
            json.dumps(
                live_runtime_hold,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    ).hexdigest()
    if post_merge_proof.get("receipt_sha256") != expected_live_hold_receipt_sha256:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    for predecessor, successor in successor_pairs.items():
        successor_proof = cast(
            dict[str, Any], controller_documents[successor]["pre_effect_proof"]
        )
        if successor_proof.get("predecessor_attestation") != stage_attestations[predecessor]:
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")

    identity_effects = cast(dict[str, Any], identity["effects"])
    seal_effects = cast(dict[str, Any], seal["effects"])
    preflight_effects = cast(dict[str, Any], preflight_effects)
    derived_effects: dict[str, dict[str, int]] = {}
    for stage in _RECOVERY_V2_CONTROLLER_ORDER:
        derived_effects[stage] = _recovery_v2_empty_stage_effects()
    derived_effects["RECOVERY_IDENTITY_V2"]["neon_gets"] = cast(
        int, identity_effects["neon_gets"]
    )
    derived_effects["DURABLE_IDENTITY_SEAL_V2"].update(
        r2_puts=cast(int, seal_effects["r2_puts"]),
        r2_gets=cast(int, seal_effects["r2_gets"]),
        r2_objects=cast(int, seal_effects["r2_objects_created"]),
    )
    derived_effects["PRODUCTION_PREFLIGHT_V2"].update(
        neon_gets=cast(int, preflight_effects["neon_gets"]),
        neon_posts=cast(int, preflight_effects["neon_posts"]),
        r2_gets=cast(int, preflight_effects["r2_gets"]),
        postgresql_connection_attempts_upper_bound=cast(
            int, preflight_effects["postgresql_connection_attempts"]
        ),
        postgresql_sql_statements_upper_bound=cast(
            int, preflight_effects["sql_statements_upper_bound"]
        ),
    )
    derived_effects["MIGRATE_0015"].update(
        neon_gets=cast(int, migration_effects["neon_gets"]),
        postgresql_connection_attempts_upper_bound=cast(
            int, migration_effects["postgresql_connection_attempts"]
        ),
        postgresql_sql_statements_upper_bound=cast(
            int, migration_effects["sql_statements_upper_bound"]
        ),
        postgresql_sql_write_statements_upper_bound=cast(
            int, migration_effects["sql_write_statements_upper_bound"]
        ),
        postgresql_migrations=cast(int, migration_effects["migration_dispatches"]),
    )
    derived_effects["VERIFY_0015"].update(
        postgresql_connection_attempts_upper_bound=cast(
            int, verify_effects["postgresql_connection_attempts"]
        ),
        postgresql_sql_statements_upper_bound=cast(
            int, verify_effects["sql_statements_upper_bound"]
        ),
    )
    derived_effects["LIVE_ONCE"] = live_semantics["live_effects"]

    stage_proofs: dict[str, Any] = {}
    for stage in _RECOVERY_V2_CONTROLLER_ORDER:
        stage_attestation = stage_attestations[stage]
        if stage == "LIVE_ONCE":
            payload = live_artifact_payloads["torrent-real-batch-manifest-v1.json"]
        else:
            payload = singleton_payloads[stage]
        stage_proofs[stage] = {
            "run_id": int(cast(str, stage_attestation["run_id"])),
            "run_attempt": 1,
            "workflow_path": _RECOVERY_V2_TERMINAL_WORKFLOW_STAGES[stage][0],
            "head_sha": runtime_main_sha,
            "artifact_id": stage_attestation["artifact_id"],
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "payload_filename": _RECOVERY_V2_TERMINAL_WORKFLOW_STAGES[stage][2],
            "archive_sha256": stage_attestation["archive_sha256"],
            "semantic_verdict": _RECOVERY_V2_TERMINAL_WORKFLOW_STAGES[stage][1],
            "effect_counters": derived_effects[stage],
        }
    binding_effects = _recovery_v2_empty_stage_effects()
    binding_effects["secret_writes"] = 4
    migration_attestation = singleton_attestations["MIGRATE_0015"]
    stage_proofs["FOUR_RUNTIME_BINDINGS"] = {
        "run_id": int(migration_run_id),
        "run_attempt": 1,
        "workflow_path": _RECOVERY_V2_TERMINAL_WORKFLOW_STAGES["MIGRATE_0015"][0],
        "head_sha": runtime_main_sha,
        "artifact_id": migration_attestation["artifact_id"],
        "payload_sha256": hashlib.sha256(bindings_payload).hexdigest(),
        "payload_filename": "chronos-runtime-bindings-v2.json",
        "archive_sha256": migration_attestation["archive_sha256"],
        "semantic_verdict": "FOUR_RUNTIME_BINDINGS_INSTALLED_V2",
        "effect_counters": binding_effects,
        "artifact_relation": "EXACT_RECEIPT_BOUND_BY_MIGRATE_CONTROLLER_INPUT_AND_SIGNED_OBJECT",
        "carrier_payload_sha256": migration_attestation["payload_sha256"],
        "runtime_bindings_receipt_path": DATA_TORRENT_RECOVERY_V2_BINDINGS_EVIDENCE_PATH,
        "runtime_bindings_receipt_sha256": hashlib.sha256(bindings_payload).hexdigest(),
        "secret_writes": 4,  # nosec B105
    }
    replay_effects = live_semantics["replay_effects"]
    replay = live_semantics["replay"]
    replay_payload = live_artifact_payloads["torrent-load-replay-report-v1.json"]
    stage_proofs["REPLAY_100"] = {
        "run_id": int(cast(str, live_attestation["run_id"])),
        "run_attempt": 1,
        "workflow_path": _RECOVERY_V2_TERMINAL_WORKFLOW_STAGES["LIVE_ONCE"][0],
        "head_sha": runtime_main_sha,
        "artifact_id": live_attestation["artifact_id"],
        "payload_sha256": hashlib.sha256(replay_payload).hexdigest(),
        "payload_filename": "torrent-load-replay-report-v1.json",
        "archive_sha256": live_attestation["archive_sha256"],
        "semantic_verdict": "REPLAY_100_COMPLETE",
        "effect_counters": replay_effects,
        "parent_stage": "LIVE_ONCE",
        **replay,
    }
    return {
        "runtime_stages": stage_proofs,
        "production_state": {
            **live_semantics["production_state"],
            "chronos_opportunity_claim_active": True,
        },
        "payload_sha256": sorted(evidence_payload_hashes),
        "archive_sha256": sorted(evidence_archive_hashes),
        "run_ids": sorted(evidence_run_ids),
        "artifact_ids": sorted(evidence_artifact_ids),
        "provider_neutralization": {
            "receipt_path": DATA_TORRENT_RECOVERY_V2_PROVIDER_EVIDENCE_PATH,
            "receipt_sha256": provider_sha256,
            "verdict": "LEGACY_PROVIDER_BRANCH_NEUTRALIZED",
            "required_current_sha": DATA_TORRENT_RECOVERY_V2_START_SHA,
            "target_main_sha": runtime_main_sha,
            "push_mode": "ORDINARY_NON_FORCE_FAST_FORWARD",
            "push_attempts": 1,
            "remote_ref_observations": 2,
            "non_fast_forward_updates": 0,
            "branch_deletes": 0,
            "automatic_retries": 0,
        },
        "postmerge_quarantine": {
            "receipt_path": DATA_TORRENT_RECOVERY_V2_QUARANTINE_EVIDENCE_PATH,
            "receipt_sha256": quarantine_sha256,
            "verdict": "POSTMERGE_QUARANTINE_CONFIRMED",
            "automatic_retries": 0,
            "workflows_dormant": True,
            "global_queue_empty": True,
        },
    }


def _recovery_v2_terminal_intents(
    root: Path,
    *,
    runtime_main_sha: str,
    live_run_id: str,
) -> tuple[bytes, dict[str, Any], bytes, dict[str, Any], list[int]]:
    terminal_payload, terminal = _recovery_v2_strict_json(
        root / DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH,
        maximum_bytes=262_144,
        repository_root=root,
    )
    delivery_payload, delivery = _recovery_v2_strict_json(
        root / DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_PATH,
        maximum_bytes=262_144,
        repository_root=root,
    )
    engineering_numbers = delivery.get("engineering_pull_request_numbers")
    engineering_count = len(engineering_numbers) if isinstance(engineering_numbers, list) else 0
    delivery_gets = 2 * engineering_count + 3
    common = {
        "verdict": "RESERVED_NOT_ATTEMPTED",
        "repository": EXPECTED_REPOSITORY,
        "runtime_main_sha": runtime_main_sha,
        "reservation_parent_sha": runtime_main_sha,
        "pr_c_branch": "codex/data-torrent-recovery-v2",
        "automatic_retries": 0,
    }
    expected_terminal: dict[str, object] = {
        **common,
        "schema_version": "data-torrent-recovery-v2-terminal-evidence-reservation-v1",
        "live_run_id": live_run_id,
        "terminal_evidence_dir": DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR,
        "github_gets_upper_bound": {
            "runtime_close_live_bundle": 0,
            "runtime_close_hold": 12,
            "runtime_close_main_ref": 1,
            "pr_c_c1_status_observations": 30,
            "pr_c_c2_status_observations": 30,
            "postmerge_run_observation": 19,
            "postmerge_final_gate": 34,
            "total": 126,
        },
        "artifact_downloads_upper_bound": {
            "runtime_close_live_bundle": 0,
            "postmerge_final_gate": 1,
            "total": 1,
        },
        "git_remote_ref_observations_upper_bound": 1,
        "pr_c_safe_v2_cycles": {
            "reservation_before_pr": 0,
            "phase_one_expected_hold": 1,
            "candidate_exact_head": 1,
            "postmerge": 1,
            "total": 3,
            "reruns": 0,
        },
        "pr_c_pull_request_writes_upper_bound": {
            "create": 1,
            "ready_for_review": 0,
            "total": 1,
        },
        "shared_pr_c_git_effects_upper_bound": {
            "commits": 3,
            "non_force_pushes": 3,
            "force_pushes": 0,
        },
    }
    expected_delivery: dict[str, object] = {
        **common,
        "schema_version": "data-torrent-recovery-v2-delivery-observation-reservation-v1",
        "engineering_pull_request_numbers": engineering_numbers,
        "github_gets_upper_bound": {
            "engineering_pull_requests": engineering_count,
            "safe_v2_run_inventory": 1,
            "safe_v2_exact_head_jobs": engineering_count,
            "terminal_phase_one_jobs": 1,
            "terminal_open_pr_inventory": 1,
            "total": delivery_gets,
        },
        "artifact_downloads_upper_bound": {"total": 0},
        "git_remote_ref_observations_upper_bound": 1,
        "shared_pr_c_git_effects_accounted_by": "TERMINAL_INTENT",
        "terminal_read_budget_accounted_by": "TERMINAL_INTENT",
    }
    intent_set_sha256 = hashlib.sha256(
        canonical_json_bytes(
            {"delivery": expected_delivery, "terminal": expected_terminal}
        )
    ).hexdigest()
    expected_terminal["intent_set_sha256"] = intent_set_sha256
    expected_delivery["intent_set_sha256"] = intent_set_sha256
    if (
        not isinstance(engineering_numbers, list)
        or len(engineering_numbers) not in {1, 2}
        or any(type(number) is not int or number <= 0 for number in engineering_numbers)
        or len(set(cast(list[int], engineering_numbers))) != len(engineering_numbers)
        or not _json_exact_equal(terminal, expected_terminal)
        or not _json_exact_equal(delivery, expected_delivery)
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    return (
        terminal_payload,
        terminal,
        delivery_payload,
        delivery,
        cast(list[int], engineering_numbers),
    )


def _recovery_v2_terminal_quiescence(
    root: Path,
    *,
    runtime_main_sha: str,
    live_attestation_payload: bytes,
    live_attestation: Mapping[str, object],
) -> tuple[bytes, dict[str, Any]]:
    payload, receipt = _recovery_v2_strict_json(
        root / DATA_TORRENT_RECOVERY_V2_FINAL_QUIESCENCE_PATH,
        maximum_bytes=262_144,
        repository_root=root,
    )
    live_binding = receipt.get("live_bundle_attestation")
    hold = receipt.get("full_hold")
    worktree = receipt.get("worktree")
    reservation_binding = receipt.get("reservation")
    if not isinstance(reservation_binding, dict):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    reservation_commit_sha = reservation_binding.get("reservation_commit_sha")
    reservation_payload, reservation = _recovery_v2_strict_json(
        root / DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_EVIDENCE_PATH,
        maximum_bytes=262_144,
        repository_root=root,
    )
    (
        authority_reservation_payload,
        authority_reservation,
        _authority_delivery_payload,
        _authority_delivery,
        _engineering_numbers,
    ) = _recovery_v2_terminal_intents(
        root,
        runtime_main_sha=runtime_main_sha,
        live_run_id=str(live_attestation["run_id"]),
    )
    ephemeral_payloads: dict[str, bytes] = {}
    cache_slugs = {
        "RECOVERY_IDENTITY_V2": "recovery-identity-v2",
        "DURABLE_IDENTITY_SEAL_V2": "durable-identity-seal-v2",
        "PRODUCTION_PREFLIGHT_V2": "production-preflight-v2",
        "MIGRATE_0015": "migrate-0015",
        "VERIFY_0015": "verify-0015",
    }
    for stage, paths in DATA_TORRENT_RECOVERY_V2_STAGE_EVIDENCE_PATHS.items():
        controller_path = (
            f".torrent/release/recovery-v2-controller-"
            f"{stage.casefold().replace('_', '-')}.json"
        )
        ephemeral_payloads[controller_path] = _recovery_v2_evidence_bytes(
            root / paths["controller"],
            repository_root=root,
            maximum_bytes=2 * 1024 * 1024,
        )
        if stage == "LIVE_ONCE":
            continue
        attestation_payload, attestation = _recovery_v2_strict_json(
            root / paths["attestation"],
            maximum_bytes=262_144,
            repository_root=root,
        )
        artifact_payload = _recovery_v2_evidence_bytes(
            root / paths["payload"],
            repository_root=root,
            maximum_bytes=10 * 1024 * 1024,
        )
        if attestation_payload != json.dumps(
            attestation, ensure_ascii=False, sort_keys=True
        ).encode("utf-8") + b"\n":
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        cache = {
            "schema_version": "data-torrent-recovery-v2-singleton-cache-v1",
            "kind": {
                "RECOVERY_IDENTITY_V2": "IDENTITY",
                "DURABLE_IDENTITY_SEAL_V2": "IDENTITY_SEAL",
                "PRODUCTION_PREFLIGHT_V2": "PREFLIGHT",
                "MIGRATE_0015": "MIGRATION",
                "VERIFY_0015": "VERIFY",
            }[stage],
            "artifact_filename": Path(paths["payload"]).name,
            "payload_base64": base64.b64encode(artifact_payload).decode("ascii"),
            "attestation": attestation,
        }
        ephemeral_payloads[
            f".torrent/release/recovery-v2-predecessor-cache/{cache_slugs[stage]}.json"
        ] = json.dumps(cache, sort_keys=True).encode("utf-8") + b"\n"
    for ephemeral, durable in {
        ".torrent/release/chronos-runtime-bindings-v2.json": (
            DATA_TORRENT_RECOVERY_V2_BINDINGS_EVIDENCE_PATH
        ),
        ".torrent/release/recovery-v2-provider-neutralization.json": (
            DATA_TORRENT_RECOVERY_V2_PROVIDER_EVIDENCE_PATH
        ),
        ".torrent/release/recovery-v2-postmerge-quarantine.json": (
            DATA_TORRENT_RECOVERY_V2_QUARANTINE_EVIDENCE_PATH
        ),
    }.items():
        ephemeral_payloads[ephemeral] = _recovery_v2_evidence_bytes(
            root / durable,
            repository_root=root,
            maximum_bytes=10 * 1024 * 1024,
        )
    live_artifact_rows = []
    for filename in _RECOVERY_V2_TERMINAL_ARTIFACT_NAMES:
        artifact_payload = _recovery_v2_evidence_bytes(
            root / DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR / "artifacts" / filename,
            repository_root=root,
            maximum_bytes=10 * 1024 * 1024,
        )
        live_artifact_rows.append(
            {
                "filename": filename,
                "payload_base64": base64.b64encode(artifact_payload).decode("ascii"),
            }
        )
    live_cache = {
        "schema_version": "data-torrent-recovery-v2-live-bundle-cache-v1",
        "main_sha": runtime_main_sha,
        "run_id": cast(str, live_attestation["run_id"]),
        "attestation": dict(live_attestation),
        "artifacts": live_artifact_rows,
    }
    ephemeral_payloads[".torrent/release/recovery-v2-live-bundle-cache.json"] = (
        json.dumps(live_cache, sort_keys=True).encode("utf-8") + b"\n"
    )
    expected_untracked = [
        {"path": ephemeral, "raw_sha256": hashlib.sha256(ephemeral_payload).hexdigest()}
        for ephemeral, ephemeral_payload in sorted(ephemeral_payloads.items())
    ]
    if (
        set(receipt)
        != {
            "schema_version",
            "repository",
            "runtime_main_sha",
            "observed_at",
            "observed_after_live_run_id",
            "live_bundle_attestation",
            "main_ref_sha",
            "full_hold",
            "full_hold_sha256",
            "quiescence_scope",
            "production_workflows_quiescent_at_runtime_close",
            "global_queue_empty_at_runtime_close",
            "worktree",
            "reservation",
            "reservation_git_effects_exact",
            "observed_before_terminal_output_materialization",
            "github_gets_exact",
            "artifact_downloads_exact",
            "git_remote_ref_observations_exact",
            "remote_gets_exact_total",
            "automatic_retries",
        }
        or receipt.get("schema_version")
        != "data-torrent-recovery-v2-terminal-quiescence-v1"
        or receipt.get("repository") != EXPECTED_REPOSITORY
        or receipt.get("runtime_main_sha") != runtime_main_sha
        or not _json_exact_equal(
            receipt.get("observed_after_live_run_id"),
            int(cast(str, live_attestation["run_id"])),
        )
        or not isinstance(live_binding, dict)
        or not _json_exact_equal(
            live_binding,
            {
                "path": DATA_TORRENT_RECOVERY_V2_LIVE_BUNDLE_ATTESTATION_PATH,
                "raw_sha256": hashlib.sha256(live_attestation_payload).hexdigest(),
                "run_id": int(cast(str, live_attestation["run_id"])),
                "artifact_id": live_attestation["artifact_id"],
                "archive_sha256": live_attestation["archive_sha256"],
            },
        )
        or receipt.get("main_ref_sha") != runtime_main_sha
        or not isinstance(hold, dict)
        or receipt.get("full_hold_sha256")
        != hashlib.sha256(
            json.dumps(
                hold,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        or receipt.get("quiescence_scope") != "RUNTIME_CLOSE_BEFORE_PR_C"
        or receipt.get("production_workflows_quiescent_at_runtime_close") is not True
        or receipt.get("global_queue_empty_at_runtime_close") is not True
        or not isinstance(worktree, dict)
        or not _json_exact_equal(
            worktree,
            {
                "head_sha": reservation_commit_sha,
                "tracked_status": "CLEAN",
                "tracked_status_porcelain_sha256": hashlib.sha256(b"").hexdigest(),
                "nonignored_untracked_allowlist": expected_untracked,
                "unexpected_nonignored_untracked_paths": [],
                "ephemeral_release_root": ".torrent/release",
                "ephemeral_release_paths_exact": True,
            },
        )
        or not _json_exact_equal(
            reservation_binding,
            {
                "source_path": DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH,
                "durable_path": DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_EVIDENCE_PATH,
                "raw_sha256": hashlib.sha256(reservation_payload).hexdigest(),
                "reservation_commit_sha": reservation_commit_sha,
                "remote_branch_verified_before_github_reads": True,
            },
        )
        or not isinstance(reservation_commit_sha, str)
        or _HEX_40.fullmatch(reservation_commit_sha) is None
        or reservation_payload != authority_reservation_payload
        or reservation != authority_reservation
        or not _json_exact_equal(
            receipt.get("reservation_git_effects_exact"),
            {"commits": 1, "non_force_pushes": 1, "force_pushes": 0},
        )
        or receipt.get("observed_before_terminal_output_materialization") is not True
        or not _json_exact_equal(
            receipt.get("github_gets_exact"),
            {"live_bundle": 0, "final_hold": 12, "main_ref": 1, "total": 13},
        )
        or not _json_exact_equal(
            receipt.get("artifact_downloads_exact"), {"live_bundle": 0, "total": 0}
        )
        or not _json_exact_equal(receipt.get("git_remote_ref_observations_exact"), 1)
        or not _json_exact_equal(receipt.get("remote_gets_exact_total"), 14)
        or not _json_exact_equal(receipt.get("automatic_retries"), 0)
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    _recovery_v2_terminal_hold(hold, runtime_main_sha=runtime_main_sha)
    try:
        _authority_timestamp(receipt.get("observed_at"), field="terminal_quiescence_observed_at")
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    return payload, receipt


def validate_data_torrent_recovery_v2_terminal_runtime_evidence(
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Validate the committed phase-one runtime evidence without GitHub reads."""

    root = repository_root
    _preliminary_payload, preliminary = _recovery_v2_strict_json(
        root / DATA_TORRENT_RECOVERY_V2_FINAL_QUIESCENCE_PATH,
        maximum_bytes=2 * 1024 * 1024,
        repository_root=root,
    )
    runtime_main_sha = preliminary.get("runtime_main_sha")
    if not isinstance(runtime_main_sha, str) or _HEX_40.fullmatch(runtime_main_sha) is None:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    live_attestation_payload, live_attestation, live_artifact_payloads = (
        _recovery_v2_terminal_live_bundle(root, runtime_main_sha=runtime_main_sha)
    )
    live_semantics = _recovery_v2_terminal_live_semantics(
        live_artifact_payloads,
        repository_root=root,
    )
    stage_evidence = _recovery_v2_terminal_stage_evidence(
        root,
        runtime_main_sha=runtime_main_sha,
        live_attestation=live_attestation,
        live_artifact_payloads=live_artifact_payloads,
        live_semantics=live_semantics,
    )
    quiescence_payload, quiescence = _recovery_v2_terminal_quiescence(
        root,
        runtime_main_sha=runtime_main_sha,
        live_attestation_payload=live_attestation_payload,
        live_attestation=live_attestation,
    )
    return {
        "runtime_main_sha": runtime_main_sha,
        "live_attestation_payload": live_attestation_payload,
        "live_attestation": live_attestation,
        "live_artifact_payloads": live_artifact_payloads,
        "live_semantics": live_semantics,
        "stage_evidence": stage_evidence,
        "quiescence_payload": quiescence_payload,
        "quiescence": quiescence,
    }


def _recovery_v2_terminal_delivery(
    root: Path,
    *,
    runtime_main_sha: str,
) -> tuple[bytes, bytes, dict[str, Any]]:
    """Validate the bounded GitHub delivery observation and derive its report projection."""

    reservation_payload, reservation = _recovery_v2_strict_json(
        root / DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_EVIDENCE_PATH,
        maximum_bytes=262_144,
        repository_root=root,
    )
    receipt_payload, receipt = _recovery_v2_strict_json(
        root / DATA_TORRENT_RECOVERY_V2_DELIVERY_EVIDENCE_PATH,
        maximum_bytes=512 * 1024,
        repository_root=root,
    )
    terminal_intent_payload, terminal_intent = _recovery_v2_strict_json(
        root / DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH,
        maximum_bytes=262_144,
        repository_root=root,
    )
    live_run_id = terminal_intent.get("live_run_id")
    if not isinstance(live_run_id, str):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    (
        validated_terminal_intent_payload,
        _validated_terminal_intent,
        authority_reservation_payload,
        authority_reservation,
        validated_engineering_numbers,
    ) = _recovery_v2_terminal_intents(
        root,
        runtime_main_sha=runtime_main_sha,
        live_run_id=live_run_id,
    )
    engineering_numbers = reservation.get("engineering_pull_request_numbers")
    engineering_count = len(engineering_numbers) if isinstance(engineering_numbers, list) else 0
    expected_gets = 2 * engineering_count + 3
    expected_get_counters = {
        "engineering_pull_requests": engineering_count,
        "safe_v2_run_inventory": 1,
        "safe_v2_exact_head_jobs": engineering_count,
        "terminal_phase_one_jobs": 1,
        "terminal_open_pr_inventory": 1,
        "total": expected_gets,
    }
    if (
        terminal_intent_payload != validated_terminal_intent_payload
        or reservation_payload != authority_reservation_payload
        or reservation != authority_reservation
        or engineering_numbers != validated_engineering_numbers
        or not isinstance(engineering_numbers, list)
        or len(engineering_numbers) not in {1, 2}
        or any(type(number) is not int or number <= 0 for number in engineering_numbers)
        or len(set(cast(list[int], engineering_numbers))) != len(engineering_numbers)
        or not _json_exact_equal(
            reservation.get("github_gets_upper_bound"), expected_get_counters
        )
        or not _json_exact_equal(reservation.get("automatic_retries"), 0)
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    engineering = receipt.get("engineering_pull_requests")
    safe_cycles = receipt.get("safe_v2_cycles")
    terminal_pr = receipt.get("terminal_pull_request")
    terminal_phase_one = receipt.get("terminal_phase_one_expected_hold")
    observer_evidence = receipt.get("pr_c_observer_evidence")
    reservation_binding = receipt.get("reservation")
    if not isinstance(reservation_binding, dict):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    reservation_commit_sha = reservation_binding.get("reservation_commit_sha")
    if (
        set(receipt)
        != {
            "schema_version",
            "verdict",
            "repository",
            "runtime_main_sha",
            "observed_at",
            "engineering_pull_requests",
            "active_engineering_role",
            "safe_v2_cycles",
            "terminal_pull_request",
            "terminal_phase_one_expected_hold",
            "pr_c_observer_evidence",
            "reservation",
            "phase_one_git_effects_exact",
            "github_gets_exact",
            "git_remote_ref_observations_exact",
            "remote_gets_exact_total",
            "automatic_retries",
        }
        or receipt.get("schema_version") != "data-torrent-recovery-v2-delivery-receipt-v1"
        or receipt.get("verdict")
        != "ENGINEERING_DELIVERY_AND_TERMINAL_PR_OPEN_CONFIRMED"
        or receipt.get("repository") != EXPECTED_REPOSITORY
        or receipt.get("runtime_main_sha") != runtime_main_sha
        or not _json_exact_equal(receipt.get("github_gets_exact"), expected_get_counters)
        or not _json_exact_equal(receipt.get("git_remote_ref_observations_exact"), 1)
        or not _json_exact_equal(receipt.get("remote_gets_exact_total"), expected_gets + 1)
        or not _json_exact_equal(receipt.get("automatic_retries"), 0)
        or not _json_exact_equal(
            receipt.get("phase_one_git_effects_exact"),
            {"commits": 1, "non_force_pushes": 1, "force_pushes": 0},
        )
        or not _json_exact_equal(
            reservation_binding,
            {
                "source_path": DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_PATH,
                "durable_path": DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_EVIDENCE_PATH,
                "raw_sha256": hashlib.sha256(reservation_payload).hexdigest(),
                "reservation_commit_sha": reservation_commit_sha,
                "remote_branch_verified_before_github_reads": True,
            },
        )
        or not isinstance(
            reservation_commit_sha,
            str,
        )
        or _HEX_40.fullmatch(
            reservation_commit_sha
        )
        is None
        or not isinstance(engineering, list)
        or len(engineering) != len(cast(list[object], engineering_numbers))
        or any(not isinstance(item, dict) for item in engineering)
        or not isinstance(safe_cycles, dict)
        or not isinstance(terminal_pr, dict)
        or not isinstance(terminal_phase_one, dict)
        or not isinstance(observer_evidence, dict)
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    try:
        observed_at = _authority_timestamp(receipt.get("observed_at"), field="delivery_observed_at")
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    expected_roles = ["PR_A", *( ["PR_B"] if len(cast(list[object], engineering_numbers)) == 2 else [])]
    engineering_rows = cast(list[dict[str, Any]], engineering)
    merge_times: list[datetime] = []
    previous_merge_sha = DATA_TORRENT_RECOVERY_V2_START_SHA
    projected: dict[str, object] = {}
    head_shas: set[str] = set()
    merge_shas: set[str] = set()
    for index, (role, number, row) in enumerate(
        zip(expected_roles, cast(list[int], engineering_numbers), engineering_rows, strict=True)
    ):
        if (
            set(row)
            != {
                "role",
                "number",
                "head_ref",
                "head_sha",
                "base_ref",
                "merged_at",
                "state",
                "merge_commit_sha",
                "merge_method",
                "first_parent_sha",
                "second_parent_sha",
                "merge_commit_subject",
                "merge_commit_body",
            }
            or row.get("role") != role
            or row.get("number") != number
            or row.get("head_ref") != "codex/data-torrent-recovery-v2"
            or row.get("base_ref") != "main"
            or row.get("state") != "MERGED"
            or row.get("merge_method") != "MERGE_COMMIT"
            or row.get("first_parent_sha") != previous_merge_sha
            or row.get("second_parent_sha") != row.get("head_sha")
            or row.get("merge_commit_subject") != f"[DATA_TORRENT_RECOVERY_V2] PR-{'A' if index == 0 else 'B'}"
            or row.get("merge_commit_body") != ""
            or any(
                not isinstance(row.get(field), str)
                or _HEX_40.fullmatch(cast(str, row[field])) is None
                for field in ("head_sha", "merge_commit_sha", "first_parent_sha", "second_parent_sha")
            )
            or cast(str, row["head_sha"]) in head_shas
            or cast(str, row["merge_commit_sha"]) in merge_shas
        ):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        try:
            merged_at = _authority_timestamp(row.get("merged_at"), field="engineering_pr_merged_at")
        except ChronosProductionError:
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
        if (merge_times and merged_at <= merge_times[-1]) or merged_at > observed_at:
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        merge_times.append(merged_at)
        head_shas.add(cast(str, row["head_sha"]))
        merge_shas.add(cast(str, row["merge_commit_sha"]))
        previous_merge_sha = cast(str, row["merge_commit_sha"])
        projected["pr_a" if role == "PR_A" else "pr_b"] = {
            "number": number,
            "head_sha": row["head_sha"],
            "merge_commit_sha": row["merge_commit_sha"],
            "state": "MERGED",
            "merge_method": "MERGE_COMMIT",
            "base_ref": "main",
        }
    if previous_merge_sha != runtime_main_sha:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    if "pr_b" not in projected:
        projected["pr_b"] = "NOT_OPENED"
    safe_cycles = cast(dict[str, Any], safe_cycles)
    cycle_rows = safe_cycles.get("by_role")
    if (
        receipt.get("active_engineering_role") != expected_roles[-1]
        or set(safe_cycles)
        != {
            "by_role",
            "engineering_cycles_observed",
            "cycles_per_engineering_pr_maximum",
            "engineering_cycles_total_maximum",
            "failed_run_reruns",
            "historical_ci_runs",
            "phase_budgets_fungible",
        }
        or not isinstance(cycle_rows, list)
        or len(cycle_rows) != engineering_count
        or any(not isinstance(row, dict) for row in cycle_rows)
        or not _json_exact_equal(safe_cycles.get("cycles_per_engineering_pr_maximum"), 3)
        or not _json_exact_equal(safe_cycles.get("engineering_cycles_total_maximum"), 6)
        or not _json_exact_equal(safe_cycles.get("failed_run_reruns"), 0)
        or not _json_exact_equal(safe_cycles.get("historical_ci_runs"), 0)
        or safe_cycles.get("phase_budgets_fungible") is not False
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    exact_heads: list[dict[str, Any]] = []
    observed_cycle_total = 0
    for role, engineering_row, value in zip(
        expected_roles,
        engineering_rows,
        cast(list[dict[str, Any]], cycle_rows),
        strict=True,
    ):
        exact_head = value.get("exact_head_safe_v2")
        run_ids = value.get("run_ids")
        cycles_observed = value.get("cycles_observed")
        if (
            set(value)
            != {
                "role",
                "pull_request_number",
                "cycles_observed",
                "run_ids",
                "exact_head_safe_v2",
            }
            or value.get("role") != role
            or value.get("pull_request_number") != engineering_row.get("number")
            or type(cycles_observed) is not int
            or not 1 <= cycles_observed <= 3
            or not isinstance(run_ids, list)
            or len(run_ids) != cycles_observed
            or run_ids != sorted(run_ids)
            or len(set(cast(list[object], run_ids))) != len(run_ids)
            or any(type(run_id) is not int or run_id <= 0 for run_id in run_ids)
            or not isinstance(exact_head, dict)
            or set(exact_head)
            != {
                "workflow_path",
                "run_id",
                "run_attempt",
                "event",
                "pull_request_number",
                "head_ref",
                "head_sha",
                "status",
                "conclusion",
                "run_completed_observed_at",
                "scope_guard_job_id",
                "scope_guard_name",
                "scope_guard_status",
                "scope_guard_conclusion",
                "scope_guard_completed_at",
            }
            or exact_head.get("workflow_path") != ".github/workflows/ci-safe-v2.yml"
            or type(exact_head.get("run_id")) is not int
            or exact_head.get("run_id") not in run_ids
            or not _json_exact_equal(exact_head.get("run_attempt"), 1)
            or exact_head.get("event") != "pull_request"
            or exact_head.get("pull_request_number") != engineering_row.get("number")
            or exact_head.get("head_ref") != engineering_row.get("head_ref")
            or exact_head.get("head_sha") != engineering_row.get("head_sha")
            or exact_head.get("status") != "completed"
            or exact_head.get("conclusion") != "success"
            or type(exact_head.get("scope_guard_job_id")) is not int
            or cast(int, exact_head["scope_guard_job_id"]) <= 0
            or exact_head.get("scope_guard_name") != "Recovery V2 — scope guard exact"
            or exact_head.get("scope_guard_status") != "completed"
            or exact_head.get("scope_guard_conclusion") != "success"
        ):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        try:
            exact_completed = _authority_timestamp(
                exact_head.get("run_completed_observed_at"),
                field="exact_head_safe_completed_at",
            )
            scope_completed = _authority_timestamp(
                exact_head.get("scope_guard_completed_at"),
                field="scope_guard_completed_at",
            )
        except ChronosProductionError:
            raise ChronosProductionError(
                "CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID"
            ) from None
        engineering_index = expected_roles.index(role)
        if exact_completed > merge_times[engineering_index] or scope_completed > exact_completed:
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        observed_cycle_total += cycles_observed
        exact_heads.append(cast(dict[str, Any], exact_head))
    if (
        not _json_exact_equal(
            safe_cycles.get("engineering_cycles_observed"), observed_cycle_total
        )
        or not 1 <= observed_cycle_total <= 6
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    exact_head = exact_heads[-1]
    expected_terminal_fields = {
        "role",
        "number",
        "head_ref",
        "observed_head_sha",
        "observed_head_parent_sha",
        "base_ref",
        "base_sha",
        "state",
        "open_prs_for_exact_head_ref",
        "created_at",
    }
    if (
        set(terminal_pr) != expected_terminal_fields
        or terminal_pr.get("role") != "PR_C"
        or type(terminal_pr.get("number")) is not int
        or cast(int, terminal_pr["number"]) <= 0
        or terminal_pr.get("number") in cast(list[int], engineering_numbers)
        or terminal_pr.get("head_ref") != "codex/data-torrent-recovery-v2"
        or not isinstance(terminal_pr.get("observed_head_sha"), str)
        or _HEX_40.fullmatch(cast(str, terminal_pr["observed_head_sha"])) is None
        or terminal_pr.get("observed_head_parent_sha")
        != reservation_commit_sha
        or terminal_pr.get("base_ref") != "main"
        or terminal_pr.get("base_sha") != runtime_main_sha
        or terminal_pr.get("state") != "OPEN"
        or not _json_exact_equal(terminal_pr.get("open_prs_for_exact_head_ref"), 1)
        or any(
            not isinstance(terminal_pr.get(field), str)
            or _HEX_40.fullmatch(cast(str, terminal_pr[field])) is None
            for field in ("observed_head_parent_sha", "base_sha")
        )
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    try:
        terminal_created = _authority_timestamp(
            terminal_pr.get("created_at"), field="terminal_pr_created_at"
        )
        _quiescence_payload, quiescence = _recovery_v2_strict_json(
            root / DATA_TORRENT_RECOVERY_V2_FINAL_QUIESCENCE_PATH,
            maximum_bytes=2 * 1024 * 1024,
            repository_root=root,
        )
        quiescence_observed = _authority_timestamp(
            quiescence.get("observed_at"), field="terminal_quiescence_observed_at"
        )
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    if not merge_times[-1] < quiescence_observed <= terminal_created <= observed_at:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    terminal_phase_one = cast(dict[str, Any], terminal_phase_one)
    observer_evidence = cast(dict[str, Any], observer_evidence)
    expected_phase_one_fields = {
        "workflow_path",
        "run_id",
        "run_attempt",
        "event",
        "pull_request_number",
        "head_ref",
        "head_sha",
        "status",
        "conclusion",
        "scope_guard_job_id",
        "scope_guard_conclusion",
        "tests_job_id",
        "tests_conclusion",
        "gate_step_conclusion",
        "run_completed_observed_at",
    }
    if (
        set(terminal_phase_one) != expected_phase_one_fields
        or terminal_phase_one.get("workflow_path") != ".github/workflows/ci-safe-v2.yml"
        or type(terminal_phase_one.get("run_id")) is not int
        or cast(int, terminal_phase_one["run_id"]) <= 0
        or not _json_exact_equal(terminal_phase_one.get("run_attempt"), 1)
        or terminal_phase_one.get("event") != "pull_request"
        or terminal_phase_one.get("pull_request_number") != terminal_pr.get("number")
        or terminal_phase_one.get("head_ref") != "codex/data-torrent-recovery-v2"
        or terminal_phase_one.get("head_sha") != terminal_pr.get("observed_head_sha")
        or terminal_phase_one.get("status") != "completed"
        or terminal_phase_one.get("conclusion") != "failure"
        or type(terminal_phase_one.get("scope_guard_job_id")) is not int
        or cast(int, terminal_phase_one["scope_guard_job_id"]) <= 0
        or terminal_phase_one.get("scope_guard_conclusion") != "success"
        or type(terminal_phase_one.get("tests_job_id")) is not int
        or cast(int, terminal_phase_one["tests_job_id"]) <= 0
        or terminal_phase_one.get("tests_job_id")
        == terminal_phase_one.get("scope_guard_job_id")
        or terminal_phase_one.get("tests_conclusion") != "failure"
        or terminal_phase_one.get("gate_step_conclusion") != "failure"
        or not _json_exact_equal(
            observer_evidence,
            {
                "phase": "C1",
                "scope": "HOST_LOCAL_OS_STATE_OUTSIDE_WORKTREE",
                "namespace": (
                    "RobinCouncilOS/dddur75__robin-stades-ng/data-torrent-recovery-v2/"
                    f"{DATA_TORRENT_RECOVERY_V2_START_SHA}/pr-c-c1-observer-result-v1.json"
                ),
                "raw_sha256": observer_evidence.get("raw_sha256"),
                "run_id": terminal_phase_one.get("run_id"),
                "authoritative": False,
            },
        )
        or not isinstance(observer_evidence.get("raw_sha256"), str)
        or _HEX_64.fullmatch(cast(str, observer_evidence["raw_sha256"])) is None
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    try:
        phase_one_completed = _authority_timestamp(
            terminal_phase_one.get("run_completed_observed_at"),
            field="terminal_phase_one_completed_at",
        )
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    if not terminal_created <= phase_one_completed <= observed_at:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    projected.update(
        {
            "pr_c": terminal_pr["number"],
            "pr_c_phase_one_head_sha": terminal_pr["observed_head_sha"],
            "pr_c_phase_one_safe_v2": terminal_phase_one,
            "pr_c_reservation_parent_sha": terminal_pr["observed_head_parent_sha"],
            "engineering_pr_merged": True,
            "exact_head_safe_v2": {
                "workflow_path": exact_head["workflow_path"],
                "run_id": exact_head["run_id"],
                "run_attempt": exact_head["run_attempt"],
                "head_sha": exact_head["head_sha"],
                "conclusion": exact_head["conclusion"],
                "scope_guard_job_id": exact_head["scope_guard_job_id"],
                "scope_guard_conclusion": exact_head["scope_guard_conclusion"],
            },
            "final_main_sha": None,
            "final_main_sha_definition": "PENDING_PR_C_MERGE_AND_POSTMERGE_SAFE",
            "evidence": {
                "path": DATA_TORRENT_RECOVERY_V2_DELIVERY_EVIDENCE_PATH,
                "raw_sha256": hashlib.sha256(receipt_payload).hexdigest(),
            },
        }
    )
    return reservation_payload, receipt_payload, projected


def _data_torrent_recovery_v2_projection(
    repository_root: Path,
    *,
    paths: tuple[str, ...],
    projection_schema: str,
    excluded_paths: list[str],
) -> dict[str, Any]:
    root = Path(os.path.abspath(repository_root))
    _recovery_v2_require_no_reparse_chain(
        root,
        repository_root=root,
        allow_missing_leaf=False,
    )
    if tuple(sorted(set(paths))) != paths:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_RELEASE_PATH_SET_INVALID")
    files: list[dict[str, str]] = []
    total_bytes = 0
    for relative in paths:
        posix = PurePosixPath(relative)
        if (
            posix.is_absolute()
            or ".." in posix.parts
            or "." in posix.parts
            or posix.as_posix() != relative
        ):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_RELEASE_PATH_SET_INVALID")
        path = root.joinpath(*posix.parts)
        payload = _recovery_v2_read_bytes(
            path,
            repository_root=root,
            maximum_bytes=16 * 1024 * 1024,
        )
        if not payload or len(payload) > 16 * 1024 * 1024:
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
        if (
            payload.startswith(b"\xef\xbb\xbf")
            or b"\x00" in payload
        ):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        lf_text = text.replace("\r\n", "\n")
        if "\r" in lf_text:
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        lf_payload = lf_text.encode("utf-8")
        total_bytes += len(lf_payload)
        if total_bytes > 64 * 1024 * 1024:
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        files.append({"path": relative, "lf_sha256": hashlib.sha256(lf_payload).hexdigest()})
    projection_payload = json.dumps(
        files,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "projection_schema": projection_schema,
        "excluded_paths": excluded_paths,
        "files": files,
        "projection_sha256": hashlib.sha256(projection_payload).hexdigest(),
    }


def data_torrent_recovery_v2_release_projection(repository_root: Path) -> dict[str, Any]:
    """Hash release bytes without the two mutually linked append-only surfaces."""

    return _data_torrent_recovery_v2_projection(
        repository_root,
        paths=tuple(
            path
            for path in DATA_TORRENT_RECOVERY_V2_RELEASE_PATHS
            if path not in DATA_TORRENT_RECOVERY_V2_RELEASE_EXCLUDED_PATHS
        ),
        projection_schema="sha256-sorted-path-utf8-lf-sha256-v1",
        excluded_paths=list(DATA_TORRENT_RECOVERY_V2_RELEASE_EXCLUDED_PATHS),
    )


def data_torrent_recovery_v2_reviewed_candidate_projection(
    repository_root: Path,
) -> dict[str, Any]:
    """Hash exactly the pre-review candidate without any review-owned artifact."""

    excluded = sorted(
        {
            "reports/council/decision-ledger.jsonl",
            "reports/evidence/evidence-graph.json",
            DATA_TORRENT_RECOVERY_V2_INITIAL_FINAL_REVIEW_PATH,
            *DATA_TORRENT_RECOVERY_V2_INITIAL_REVIEW_PATHS.values(),
            DATA_TORRENT_RECOVERY_V2_FINAL_REVIEW_PATH,
            *DATA_TORRENT_RECOVERY_V2_REVIEW_PATHS.values(),
            DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_FINAL_REVIEW_PATH,
            *DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_REVIEW_PATHS.values(),
            DATA_TORRENT_RECOVERY_V2_STATIC_CORRECTION_FINAL_REVIEW_PATH,
            *DATA_TORRENT_RECOVERY_V2_STATIC_CORRECTION_REVIEW_PATHS.values(),
            DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_FINAL_REVIEW_PATH,
            *DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_REVIEW_PATHS.values(),
            DATA_TORRENT_RECOVERY_V2_POST_202_B101_FINAL_REVIEW_PATH,
            *DATA_TORRENT_RECOVERY_V2_POST_202_B101_REVIEW_PATHS.values(),
            DATA_TORRENT_RECOVERY_V2_CYCLE_2_CORRECTION_FINAL_REVIEW_PATH,
            *DATA_TORRENT_RECOVERY_V2_CYCLE_2_CORRECTION_REVIEW_PATHS.values(),
        }
    )
    paths = tuple(path for path in DATA_TORRENT_RECOVERY_V2_RELEASE_PATHS if path not in excluded)
    return _data_torrent_recovery_v2_projection(
        repository_root,
        paths=paths,
        projection_schema="sha256-sorted-path-utf8-lf-sha256-reviewed-candidate-v1",
        excluded_paths=excluded,
    )


def data_torrent_recovery_v2_pr_b_reviewed_candidate_projection(
    repository_root: Path,
) -> dict[str, Any]:
    """Hash the conditional PR-B candidate without any review-owned artifact."""

    excluded = sorted(
        {
            "reports/council/decision-ledger.jsonl",
            "reports/evidence/evidence-graph.json",
            DATA_TORRENT_RECOVERY_V2_INITIAL_FINAL_REVIEW_PATH,
            *DATA_TORRENT_RECOVERY_V2_INITIAL_REVIEW_PATHS.values(),
            DATA_TORRENT_RECOVERY_V2_FINAL_REVIEW_PATH,
            *DATA_TORRENT_RECOVERY_V2_REVIEW_PATHS.values(),
            DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_FINAL_REVIEW_PATH,
            *DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_REVIEW_PATHS.values(),
            DATA_TORRENT_RECOVERY_V2_STATIC_CORRECTION_FINAL_REVIEW_PATH,
            *DATA_TORRENT_RECOVERY_V2_STATIC_CORRECTION_REVIEW_PATHS.values(),
            DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_FINAL_REVIEW_PATH,
            *DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_REVIEW_PATHS.values(),
            DATA_TORRENT_RECOVERY_V2_POST_202_B101_FINAL_REVIEW_PATH,
            *DATA_TORRENT_RECOVERY_V2_POST_202_B101_REVIEW_PATHS.values(),
            DATA_TORRENT_RECOVERY_V2_CYCLE_2_CORRECTION_FINAL_REVIEW_PATH,
            *DATA_TORRENT_RECOVERY_V2_CYCLE_2_CORRECTION_REVIEW_PATHS.values(),
            DATA_TORRENT_RECOVERY_V2_PR_B_FINAL_REVIEW_PATH,
            *DATA_TORRENT_RECOVERY_V2_PR_B_REVIEW_PATHS.values(),
        }
    )
    paths = tuple(path for path in DATA_TORRENT_RECOVERY_V2_RELEASE_PATHS if path not in excluded)
    return _data_torrent_recovery_v2_projection(
        repository_root,
        paths=paths,
        projection_schema="sha256-sorted-path-utf8-lf-sha256-pr-b-reviewed-candidate-v1",
        excluded_paths=excluded,
    )


def data_torrent_recovery_v2_pr_b_release_projection(
    repository_root: Path,
) -> dict[str, Any]:
    """Hash the corrected runtime plus the distinct conditional PR-B reviews."""

    paths = tuple(
        sorted(
            {
                *DATA_TORRENT_RECOVERY_V2_RELEASE_PATHS,
                *DATA_TORRENT_RECOVERY_V2_PR_B_REVIEW_PATHS.values(),
                DATA_TORRENT_RECOVERY_V2_PR_B_FINAL_REVIEW_PATH,
            }
            - set(DATA_TORRENT_RECOVERY_V2_RELEASE_EXCLUDED_PATHS)
        )
    )
    return _data_torrent_recovery_v2_projection(
        repository_root,
        paths=paths,
        projection_schema="sha256-sorted-path-utf8-lf-sha256-pr-b-release-v1",
        excluded_paths=list(DATA_TORRENT_RECOVERY_V2_RELEASE_EXCLUDED_PATHS),
    )


def _recovery_v2_raw_evidence_projection(
    root: Path,
    *,
    paths: tuple[str, ...],
) -> dict[str, object]:
    """Bind an exact evidence set without newline normalization."""

    if paths != tuple(sorted(set(paths))):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    files: list[dict[str, str]] = []
    total_bytes = 0
    for relative in paths:
        payload = _recovery_v2_evidence_bytes(
            root / relative,
            repository_root=root,
            maximum_bytes=16 * 1024 * 1024,
        )
        total_bytes += len(payload)
        if total_bytes > 64 * 1024 * 1024:
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        files.append({"path": relative, "raw_sha256": hashlib.sha256(payload).hexdigest()})
    projection_payload = json.dumps(
        files,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "projection_schema": "sha256-sorted-path-raw-sha256-v1",
        "files": files,
        "projection_sha256": hashlib.sha256(projection_payload).hexdigest(),
    }


def _validate_recovery_v2_agent_reports(
    root: Path,
    *,
    bindings: object,
    reviewed_snapshot_sha256: str,
    review_paths: Mapping[str, str] = DATA_TORRENT_RECOVERY_V2_REVIEW_PATHS,
    expected_facts: Mapping[str, list[dict[str, object]]] | None = None,
) -> None:
    if (
        not isinstance(bindings, dict)
        or set(bindings) != set(review_paths)
        or (expected_facts is not None and set(expected_facts) != set(review_paths))
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    snapshot_ref = f"REVIEWED_SNAPSHOT_SHA256:{reviewed_snapshot_sha256}"
    for agent_id, relative in review_paths.items():
        binding = bindings.get(agent_id)
        if not isinstance(binding, dict):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        payload, report = _recovery_v2_strict_json(
            root / relative,
            maximum_bytes=262_144,
            repository_root=root,
        )
        if (
            not _json_exact_equal(
                binding,
                {
                "path": relative,
                "raw_sha256": hashlib.sha256(payload).hexdigest(),
                "field_count": 15,
                "reviewed_snapshot_sha256": reviewed_snapshot_sha256,
                "recommended_action": "PASS_AND_HOLD_IMPLEMENTATION_RELEASE",
                "p0": 0,
                "p1": 0,
                "p2": 0,
                "open_threads": 0,
                },
            )
            or not _exact_integer_fields(
                binding,
                {"field_count", "p0", "p1", "p2", "open_threads"},
            )
            or set(report) != _RECOVERY_V2_AGENT_REPORT_FIELDS
            or report.get("agent_id") != agent_id
            or report.get("mission_id") != "DATA_TORRENT_RECOVERY_V2"
            or report.get("unknowns") != []
            or report.get("assumptions") != []
            or report.get("main_objection")
            != ("P0=0; P1=0; P2=0; OPEN_THREADS=0; VERDICT=PASS_AND_HOLD_IMPLEMENTATION_RELEASE")
            or report.get("risks") != []
            or report.get("recommended_action") != "PASS_AND_HOLD_IMPLEMENTATION_RELEASE"
            or report.get("scale_condition")
            != "EXACT_HEAD_SAFE_V2_GREEN_NORMAL_MERGE_POSTMERGE_SAFE_V2_GREEN"
            or any(
                not isinstance(report.get(field), str) or not cast(str, report[field]).strip()
                for field in (
                    "minimum_decisive_test",
                    "estimated_compute",
                    "estimated_external_cost",
                    "estimated_human_time",
                    "maintenance_impact",
                )
            )
            or type(report.get("confidence")) not in {int, float}
            or float(report["confidence"]) < 0.95
            or float(report["confidence"]) > 1.0
        ):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        facts = report.get("facts_verified")
        if (
            not isinstance(facts, list)
            or not facts
            or any(
                not isinstance(fact, dict)
                or set(fact) != {"claim", "evidence_refs", "status"}
                or fact.get("status") != "VERIFIED"
                or not isinstance(fact.get("claim"), str)
                or not fact["claim"]
                or not isinstance(fact.get("evidence_refs"), list)
                or not fact["evidence_refs"]
                or any(
                    not isinstance(reference, str) or not reference
                    for reference in fact["evidence_refs"]
                )
                or snapshot_ref not in fact["evidence_refs"]
                for fact in facts
            )
            or (
                expected_facts is not None
                and not _json_exact_equal(facts, expected_facts[agent_id])
            )
        ):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")


def _validate_recovery_v2_final_review(
    root: Path,
    *,
    binding: object,
    relative: str,
    reviewed_snapshot_sha256: str,
    schema_version: str,
    review_paths: Mapping[str, str],
    reviewed_file_count: int,
    reviewed_at_not_after: datetime,
    reviewed_at_not_before: datetime | None = None,
    reviewed_at_must_precede: bool = False,
    expected_external_effects: Mapping[str, int] | None = None,
    expected_delivery_effects: Mapping[str, int] | None = None,
) -> None:
    payload, report = _recovery_v2_strict_json(
        root / relative,
        maximum_bytes=262_144,
        repository_root=root,
    )
    expected_fields = {
        "schema_version",
        "mission_id",
        "reviewed_at",
        "program_start_sha",
        "reviewed_snapshot_sha256",
        "reviewed_file_count",
        "agents",
        "reviewer_reports",
        "verdict",
        "defects",
        "production_effects_observed",
        "external_effects_observed",
        "release_boundary",
        "release_conditions",
    }
    if expected_delivery_effects is not None:
        expected_fields.add("delivery_effects_observed")
    expected_external = (
        dict(expected_external_effects)
        if expected_external_effects is not None
        else {
            "git_remote_writes": 0,
            "github_writes": 0,
            "neon_gets": 0,
            "neon_mutations": 0,
            "postgresql_production_connections": 0,
            "postgresql_production_writes": 0,
            "r2_gets": 0,
            "r2_puts": 0,
            "official_reads": 0,
            "provider_requests": 0,
            "secret_writes": 0,  # nosec B105 - effect counter, not a credential.
        }
    )
    try:
        reviewed_at = _authority_timestamp(report.get("reviewed_at"), field="final_reviewed_at")
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    if (
        not _json_exact_equal(
            binding,
            {
            "path": relative,
            "raw_sha256": hashlib.sha256(payload).hexdigest(),
            },
        )
        or set(report) != expected_fields
        or report.get("schema_version") != schema_version
        or report.get("mission_id") != "DATA_TORRENT_RECOVERY_V2"
        or report.get("program_start_sha") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or report.get("reviewed_snapshot_sha256") != reviewed_snapshot_sha256
        or report.get("reviewed_file_count") != reviewed_file_count
        or reviewed_at > reviewed_at_not_after
        or (reviewed_at_must_precede and reviewed_at == reviewed_at_not_after)
        or (
            reviewed_at_not_before is not None
            and reviewed_at <= reviewed_at_not_before
        )
        or report.get("agents") != ["C2", "C4", "DP6", "A2"]
        or report.get("reviewer_reports") != dict(review_paths)
        or report.get("verdict") != "PASS_AND_HOLD_IMPLEMENTATION_RELEASE"
        or not isinstance(report.get("defects"), dict)
        or not _exact_integer_fields(
            cast(dict[str, object], report["defects"]),
            {"open_p0", "open_p1", "open_p2", "open_threads"},
        )
        or report.get("defects")
        != {"open_p0": 0, "open_p1": 0, "open_p2": 0, "open_threads": 0}
        or type(report.get("production_effects_observed")) is not int
        or report.get("production_effects_observed") != 0
        or not isinstance(report.get("external_effects_observed"), dict)
        or not _exact_integer_fields(
            cast(dict[str, object], report["external_effects_observed"]),
            {
                "git_remote_writes",
                "github_writes",
                "neon_gets",
                "neon_mutations",
                "postgresql_production_connections",
                "postgresql_production_writes",
                "r2_gets",
                "r2_puts",
                "official_reads",
                "provider_requests",
                "secret_writes",
            },
        )
        or not _json_exact_equal(
            report.get("external_effects_observed"),
            expected_external,
        )
        or (
            expected_delivery_effects is not None
            and (
                not isinstance(report.get("delivery_effects_observed"), dict)
                or not _exact_integer_fields(
                    cast(dict[str, object], report["delivery_effects_observed"]),
                    set(expected_delivery_effects),
                )
                or not _json_exact_equal(
                    report.get("delivery_effects_observed"),
                    dict(expected_delivery_effects),
                )
            )
        )
        or not _json_exact_equal(
            report.get("release_boundary"),
            {
            "runtime_projection_includes_all_review_reports": True,
            "runtime_projection_excludes_append_only_ledger": True,
            "runtime_projection_excludes_evidence_graph": True,
            "ledger_graph_exact_hash_equality_required_separately": True,
            },
        )
        or report.get("release_conditions")
        != [
            "EXACT_HEAD_SAFE_V2_GREEN",
            "NORMAL_MERGE_COMMIT",
            "POSTMERGE_SAFE_V2_GREEN",
            "EXACT_IMMEDIATE_PREDECESSOR_BEFORE_EACH_STAGE",
        ]
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")


def _recovery_v2_next_decision_id(previous_id: str, record_date: datetime) -> str:
    match = re.fullmatch(r"RCV3-\d{8}-(\d+)", previous_id)
    if match is None:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    return f"RCV3-{record_date:%Y%m%d}-{int(match.group(1)) + 1:03d}"


def _recovery_v2_successor_edges_are_canonical(
    all_edges: list[dict[str, object]],
    matching_edges: list[dict[str, object]],
    expected_from_claim_ids: list[str],
    *,
    require_tail: bool = False,
) -> bool:
    """Require one contiguous numeric sequence in the exact proof order."""

    if not matching_edges or len(matching_edges) != len(expected_from_claim_ids):
        return False
    positions = [
        index for index, edge in enumerate(all_edges) if any(edge is item for item in matching_edges)
    ]
    if positions != list(range(positions[0], positions[0] + len(matching_edges))):
        return False
    if require_tail and positions[-1] != len(all_edges) - 1:
        return False
    prior_numbers = [
        int(match.group(1))
        for edge in all_edges[: positions[0]]
        if isinstance(edge.get("edge_id"), str)
        and (match := re.fullmatch(r"EDGE\.([1-9][0-9]*)", cast(str, edge["edge_id"])))
        is not None
    ]
    if not prior_numbers:
        return False
    expected = [
        f"EDGE.{number}"
        for number in range(
            max(prior_numbers) + 1,
            max(prior_numbers) + 1 + len(matching_edges),
        )
    ]
    return [edge.get("edge_id") for edge in matching_edges] == expected and [
        edge.get("from_claim_id") for edge in matching_edges
    ] == expected_from_claim_ids


def _validate_recovery_v2_reservation_graph(
    root: Path,
    *,
    record: Mapping[str, object],
    release_claim: str,
    downstream_allowed: bool,
) -> None:
    _payload, graph = _recovery_v2_strict_json(
        root / "reports" / "evidence" / "evidence-graph.json",
        maximum_bytes=16 * 1024 * 1024,
        repository_root=root,
    )
    claims = graph.get("claims")
    nodes = graph.get("decision_nodes")
    edges = graph.get("edges")
    if (
        not isinstance(claims, list)
        or not isinstance(nodes, list)
        or not isinstance(edges, list)
        or any(not isinstance(row, dict) for row in (*claims, *nodes, *edges))
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    typed_claims = cast(list[dict[str, object]], claims)
    typed_nodes = cast(list[dict[str, object]], nodes)
    typed_edges = cast(list[dict[str, object]], edges)
    matching_claims = [
        row for row in typed_claims if row.get("claim_id") == _RECOVERY_V2_RESERVATION_CLAIM
    ]
    matching_nodes = [
        row for row in typed_nodes if row.get("decision_id") == record.get("decision_id")
    ]
    matching_edges = [
        row for row in typed_edges if row.get("to_decision_id") == record.get("decision_id")
    ]
    context = record.get("context")
    if not isinstance(context, dict):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    terminal_binding = context.get("terminal_intent")
    if not isinstance(terminal_binding, dict):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    release_and_reservation_edges = [
        row
        for row in typed_edges
        if row.get("to_decision_id")
        in {context.get("release_decision_id"), record.get("decision_id")}
    ]
    if (
        len(matching_claims) != 1
        or matching_claims[0]
        != {
            "claim_id": _RECOVERY_V2_RESERVATION_CLAIM,
            "claim": (
                "Recovery V2 terminal and delivery external-read intents are durably "
                "reserved; no read has been attempted"
            ),
            "scope": "DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION",
            "source": DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH,
            "grain": "ONE_RUNTIME_MAIN_TO_ONE_DUAL_INTENT_RESERVATION",
            "temporal_class": "DECISION_AS_OF",
            "artifact": DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH,
            "hash": terminal_binding.get("raw_sha256"),
            "code_revision": context.get("runtime_main_sha"),
            "execution_id": f"council-record:{record.get('decision_id')}",
            "scientific_lineage_id": "DATA_TORRENT_RECOVERY_V2",
            "dataset_lineage_id": context.get("intent_set_sha256"),
            "status": "VERIFIED",
            "verified_by": ["C0", "C2", "C4"],
            "successor_of": release_claim,
        }
        or matching_nodes
        != [
            {
                "decision_id": record.get("decision_id"),
                "ledger_record_hash": record.get("hash"),
            }
        ]
        or len(matching_edges) != 2
        or not _recovery_v2_successor_edges_are_canonical(
            typed_edges,
            matching_edges,
            [release_claim, _RECOVERY_V2_RESERVATION_CLAIM],
            require_tail=not downstream_allowed,
        )
        or not _recovery_v2_successor_edges_are_canonical(
            typed_edges,
            release_and_reservation_edges,
            [release_claim, release_claim, _RECOVERY_V2_RESERVATION_CLAIM],
            require_tail=not downstream_allowed,
        )
        or {row.get("from_claim_id") for row in matching_edges}
        != {release_claim, _RECOVERY_V2_RESERVATION_CLAIM}
        or any(
            set(row) != {"edge_id", "from_claim_id", "to_decision_id", "relation", "status"}
            or not isinstance(row.get("edge_id"), str)
            or not cast(str, row["edge_id"]).strip()
            or row.get("relation") != "SUPPORTS"
            or row.get("status") != "RECORDED"
            for row in matching_edges
        )
        or (
            not downstream_allowed
            and any(
                row.get("claim_id") in {_RECOVERY_V2_PHASE_ONE_CLAIM, _RECOVERY_V2_TERMINAL_CLAIM}
                for row in typed_claims
            )
        )
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")


def _validate_recovery_v2_reservation_record(
    record: dict[str, Any],
    *,
    root: Path,
    release_id: str,
    release_hash: str,
    release_claim: str,
    release_date: datetime,
    observed_now: datetime,
) -> tuple[datetime, str, str, list[int]]:
    terminal_payload, terminal = _recovery_v2_strict_json(
        root / DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH,
        maximum_bytes=262_144,
        repository_root=root,
    )
    runtime_main_sha = terminal.get("runtime_main_sha")
    live_run_id = terminal.get("live_run_id")
    if (
        not isinstance(runtime_main_sha, str)
        or _HEX_40.fullmatch(runtime_main_sha) is None
        or not isinstance(live_run_id, str)
        or re.fullmatch(r"[1-9][0-9]{0,17}", live_run_id) is None
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    (
        validated_terminal_payload,
        validated_terminal,
        delivery_payload,
        delivery,
        engineering_numbers,
    ) = _recovery_v2_terminal_intents(
        root,
        runtime_main_sha=runtime_main_sha,
        live_run_id=live_run_id,
    )
    if terminal_payload != validated_terminal_payload or terminal != validated_terminal:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    context = record.get("context")
    try:
        record_date = _authority_timestamp(record.get("date"), field="reservation_council_date")
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    expires_at = _authority_timestamp(
        DATA_TORRENT_RECOVERY_V2_EXPIRES_AT,
        field="recovery_v2_expiry",
    )
    terminal_hash = hashlib.sha256(terminal_payload).hexdigest()
    delivery_hash = hashlib.sha256(delivery_payload).hexdigest()
    delivery_gets = 2 * len(engineering_numbers) + 3
    expected_files = sorted(
        [
            DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH,
            DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_PATH,
            "reports/council/decision-ledger.jsonl",
            "reports/evidence/evidence-graph.json",
        ]
    )
    external_read_upper_bounds = (
        context.get("external_read_upper_bounds") if isinstance(context, dict) else None
    )
    shared_git_effect_upper_bound = (
        context.get("shared_git_effect_upper_bound") if isinstance(context, dict) else None
    )
    expected_external_read_upper_bounds = {
        "terminal_runtime_close_github_gets": 13,
        "terminal_pr_c_c1_status_observation_gets": 30,
        "terminal_pr_c_c2_status_observation_gets": 30,
        "terminal_postmerge_run_observation_gets": 19,
        "terminal_postmerge_final_gate_gets": 34,
        "terminal_github_gets_total": 126,
        "terminal_artifact_downloads": 1,
        "terminal_git_remote_ref_observations": 1,
        "delivery_github_gets": delivery_gets,
        "delivery_artifact_downloads": 0,
        "delivery_git_remote_ref_observations": 1,
        "terminal_slot_github_gets_total": 126 + delivery_gets,
        "terminal_slot_github_gets_maximum": 136,
    }
    expected_shared_git_effect_upper_bound = {
        "commits": 3,
        "non_force_pushes": 3,
        "force_pushes": 0,
    }
    if (
        record.get("decision_id") != _recovery_v2_next_decision_id(release_id, record_date)
        or record.get("record_type") != "STAGE_STARTED"
        or record.get("decision") != "PASS_AND_HOLD"
        or record.get("responsible") != "C0"
        or record.get("dissent") is not None
        or record.get("objections") != []
        or record.get("proof") != [release_claim, _RECOVERY_V2_RESERVATION_CLAIM]
        or record.get("proposal")
        != (
            "Reserve the exact Recovery V2 terminal and delivery intents before any "
            "external read."
        )
        or record.get("previous_hash") != release_hash
        or not isinstance(context, dict)
        or set(context)
        != {
            "mission_id",
            "program_start_sha",
            "release_decision_id",
            "release_record_hash",
            "active_release_claim_id",
            "manifest_hashes",
            "effect_contract_hashes",
            "scale_stage",
            "phase",
            "writer",
            "worktree",
            "branch",
            "head",
            "runtime_main_sha",
            "live_run_id",
            "engineering_pull_request_numbers",
            "pr",
            "files",
            "targeted_tests",
            "proofs_reused",
            "terminal_intent",
            "delivery_intent",
            "intent_set_sha256",
            "external_read_upper_bounds",
            "shared_git_effect_upper_bound",
            "automatic_retries",
            "data_torrent_ready",
        }
        or context.get("mission_id") != "DATA_TORRENT_RECOVERY_V2"
        or context.get("program_start_sha") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or context.get("release_decision_id") != release_id
        or context.get("release_record_hash") != release_hash
        or context.get("active_release_claim_id") != release_claim
        or context.get("manifest_hashes")
        != {
            "raw_sha256": DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256,
            "canonical_sha256": DATA_TORRENT_RECOVERY_V2_MANIFEST_CANONICAL_SHA256,
            "source_hash": DATA_TORRENT_RECOVERY_V2_OWNER_DIRECTIVE_SHA256,
        }
        or context.get("effect_contract_hashes")
        != {
            "raw_sha256": DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_SHA256,
            "canonical_sha256": DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_CANONICAL_SHA256,
        }
        or context.get("scale_stage") != "E4"
        or context.get("phase") != "TERMINAL_EVIDENCE_RESERVATION"
        or context.get("writer") != "C0"
        or context.get("worktree") != "ENGINEERING_WORKTREE:data-torrent-recovery-v2"
        or context.get("branch") != "codex/data-torrent-recovery-v2"
        or not isinstance(context.get("head"), str)
        or _HEX_40.fullmatch(cast(str, context["head"])) is None
        or context.get("head") != runtime_main_sha
        or context.get("runtime_main_sha") != runtime_main_sha
        or context.get("live_run_id") != live_run_id
        or context.get("engineering_pull_request_numbers") != engineering_numbers
        or context.get("pr") != "PR_C_PENDING"
        or context.get("files") != expected_files
        or context.get("targeted_tests")
        != {
            "dual_intent_bytes": "PASS",
            "reservation_crash_adoption": "PASS",
            "scope_guard_pr_c_c0": "PASS",
        }
        or context.get("proofs_reused")
        != [
            f"active-release-claim:{release_claim}",
            f"manifest-raw:{DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256}",
            f"manifest-canonical:{DATA_TORRENT_RECOVERY_V2_MANIFEST_CANONICAL_SHA256}",
            f"effect-contract-raw:{DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_SHA256}",
            f"effect-contract-canonical:{DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_CANONICAL_SHA256}",
        ]
        or context.get("terminal_intent")
        != {
            "path": DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH,
            "raw_sha256": terminal_hash,
        }
        or context.get("delivery_intent")
        != {
            "path": DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_PATH,
            "raw_sha256": delivery_hash,
        }
        or context.get("intent_set_sha256") != terminal.get("intent_set_sha256")
        or not isinstance(external_read_upper_bounds, dict)
        or not _exact_integer_fields(
            cast(dict[str, object], external_read_upper_bounds),
            set(expected_external_read_upper_bounds),
        )
        or not _json_exact_equal(
            external_read_upper_bounds, expected_external_read_upper_bounds
        )
        or not isinstance(shared_git_effect_upper_bound, dict)
        or not _exact_integer_fields(
            cast(dict[str, object], shared_git_effect_upper_bound),
            set(expected_shared_git_effect_upper_bound),
        )
        or not _json_exact_equal(
            shared_git_effect_upper_bound, expected_shared_git_effect_upper_bound
        )
        or type(context.get("automatic_retries")) is not int
        or context.get("automatic_retries") != 0
        or context.get("data_torrent_ready") is not False
        or record_date <= release_date
        or record_date > observed_now
        or record_date > expires_at
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    return record_date, runtime_main_sha, live_run_id, engineering_numbers


def _validate_recovery_v2_phase_one_graph(
    root: Path,
    *,
    record: Mapping[str, object],
    release_claim: str,
    terminal_allowed: bool,
) -> None:
    _payload, graph = _recovery_v2_strict_json(
        root / "reports" / "evidence" / "evidence-graph.json",
        maximum_bytes=16 * 1024 * 1024,
        repository_root=root,
    )
    claims = graph.get("claims")
    nodes = graph.get("decision_nodes")
    edges = graph.get("edges")
    if (
        not isinstance(claims, list)
        or not isinstance(nodes, list)
        or not isinstance(edges, list)
        or any(not isinstance(row, dict) for row in (*claims, *nodes, *edges))
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    matching_nodes = [
        row for row in cast(list[dict[str, object]], nodes) if row.get("decision_id") == record.get("decision_id")
    ]
    matching_edges = [
        row for row in cast(list[dict[str, object]], edges) if row.get("to_decision_id") == record.get("decision_id")
    ]
    phase_one_claims = [
        row
        for row in cast(list[dict[str, object]], claims)
        if row.get("claim_id") == _RECOVERY_V2_PHASE_ONE_CLAIM
    ]
    terminal_claims = [
        row
        for row in cast(list[dict[str, object]], claims)
        if row.get("claim_id") == _RECOVERY_V2_TERMINAL_CLAIM
    ]
    context = record.get("context")
    if not isinstance(context, dict):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    successor_edge_suffix = [
        row
        for row in cast(list[dict[str, object]], edges)
        if row.get("to_decision_id")
        in {context.get("reservation_decision_id"), record.get("decision_id")}
    ]
    runtime_close_quiescence = context.get("runtime_close_quiescence")
    phase_one_projection = context.get("phase_one_projection")
    if not isinstance(runtime_close_quiescence, dict) or not isinstance(
        phase_one_projection, dict
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    if (
        matching_nodes
        != [
            {
                "decision_id": record.get("decision_id"),
                "ledger_record_hash": record.get("hash"),
            }
        ]
        or len(phase_one_claims) != 1
        or set(phase_one_claims[0])
        != {
            "claim_id",
            "claim",
            "scope",
            "source",
            "grain",
            "temporal_class",
            "artifact",
            "hash",
            "code_revision",
            "execution_id",
            "scientific_lineage_id",
            "dataset_lineage_id",
            "status",
            "verified_by",
            "successor_of",
        }
        or phase_one_claims[0].get("claim")
        != "Recovery V2 runtime E4 and terminal evidence phase one are complete; READY remains held"
        or phase_one_claims[0].get("scope")
        != "DATA_TORRENT_RECOVERY_V2_TERMINAL_PHASE_ONE"
        or phase_one_claims[0].get("source")
        != DATA_TORRENT_RECOVERY_V2_FINAL_QUIESCENCE_PATH
        or phase_one_claims[0].get("grain")
        != "ONE_RUNTIME_MAIN_TO_ONE_PHASE_ONE_STAGE_FINISHED"
        or phase_one_claims[0].get("temporal_class") != "DECISION_AS_OF"
        or phase_one_claims[0].get("artifact")
        != DATA_TORRENT_RECOVERY_V2_FINAL_QUIESCENCE_PATH
        or phase_one_claims[0].get("hash")
        != runtime_close_quiescence.get("raw_sha256")
        or phase_one_claims[0].get("code_revision") != context.get("runtime_main_sha")
        or phase_one_claims[0].get("execution_id")
        != f"council-record:{record.get('decision_id')}"
        or phase_one_claims[0].get("scientific_lineage_id")
        != "DATA_TORRENT_RECOVERY_V2"
        or phase_one_claims[0].get("dataset_lineage_id")
        != phase_one_projection.get("projection_sha256")
        or phase_one_claims[0].get("status") != "VERIFIED"
        or phase_one_claims[0].get("verified_by")
        != ["C0", "CI_SAFE_V2", "RUNTIME_RECEIPTS"]
        or phase_one_claims[0].get("successor_of") != _RECOVERY_V2_RESERVATION_CLAIM
        or len(matching_edges) != 3
        or not _recovery_v2_successor_edges_are_canonical(
            cast(list[dict[str, object]], edges),
            matching_edges,
            [release_claim, _RECOVERY_V2_RESERVATION_CLAIM, _RECOVERY_V2_PHASE_ONE_CLAIM],
        )
        or not _recovery_v2_successor_edges_are_canonical(
            cast(list[dict[str, object]], edges),
            successor_edge_suffix,
            [
                release_claim,
                _RECOVERY_V2_RESERVATION_CLAIM,
                release_claim,
                _RECOVERY_V2_RESERVATION_CLAIM,
                _RECOVERY_V2_PHASE_ONE_CLAIM,
            ],
            require_tail=not terminal_allowed,
        )
        or {edge.get("from_claim_id") for edge in matching_edges}
        != {release_claim, _RECOVERY_V2_RESERVATION_CLAIM, _RECOVERY_V2_PHASE_ONE_CLAIM}
        or any(
            set(edge)
            != {"edge_id", "from_claim_id", "to_decision_id", "relation", "status"}
            or not isinstance(edge.get("edge_id"), str)
            or not cast(str, edge["edge_id"]).strip()
            or edge.get("relation") != "SUPPORTS"
            or edge.get("status") != "RECORDED"
            for edge in matching_edges
        )
        or (not terminal_allowed and terminal_claims)
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")


def _validate_recovery_v2_phase_one_record(
    record: dict[str, Any],
    *,
    root: Path,
    release_id: str,
    release_hash: str,
    release_claim: str,
    reservation_record: Mapping[str, object],
    reservation_date: datetime,
    observed_now: datetime,
) -> tuple[datetime, str, dict[str, object]]:
    context = record.get("context")
    try:
        record_date = _authority_timestamp(record.get("date"), field="phase_one_council_date")
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    phase_one_paths = _recovery_v2_phase_one_evidence_paths()
    projection = _recovery_v2_raw_evidence_projection(root, paths=phase_one_paths)
    runtime = validate_data_torrent_recovery_v2_terminal_runtime_evidence(repository_root=root)
    runtime_main_sha = runtime.get("runtime_main_sha")
    quiescence_payload = runtime.get("quiescence_payload")
    quiescence = runtime.get("quiescence")
    if (
        not isinstance(runtime_main_sha, str)
        or _HEX_40.fullmatch(runtime_main_sha) is None
        or not isinstance(quiescence_payload, bytes)
        or not isinstance(quiescence, dict)
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    reservation_binding = quiescence.get("reservation")
    reservation_commit_sha = (
        reservation_binding.get("reservation_commit_sha")
        if isinstance(reservation_binding, dict)
        else None
    )
    if not isinstance(reservation_commit_sha, str) or _HEX_40.fullmatch(
        reservation_commit_sha
    ) is None:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    quiescence_hash = hashlib.sha256(quiescence_payload).hexdigest()
    try:
        quiescence_observed_at = _authority_timestamp(
            quiescence.get("observed_at"), field="terminal_quiescence_observed_at"
        )
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    expires_at = _authority_timestamp(
        DATA_TORRENT_RECOVERY_V2_EXPIRES_AT,
        field="recovery_v2_expiry",
    )
    expected_files = [
        *(
            path
            for path in phase_one_paths
            if path
            not in {
                DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH,
                DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_PATH,
            }
        ),
        "reports/council/decision-ledger.jsonl",
        "reports/evidence/evidence-graph.json",
    ]
    if (
        record.get("decision_id")
        != _recovery_v2_next_decision_id(
            cast(str, reservation_record.get("decision_id")),
            record_date,
        )
        or record.get("record_type") != "STAGE_FINISHED"
        or record.get("decision") != "PASS_AND_HOLD"
        or record.get("responsible") != "C0"
        or record.get("dissent") is not None
        or record.get("objections") != []
        or record.get("proof")
        != [release_claim, _RECOVERY_V2_RESERVATION_CLAIM, _RECOVERY_V2_PHASE_ONE_CLAIM]
        or record.get("proposal")
        != (
            "Record Recovery V2 E4 runtime and phase-one evidence while readiness "
            "remains held."
        )
        or record.get("previous_hash") != reservation_record.get("hash")
        or not isinstance(context, dict)
        or set(context)
        != {
            "mission_id",
            "program_start_sha",
            "release_decision_id",
            "release_record_hash",
            "active_release_claim_id",
            "reservation_decision_id",
            "reservation_record_hash",
            "reservation_commit_sha",
            "scale_stage",
            "phase",
            "writer",
            "worktree",
            "branch",
            "head",
            "runtime_main_sha",
            "pr",
            "files",
            "targeted_tests",
            "proofs_reused",
            "phase_one_projection",
            "runtime_close_quiescence",
            "data_torrent_ready",
        }
        or context.get("mission_id") != "DATA_TORRENT_RECOVERY_V2"
        or context.get("program_start_sha") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or context.get("release_decision_id") != release_id
        or context.get("release_record_hash") != release_hash
        or context.get("active_release_claim_id") != release_claim
        or context.get("reservation_decision_id") != reservation_record.get("decision_id")
        or context.get("reservation_record_hash") != reservation_record.get("hash")
        or context.get("reservation_commit_sha") != reservation_commit_sha
        or context.get("scale_stage") != "E4"
        or context.get("phase") != "TERMINAL_EVIDENCE_PHASE_ONE"
        or context.get("writer") != "C0"
        or context.get("worktree") != "ENGINEERING_WORKTREE:data-torrent-recovery-v2"
        or context.get("branch") != "codex/data-torrent-recovery-v2"
        or context.get("head") != reservation_commit_sha
        or context.get("runtime_main_sha") != runtime_main_sha
        or context.get("pr") != "PR_C_PENDING"
        or context.get("files") != expected_files
        or context.get("targeted_tests")
        != {
            "runtime_evidence_semantics": "PASS",
            "terminal_phase_one_projection": "PASS",
            "scope_guard_pr_c_c1": "PASS",
        }
        or context.get("proofs_reused")
        != [
            f"active-release-claim:{release_claim}",
            f"reservation-claim:{_RECOVERY_V2_RESERVATION_CLAIM}",
            f"reservation-commit:{reservation_commit_sha}",
            f"runtime-close-quiescence-raw:{quiescence_hash}",
        ]
        or context.get("phase_one_projection") != projection
        or context.get("runtime_close_quiescence")
        != {
            "path": DATA_TORRENT_RECOVERY_V2_FINAL_QUIESCENCE_PATH,
            "raw_sha256": quiescence_hash,
        }
        or context.get("data_torrent_ready") is not False
        or not reservation_date < quiescence_observed_at < record_date
        or record_date > observed_now
        or record_date > expires_at
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    return record_date, runtime_main_sha, projection


def _validate_recovery_v2_frozen_projection(value: object) -> None:
    """Validate the internal hash of a historical projection without rebinding current bytes."""

    if (
        not isinstance(value, dict)
        or set(value) != {"projection_schema", "excluded_paths", "files", "projection_sha256"}
        or not isinstance(value.get("projection_schema"), str)
        or not cast(str, value["projection_schema"]).strip()
        or not isinstance(value.get("excluded_paths"), list)
        or not isinstance(value.get("files"), list)
        or not isinstance(value.get("projection_sha256"), str)
        or _HEX_64.fullmatch(cast(str, value["projection_sha256"])) is None
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    excluded = cast(list[object], value["excluded_paths"])
    files = cast(list[object], value["files"])
    if (
        any(not isinstance(path, str) or not path for path in excluded)
        or excluded != sorted(set(cast(list[str], excluded)))
        or not files
        or any(
            not isinstance(row, dict)
            or set(row) != {"path", "lf_sha256"}
            or not isinstance(row.get("path"), str)
            or not cast(str, row["path"])
            or not isinstance(row.get("lf_sha256"), str)
            or _HEX_64.fullmatch(cast(str, row["lf_sha256"])) is None
            for row in files
        )
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    typed_files = cast(list[dict[str, str]], files)
    if [row["path"] for row in typed_files] != sorted({row["path"] for row in typed_files}):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    computed = hashlib.sha256(
        json.dumps(
            typed_files,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if not hmac.compare_digest(cast(str, value["projection_sha256"]), computed):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")


def _validate_recovery_v2_local_correction_pair(
    failure: dict[str, Any],
    release: dict[str, Any],
    *,
    root: Path,
    base_release: dict[str, Any],
    base_release_date: datetime,
    observed_now: datetime,
    expected_manifest: Mapping[str, str],
    expected_effect: Mapping[str, str],
    expected_call_graph: Mapping[str, str],
) -> datetime:
    """Validate the mandatory, effect-free correction of the post-196 QA fixture."""

    try:
        failure_date = _authority_timestamp(
            failure.get("date"), field="local_qa_failure_date"
        )
        release_date = _authority_timestamp(
            release.get("date"), field="local_qa_correction_release_date"
        )
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    expires_at = _authority_timestamp(
        DATA_TORRENT_RECOVERY_V2_EXPIRES_AT,
        field="recovery_v2_expiry",
    )
    zero_effects = {
        "git_remote_writes": 0,
        "github_writes": 0,
        "neon_gets": 0,
        "neon_mutations": 0,
        "postgresql_production_connections": 0,
        "postgresql_production_writes": 0,
        "r2_gets": 0,
        "r2_puts": 0,
        "official_reads": 0,
        "provider_requests": 0,
        "secret_writes": 0,  # nosec B105 - effect counter, not a credential.
    }
    base_context = base_release.get("context")
    base_runtime_release = (
        base_context.get("runtime_release") if isinstance(base_context, dict) else None
    )
    base_runtime_files = (
        base_runtime_release.get("files")
        if isinstance(base_runtime_release, dict)
        else None
    )
    if not isinstance(base_runtime_files, list) or any(
        not isinstance(row, dict)
        or set(row) != {"path", "lf_sha256"}
        or not isinstance(row.get("path"), str)
        or not isinstance(row.get("lf_sha256"), str)
        for row in base_runtime_files
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    base_runtime_file_hashes = {
        cast(str, row["path"]): cast(str, row["lf_sha256"])
        for row in cast(list[dict[str, object]], base_runtime_files)
    }
    expected_failed_candidate_hashes = {
        "src/robin/chronos_production.py": (
            "84f4f75f5647f3600937147352d2b3da9fd52bb2725a3eabea04f6c5e9207dd7"
        ),
        "tests/council/test_data_torrent_recovery_v2_governance.py": (
            "d8de152fd92a64eec2cf92a876d4f2292fe60bc4d006a8eb7d9c20bb8b5371bb"
        ),
    }
    if any(
        base_runtime_file_hashes.get(path) != expected_hash
        for path, expected_hash in expected_failed_candidate_hashes.items()
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    failure_context = failure.get("context")
    expected_failure_files = [
        "src/robin/chronos_production.py",
        "tests/council/test_data_torrent_recovery_v2_governance.py",
    ]
    if (
        failure.get("decision_id") != DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_FAILURE_ID
        or failure.get("hash") != DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_FAILURE_HASH
        or failure.get("decision_id")
        != _recovery_v2_next_decision_id(
            cast(str, base_release.get("decision_id")), failure_date
        )
        or failure.get("record_type") != "FAILURE"
        or failure.get("decision") != "PASS_AND_HOLD"
        or failure.get("responsible") != "C0"
        or failure.get("dissent") is not None
        or failure.get("objections")
        != [
            "The 29 failures are one stale-helper fan-out, not 29 independent defects.",
            "Record 196 remains immutable and cannot be rewritten after this contradiction.",
            "PR-B is not opened because no post-merge conditional trigger exists.",
        ]
        or failure.get("proposal")
        != (
            "Record the post-196 targeted-governance contradiction, hold every external "
            "effect, and authorize only the smallest local pre-CI correction plus fresh "
            "independent review."
        )
        or failure.get("proof") != [_RECOVERY_V2_LOCAL_QA_FAILURE_CLAIM]
        or failure.get("previous_hash") != base_release.get("hash")
        or not isinstance(failure_context, dict)
        or set(failure_context)
        != {
            "mission_id",
            "phase",
            "program_start_sha",
            "release_decision_id",
            "release_record_hash",
            "active_release_claim_id",
            "writer",
            "worktree",
            "branch",
            "head",
            "files",
            "targeted_test",
            "failed_candidate_hashes",
            "root_cause",
            "fanout_failure_count",
            "successor_contract_findings",
            "correction_authority",
            "observed_external_effects",
            "external_effects_authorized_now",
            "pr_b",
            "full_suite_rerun",
            "data_torrent_ready",
        }
        or failure_context.get("mission_id") != "DATA_TORRENT_RECOVERY_V2"
        or failure_context.get("phase") != "POST_196_LOCAL_QA_FAILURE"
        or failure_context.get("program_start_sha") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or failure_context.get("release_decision_id") != base_release.get("decision_id")
        or failure_context.get("release_record_hash") != base_release.get("hash")
        or failure_context.get("active_release_claim_id") != _RECOVERY_V2_BASE_RELEASE_CLAIM
        or failure_context.get("writer") != "C0"
        or failure_context.get("worktree")
        != "ENGINEERING_WORKTREE:data-torrent-recovery-v2"
        or failure_context.get("branch") != "codex/data-torrent-recovery-v2"
        or failure_context.get("head") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or failure_context.get("files") != expected_failure_files
        or failure_context.get("targeted_test")
        != {
            "command": "pytest -q tests/council/test_data_torrent_recovery_v2_governance.py",
            "result": "29 failed, 130 passed in 20.15s",
        }
        or failure_context.get("failed_candidate_hashes")
        != expected_failed_candidate_hashes
        or failure_context.get("root_cause") != "STALE_TERMINAL_TEST_HELPER_FANOUT_29"
        or type(failure_context.get("fanout_failure_count")) is not int
        or failure_context.get("fanout_failure_count") != 29
        or failure_context.get("successor_contract_findings")
        != [
            "THREE_ORDERED_SUCCESSORS_REQUIRED",
            "SUCCESSOR_TOP_LEVEL_FIELDS_AND_RAW_CANONICALITY_NOT_ENFORCED",
            "SUCCESSOR_CHRONOLOGY_WAS_NOT_STRICT",
            "JSON_BOOLEAN_INTEGER_EQUIVALENCE_AT_NESTED_BOUNDARIES",
        ]
        or failure_context.get("correction_authority")
        != "LOCAL_PRE_CI_SMALLEST_CORRECTION_AND_FRESH_FOUR_AXIS_QA"
        or not _json_exact_equal(
            failure_context.get("observed_external_effects"), zero_effects
        )
        or not isinstance(failure_context.get("observed_external_effects"), dict)
        or not _exact_integer_fields(
            cast(dict[str, object], failure_context["observed_external_effects"]),
            set(zero_effects),
        )
        or failure_context.get("external_effects_authorized_now") is not False
        or failure_context.get("pr_b") != "NOT_OPENED"
        or failure_context.get("full_suite_rerun") is not False
        or failure_context.get("data_torrent_ready") is not False
        or failure_date <= base_release_date
        or failure_date > observed_now
        or failure_date > expires_at
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")

    context = release.get("context")
    if not isinstance(context, dict):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    reviewed_candidate = context.get("reviewed_candidate")
    runtime_release = context.get("runtime_release")
    _validate_recovery_v2_frozen_projection(reviewed_candidate)
    _validate_recovery_v2_frozen_projection(runtime_release)
    if (
        not isinstance(reviewed_candidate, dict)
        or not isinstance(runtime_release, dict)
        or reviewed_candidate.get("projection_sha256")
        != DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_REVIEWED_SNAPSHOT_SHA256
        or runtime_release.get("projection_sha256")
        != DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_RUNTIME_SHA256
        or len(cast(list[object], reviewed_candidate.get("files"))) != 135
        or len(cast(list[object], runtime_release.get("files"))) != 150
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    expected_files = sorted(
        {
            ".gitattributes",
            "configs/agents/mission-activation-matrix-v3.json",
            "docs/operations/DATA-TORRENT-RECOVERY-V2.md",
            *DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_REVIEW_PATHS.values(),
            DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_FINAL_REVIEW_PATH,
            "reports/council/decision-ledger.jsonl",
            "reports/evidence/evidence-graph.json",
            "scripts/check_data_torrent_recovery_v2_scope.py",
            "scripts/materialize_data_torrent_recovery_v2_delivery_evidence.py",
            "src/robin/chronos_production.py",
            "tests/council/test_data_torrent_recovery_v2_governance.py",
        }
    )
    if (
        release.get("decision_id") != DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_RELEASE_ID
        or release.get("hash") != DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_RELEASE_HASH
        or release.get("decision_id")
        != _recovery_v2_next_decision_id(cast(str, failure.get("decision_id")), release_date)
        or release.get("record_type") != "DECISION"
        or release.get("decision") != "PASS_AND_HOLD"
        or release.get("responsible") != "C0"
        or release.get("dissent") is not None
        or release.get("objections")
        != [
            "The full suite was not rerun; the sole full-suite result remains historical.",
            "The correction is local pre-CI work and does not consume conditional PR-B authority.",
            "Every production and external effect remains zero until its exact predecessor gate.",
        ]
        or release.get("proposal")
        != (
            "Release the freshly reviewed local correction of the post-196 QA fixture and "
            "successor guards while preserving PR-B, production, and one-shot effects."
        )
        or release.get("proof") != [_RECOVERY_V2_LOCAL_CORRECTION_RELEASE_CLAIM]
        or release.get("previous_hash") != failure.get("hash")
        or set(context)
        != {
            "mission_id",
            "phase",
            "program_start_sha",
            "writer",
            "writer_count",
            "worktree",
            "branch",
            "head",
            "pr",
            "files",
            "supersedes_release_claim_id",
            "supersedes_release_decision_id",
            "supersedes_release_record_hash",
            "failure_record_id",
            "failure_record_hash",
            "manifest",
            "effect_contract",
            "postgresql_call_graph",
            "reviewed_candidate",
            "reviewed_snapshot_sha256",
            "runtime_release",
            "defects",
            "release_conditions",
            "progression_contract",
            "observed_external_effects",
            "independent_reviews",
            "final_review",
            "targeted_tests",
            "proofs_reused",
            "external_effects_authorized_now",
            "data_torrent_ready",
        }
        or context.get("mission_id") != "DATA_TORRENT_RECOVERY_V2"
        or context.get("phase") != "LOCAL_PRE_CI_CORRECTION_RELEASE_AFTER_FRESH_QA"
        or context.get("program_start_sha") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or context.get("writer") != "C0"
        or type(context.get("writer_count")) is not int
        or context.get("writer_count") != 1
        or context.get("worktree") != "ENGINEERING_WORKTREE:data-torrent-recovery-v2"
        or context.get("branch") != "codex/data-torrent-recovery-v2"
        or context.get("head") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or context.get("pr") != "PENDING"
        or context.get("files") != expected_files
        or context.get("supersedes_release_claim_id") != _RECOVERY_V2_BASE_RELEASE_CLAIM
        or context.get("supersedes_release_decision_id") != base_release.get("decision_id")
        or context.get("supersedes_release_record_hash") != base_release.get("hash")
        or context.get("failure_record_id") != failure.get("decision_id")
        or context.get("failure_record_hash") != failure.get("hash")
        or context.get("manifest") != dict(expected_manifest)
        or context.get("effect_contract") != dict(expected_effect)
        or context.get("postgresql_call_graph") != dict(expected_call_graph)
        or context.get("reviewed_candidate") != reviewed_candidate
        or context.get("reviewed_snapshot_sha256")
        != reviewed_candidate.get("projection_sha256")
        or context.get("runtime_release") != runtime_release
        or not isinstance(context.get("defects"), dict)
        or not _exact_integer_fields(
            cast(dict[str, object], context["defects"]),
            {"open_p0", "open_p1", "open_p2", "open_threads"},
        )
        or context.get("defects")
        != {"open_p0": 0, "open_p1": 0, "open_p2": 0, "open_threads": 0}
        or not _json_exact_equal(
            context.get("release_conditions"),
            {
            "production_effects_authorized_now": False,
            "exact_head_safe_v2_required": True,
            "normal_merge_required": True,
            "postmerge_safe_v2_required": True,
            "immediate_predecessor_required_for_each_stage": True,
            },
        )
        or not _json_exact_equal(
            context.get("progression_contract"),
            {
            "council_role": "CONTROL_AND_RECORD_ONLY",
            "progression_mode": "AUTOMATIC_WITHIN_AUTHORIZED_MANIFEST",
            "controller_path": "scripts/dispatch_data_torrent_recovery_v2_stage.py",
            "stage_mapping_bound_to_effect_contract": True,
            "predecessor_attestation_and_semantic_validation_before_effect": True,
            "pr_c_phase_one_stage_finished_record_required": True,
            "pr_c_terminal_decision_record_required": True,
            },
        )
        or not _json_exact_equal(context.get("observed_external_effects"), zero_effects)
        or not isinstance(context.get("observed_external_effects"), dict)
        or not _exact_integer_fields(
            cast(dict[str, object], context["observed_external_effects"]),
            set(zero_effects),
        )
        or context.get("targeted_tests")
        != {
            "governance_release": "PASS",
            "recovery_supervision": "73 passed, 3 skipped",
            "ruff_changed_python": "PASS",
            "mypy_recovery_v2_strict": "PASS",
            "full_suite_rerun": "FALSE",
            "unapproved_network_attempts": "0",
        }
        or context.get("proofs_reused")
        != [
            f"base-release-record:{base_release.get('hash')}",
            f"local-qa-failure-record:{failure.get('hash')}",
            f"manifest-raw:{DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256}",
            f"effect-contract-raw:{DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_SHA256}",
        ]
        or context.get("external_effects_authorized_now") is not False
        or context.get("data_torrent_ready") is not False
        or release_date <= failure_date
        or release_date > observed_now
        or release_date > expires_at
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    reviewed_snapshot = cast(str, reviewed_candidate["projection_sha256"])
    _validate_recovery_v2_agent_reports(
        root,
        bindings=context.get("independent_reviews"),
        reviewed_snapshot_sha256=reviewed_snapshot,
        review_paths=DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_REVIEW_PATHS,
    )
    _validate_recovery_v2_final_review(
        root,
        binding=context.get("final_review"),
        relative=DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_FINAL_REVIEW_PATH,
        reviewed_snapshot_sha256=reviewed_snapshot,
        schema_version="data-torrent-recovery-v2-post-196-correction-final-review-v3",
        review_paths=DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_REVIEW_PATHS,
        reviewed_file_count=len(cast(list[object], reviewed_candidate["files"])),
        reviewed_at_not_after=release_date,
        reviewed_at_not_before=failure_date,
    )
    return release_date


def _validate_recovery_v2_static_correction_pair(
    failure: dict[str, Any],
    release: dict[str, Any],
    *,
    root: Path,
    base_release: dict[str, Any],
    base_release_date: datetime,
    observed_now: datetime,
    expected_manifest: Mapping[str, str],
    expected_effect: Mapping[str, str],
    expected_call_graph: Mapping[str, str],
) -> datetime:
    """Validate the distinct, effect-free SAFE V2 Bandit correction after record 198."""

    try:
        failure_date = _authority_timestamp(
            failure.get("date"), field="static_qa_failure_date"
        )
        release_date = _authority_timestamp(
            release.get("date"), field="static_qa_correction_release_date"
        )
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    expires_at = _authority_timestamp(
        DATA_TORRENT_RECOVERY_V2_EXPIRES_AT,
        field="recovery_v2_expiry",
    )
    zero_effects = {
        "git_remote_writes": 0,
        "github_writes": 0,
        "neon_gets": 0,
        "neon_mutations": 0,
        "postgresql_production_connections": 0,
        "postgresql_production_writes": 0,
        "r2_gets": 0,
        "r2_puts": 0,
        "official_reads": 0,
        "provider_requests": 0,
        "secret_writes": 0,  # nosec B105 - effect counter, not a credential.
    }
    base_context = base_release.get("context")
    base_runtime = base_context.get("runtime_release") if isinstance(base_context, dict) else None
    base_files = base_runtime.get("files") if isinstance(base_runtime, dict) else None
    if not isinstance(base_files, list) or any(
        not isinstance(row, dict)
        or set(row) != {"path", "lf_sha256"}
        or not isinstance(row.get("path"), str)
        or not isinstance(row.get("lf_sha256"), str)
        for row in base_files
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    base_hashes = {
        cast(str, row["path"]): cast(str, row["lf_sha256"])
        for row in cast(list[dict[str, object]], base_files)
    }
    failed_candidate_hashes = {
        "docs/operations/DATA-TORRENT-RECOVERY-V2.md": (
            "f8f702097e4f8844871fef7f5ced72c7e9870b609035cc394dd6afd07f187502"
        ),
        "scripts/dispatch_data_torrent_recovery_v2_stage.py": (
            "5ebd365c8435e34cf14983cb5726f333cfb11830b8af5e99f0284c3897e61955"
        ),
        "scripts/install_chronos_runtime_bindings_v2.py": (
            "db54cfa8b188d667abe0b642b499babe11efe3b345ab5515fc6880d577684b48"
        ),
        "src/robin/chronos_production.py": (
            "f9fd4d27a9697013c43f35b2e1f22f08ba9006602e6d28359b7c00bc8f3dffed"
        ),
        "tests/activation/test_chronos_runtime_bindings_v2.py": (
            "29bf60fcd8283df9334b6d8f044c38adc8503419f50ac9c03ab2c23232c7246a"
        ),
        "tests/council/test_data_torrent_recovery_v2_governance.py": (
            "b30d31dc400d0132bc47c266db6834e4f06dfd8e18d07c39809c7a2fd691f985"
        ),
    }
    if any(base_hashes.get(path) != digest for path, digest in failed_candidate_hashes.items()):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    bandit_finding_fields = [
        "expected_replay_acceptance.raw_archive_binding_pass",
        "expected_replay_acceptance.volume_pass",
        "expected_replay_acceptance.canonical_equality_pass",
        "expected_replay_acceptance.idempotence_pass",
        "expected_replay_acceptance.no_external_effect_pass",
        "bootstrap_executor_terminal.password_null",
        "stage_proofs.FOUR_RUNTIME_BINDINGS.secret_writes",
        "pr_b_release.zero_effects.secret_writes",
        "targeted_tests.secret_scan",
    ]
    runtime_findings = [
        {
            "finding_id": "R3_R4_CACHE_ENVELOPE_AND_REATTESTATION_SCHEDULE_UNSAFE",
            "severity": "P0",
            "path": "scripts/install_chronos_runtime_bindings_v2.py",
        },
        {
            "finding_id": "R3_FINAL_CONTROLLER_SUCCESS_AND_SHA_NOT_BOUND_THROUGH_R4_TO_R5",
            "severity": "P0",
            "path": "scripts/install_chronos_runtime_bindings_v2.py",
        },
        {
            "finding_id": "PROVIDER_NEUTRALIZATION_DEADLINE_1200_NOT_300",
            "severity": "P1",
            "path": "scripts/dispatch_data_torrent_recovery_v2_stage.py",
        },
        {
            "finding_id": "POSTMERGE_QUARANTINE_DEADLINE_1200_NOT_300",
            "severity": "P1",
            "path": "scripts/dispatch_data_torrent_recovery_v2_stage.py",
        },
        {
            "finding_id": "QUARANTINE_TOKEN_CHECK_AFTER_ONE_SHOT_RESERVATION",
            "severity": "P1",
            "path": "scripts/dispatch_data_torrent_recovery_v2_stage.py",
        },
        {
            "finding_id": "R4_LOCAL_PREREQUISITES_AFTER_ONE_SHOT_RESERVATION",
            "severity": "P1",
            "path": "scripts/install_chronos_runtime_bindings_v2.py",
        },
        {
            "finding_id": "R4_FULL_EFFECT_SCHEDULE_AND_EXPIRY_NOT_PRE_ADMITTED",
            "severity": "P0",
            "path": "scripts/install_chronos_runtime_bindings_v2.py",
        },
        {
            "finding_id": "PR_MERGE_HEAD_NOT_COMPARE_AND_SWAP",
            "severity": "P0",
            "path": "docs/operations/DATA-TORRENT-RECOVERY-V2.md",
        },
    ]
    expected_failure_context = {
        "mission_id": "DATA_TORRENT_RECOVERY_V2",
        "phase": "POST_198_PRECOMMIT_STATIC_QA_FAILURE",
        "program_start_sha": DATA_TORRENT_RECOVERY_V2_START_SHA,
        "release_decision_id": base_release.get("decision_id"),
        "release_record_hash": base_release.get("hash"),
        "active_release_claim_id": _RECOVERY_V2_LOCAL_CORRECTION_RELEASE_CLAIM,
        "writer": "C0",
        "worktree": "ENGINEERING_WORKTREE:data-torrent-recovery-v2",
        "branch": "codex/data-torrent-recovery-v2",
        "head": DATA_TORRENT_RECOVERY_V2_START_SHA,
        "files": sorted(failed_candidate_hashes),
        "contradictions": {
            "bandit": {
                "command": (
                    "python -m bandit -q -r src/robin/chronos_production.py and "
                    "15 Recovery V2 scripts"
                ),
                "result": "9 low-severity B105 findings; exit=1",
                "finding_count": 9,
                "finding_fields": bandit_finding_fields,
            },
            "runtime_operability": {
                "independent_review": "P0=4, P1=4",
                "finding_count": 8,
                "findings": runtime_findings,
            },
        },
        "failed_candidate_hashes": failed_candidate_hashes,
        "root_causes": [
            "AUDIT_COUNTER_FALSE_POSITIVES_MISSING_NOSEC_B105",
            "R3_R4_R5_CACHE_ATTESTATION_AND_FINAL_CONTROLLER_HANDOFF_NOT_BOUND",
            "R4_FULL_EFFECT_SCHEDULE_NOT_ADMITTED_ACROSS_ALL_DEADLINES",
            "E1_LOCAL_STAGE_DEADLINE_EXCEEDS_CONTRACT",
            "LOCAL_PREREQUISITES_CHECKED_AFTER_ONE_SHOT_RESERVATION",
            "PR_HEAD_COMPARE_AND_SWAP_NOT_ENFORCED",
        ],
        "finding_count": 17,
        "failure_class_distinct_from_record_197": True,
        "correction_authority": (
            "LOCAL_PRE_CI_STATIC_RUNTIME_SMALLEST_CORRECTION_AND_FRESH_FOUR_AXIS_QA"
        ),
        "observed_external_effects": zero_effects,
        "external_effects_authorized_now": False,
        "pr_b": "NOT_OPENED",
        "full_suite_rerun": False,
        "data_torrent_ready": False,
    }
    if (
        failure.get("decision_id") != "RCV3-20260831-199"
        or failure.get("decision_id")
        != _recovery_v2_next_decision_id(
            cast(str, base_release.get("decision_id")), failure_date
        )
        or failure.get("record_type") != "FAILURE"
        or failure.get("decision") != "PASS_AND_HOLD"
        or failure.get("responsible") != "C0"
        or failure.get("dissent") is not None
        or failure.get("proposal")
        != (
            "Record the distinct post-198 pre-commit static and runtime contradictions, "
            "hold every external effect, and authorize only field-local B105 annotations, "
            "the executable R3-to-R4-to-R5 provenance chain, whole-schedule deadline "
            "admission, exact E1 deadlines, prerequisite-first one-shot ordering, "
            "PR-head compare-and-swap, and append-only governance support."
        )
        or failure.get("objections")
        != [
            "All nine Bandit findings are low-severity false positives on boolean or integer audit fields, not credentials.",
            "Independent runtime and delivery review found four P0 and four P1 defects before any production invocation.",
            "Records 197 and 198 remain immutable; PR-B is unused and every external effect remains zero.",
        ]
        or failure.get("proof") != [_RECOVERY_V2_STATIC_QA_FAILURE_CLAIM]
        or failure.get("previous_hash") != base_release.get("hash")
        or not _json_exact_equal(failure.get("context"), expected_failure_context)
        or failure_date <= base_release_date
        or failure_date > observed_now
        or failure_date > expires_at
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")

    release_context = release.get("context")
    if not isinstance(release_context, dict):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    reviewed_candidate = release_context.get("reviewed_candidate")
    runtime_release = release_context.get("runtime_release")
    _validate_recovery_v2_frozen_projection(reviewed_candidate)
    _validate_recovery_v2_frozen_projection(runtime_release)
    if (
        not isinstance(reviewed_candidate, dict)
        or not isinstance(runtime_release, dict)
        or reviewed_candidate.get("projection_sha256")
        != DATA_TORRENT_RECOVERY_V2_STATIC_CORRECTION_REVIEWED_SNAPSHOT_SHA256
        or runtime_release.get("projection_sha256")
        != DATA_TORRENT_RECOVERY_V2_STATIC_CORRECTION_RUNTIME_SHA256
        or not isinstance(reviewed_candidate.get("files"), list)
        or len(cast(list[object], reviewed_candidate["files"])) != 135
        or not isinstance(runtime_release.get("files"), list)
        or len(cast(list[object], runtime_release["files"])) != 155
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    reviews: dict[str, dict[str, object]] = {}
    for agent_id, relative in DATA_TORRENT_RECOVERY_V2_STATIC_CORRECTION_REVIEW_PATHS.items():
        payload = _recovery_v2_read_bytes(
            root / relative,
            repository_root=root,
            maximum_bytes=262_144,
        )
        reviews[agent_id] = {
            "path": relative,
            "raw_sha256": hashlib.sha256(payload).hexdigest(),
            "field_count": 15,
            "reviewed_snapshot_sha256": reviewed_candidate["projection_sha256"],
            "recommended_action": "PASS_AND_HOLD_IMPLEMENTATION_RELEASE",
            "p0": 0,
            "p1": 0,
            "p2": 0,
            "open_threads": 0,
        }
    final_path = DATA_TORRENT_RECOVERY_V2_STATIC_CORRECTION_FINAL_REVIEW_PATH
    final_payload = _recovery_v2_read_bytes(
        root / final_path,
        repository_root=root,
        maximum_bytes=262_144,
    )
    final_binding = {
        "path": final_path,
        "raw_sha256": hashlib.sha256(final_payload).hexdigest(),
    }
    expected_files = sorted(
        {
            "configs/agents/mission-activation-matrix-v3.json",
            "docs/operations/DATA-TORRENT-RECOVERY-V2.md",
            *DATA_TORRENT_RECOVERY_V2_STATIC_CORRECTION_REVIEW_PATHS.values(),
            final_path,
            "reports/council/decision-ledger.jsonl",
            "reports/evidence/evidence-graph.json",
            "scripts/check_data_torrent_recovery_v2_scope.py",
            "scripts/dispatch_data_torrent_recovery_v2_stage.py",
            "scripts/install_chronos_runtime_bindings_v2.py",
            "scripts/materialize_data_torrent_recovery_v2_delivery_evidence.py",
            "src/robin/chronos_production.py",
            "tests/activation/test_chronos_migrate_verify_v2.py",
            "tests/activation/test_chronos_runtime_bindings_v2.py",
            "tests/council/test_data_torrent_recovery_v2_governance.py",
        }
    )
    expected_release_context = {
        "mission_id": "DATA_TORRENT_RECOVERY_V2",
        "phase": "LOCAL_PRE_CI_STATIC_RUNTIME_CORRECTION_RELEASE_AFTER_FRESH_QA",
        "program_start_sha": DATA_TORRENT_RECOVERY_V2_START_SHA,
        "writer": "C0",
        "writer_count": 1,
        "worktree": "ENGINEERING_WORKTREE:data-torrent-recovery-v2",
        "branch": "codex/data-torrent-recovery-v2",
        "head": DATA_TORRENT_RECOVERY_V2_START_SHA,
        "pr": "PENDING",
        "files": expected_files,
        "supersedes_release_claim_id": _RECOVERY_V2_LOCAL_CORRECTION_RELEASE_CLAIM,
        "supersedes_release_decision_id": base_release.get("decision_id"),
        "supersedes_release_record_hash": base_release.get("hash"),
        "failure_record_id": failure.get("decision_id"),
        "failure_record_hash": failure.get("hash"),
        "manifest": dict(expected_manifest),
        "effect_contract": dict(expected_effect),
        "postgresql_call_graph": dict(expected_call_graph),
        "reviewed_candidate": reviewed_candidate,
        "reviewed_snapshot_sha256": reviewed_candidate["projection_sha256"],
        "runtime_release": runtime_release,
        "defects": {"open_p0": 0, "open_p1": 0, "open_p2": 0, "open_threads": 0},
        "release_conditions": {
            "production_effects_authorized_now": False,
            "exact_head_safe_v2_required": True,
            "normal_merge_required": True,
            "postmerge_safe_v2_required": True,
            "immediate_predecessor_required_for_each_stage": True,
        },
        "progression_contract": {
            "council_role": "CONTROL_AND_RECORD_ONLY",
            "progression_mode": "AUTOMATIC_WITHIN_AUTHORIZED_MANIFEST",
            "controller_path": "scripts/dispatch_data_torrent_recovery_v2_stage.py",
            "stage_mapping_bound_to_effect_contract": True,
            "predecessor_attestation_and_semantic_validation_before_effect": True,
            "pr_c_phase_one_stage_finished_record_required": True,
            "pr_c_terminal_decision_record_required": True,
        },
        "observed_external_effects": zero_effects,
        "independent_reviews": reviews,
        "final_review": final_binding,
        "targeted_tests": {
            "governance_release": "PASS",
            "recovery_domain": "PASS",
            "r3_r4_handoff_and_local_preconditions": "PASS",
            "e1_exact_300_second_deadlines": "PASS",
            "bandit_safe_v2_scope": "PASS",
            "ruff_changed_python": "PASS",
            "mypy_recovery_v2_strict": "PASS",
            "compileall": "PASS",
            "pip_check": "PASS",
            "secret_scan": "PASS",  # nosec B105
            "full_suite_rerun": "FALSE",
            "unapproved_network_attempts": "0",
        },
        "proofs_reused": [
            f"base-release-record:{base_release.get('hash')}",
            f"static-qa-failure-record:{failure.get('hash')}",
            f"manifest-raw:{DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256}",
            f"effect-contract-raw:{DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_SHA256}",
        ],
        "external_effects_authorized_now": False,
        "data_torrent_ready": False,
    }
    if (
        release.get("decision_id") != "RCV3-20260831-200"
        or release.get("decision_id")
        != _recovery_v2_next_decision_id(cast(str, failure.get("decision_id")), release_date)
        or release.get("record_type") != "DECISION"
        or release.get("decision") != "PASS_AND_HOLD"
        or release.get("responsible") != "C0"
        or release.get("dissent") is not None
        or release.get("proposal")
        != (
            "Release the freshly reviewed pre-commit static and runtime correction "
            "while preserving PR-B, production, and every one-shot effect."
        )
        or release.get("objections")
        != [
            "The nine B105 findings were false positives and each annotation is field-local.",
            "The R3-to-R4-to-R5 provenance chain, full R4 schedule, E1 deadlines, local prerequisites, and PR-head CAS now fail closed before effect.",
            "The full suite was not rerun; SAFE V2 remains the sole complete post-commit suite.",
            "Every production and external effect remains zero until its exact predecessor gate.",
        ]
        or release.get("proof") != [_RECOVERY_V2_STATIC_CORRECTION_RELEASE_CLAIM]
        or release.get("previous_hash") != failure.get("hash")
        or not _json_exact_equal(release.get("context"), expected_release_context)
        or release_date <= failure_date
        or release_date > observed_now
        or release_date > expires_at
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    reviewed_snapshot = cast(str, reviewed_candidate["projection_sha256"])
    _validate_recovery_v2_agent_reports(
        root,
        bindings=reviews,
        reviewed_snapshot_sha256=reviewed_snapshot,
        review_paths=DATA_TORRENT_RECOVERY_V2_STATIC_CORRECTION_REVIEW_PATHS,
    )
    _validate_recovery_v2_final_review(
        root,
        binding=final_binding,
        relative=final_path,
        reviewed_snapshot_sha256=reviewed_snapshot,
        schema_version="data-torrent-recovery-v2-post-198-static-correction-final-review-v3",
        review_paths=DATA_TORRENT_RECOVERY_V2_STATIC_CORRECTION_REVIEW_PATHS,
        reviewed_file_count=len(cast(list[object], reviewed_candidate["files"])),
        reviewed_at_not_after=release_date,
        reviewed_at_not_before=failure_date,
    )
    return release_date


def _validate_recovery_v2_exact_head_ci_correction_pair(
    failure: dict[str, Any],
    release: dict[str, Any],
    *,
    root: Path,
    base_release: dict[str, Any],
    base_release_date: datetime,
    observed_now: datetime,
    expected_manifest: Mapping[str, str],
    expected_effect: Mapping[str, str],
    expected_call_graph: Mapping[str, str],
) -> datetime:
    """Validate SAFE V2 cycle-one failure evidence and its one coherent correction."""

    try:
        failure_date = _authority_timestamp(
            failure.get("date"), field="exact_head_ci_cycle_one_failure_date"
        )
        release_date = _authority_timestamp(
            release.get("date"), field="exact_head_ci_cycle_one_correction_date"
        )
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    expires_at = _authority_timestamp(
        DATA_TORRENT_RECOVERY_V2_EXPIRES_AT,
        field="recovery_v2_expiry",
    )
    production_zero = {
        "neon_gets": 0,
        "neon_mutations": 0,
        "postgresql_production_connections": 0,
        "postgresql_production_writes": 0,
        "r2_gets": 0,
        "r2_puts": 0,
        "official_reads": 0,
        "provider_requests": 0,
        "secret_writes": 0,  # nosec B105 - effect counter, not a credential.
        "production_workflow_dispatches": 0,
    }
    delivery_effects = {
        "git_remote_writes": 1,
        "github_pull_request_writes": 1,
        "github_merge_commits": 0,
        "github_safe_v2_runs": 1,
        "failed_run_reruns": 0,
    }
    pr_binding = {
        "number": 80,
        "url": "https://github.com/dddur75/robin-stades-ng/pull/80",
        "head_ref": "codex/data-torrent-recovery-v2",
        "base_ref": "main",
    }
    ci_evidence = {
        "workflow": "00 - Qualite continue SAFE V2",
        "run_id": DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_1_RUN_ID,
        "run_attempt": 1,
        "event": "pull_request",
        "head_sha": DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_1_HEAD,
        "status": "completed",
        "conclusion": "failure",
        "created_at": "2026-08-31T17:36:38Z",
        "completed_at": "2026-08-31T17:50:55Z",
        "url": (
            "https://github.com/dddur75/robin-stades-ng/actions/runs/33420499802"
        ),
        "successful_job_ids": [
            99581397701,
            99581397931,
            99581397982,
            99581398096,
            99581398160,
            99581398210,
            99581398234,
            99583580343,
        ],
        "root_failure_jobs": [
            {
                "job_id": 99581398120,
                "name": "Recovery V2 — scope guard exact",
                "step": "Prouver le scope Recovery V2 depuis START_SHA",
                "failure": "MODULE_NOT_FOUND_ROBIN_BEFORE_SCOPE_PROOF",
            },
            {
                "job_id": 99581398246,
                "name": "Bounded live canary - Ubuntu",
                "step": "Refuser les secrets et chemins locaux suivis",
                "failure": "IMMUTABLE_LEDGER_LOCAL_PATH_FALSE_POSITIVE",
            },
            {
                "job_id": 99583580309,
                "name": "Chronos PostgreSQL profiles / tests (superuser)",
                "step": "Valider le lifecycle dual-principal et le cycle 0015",
                "failure": "CHRONOS_CI_MIGRATOR_ALTER_ROLE_NONMINIMAL",
            },
            {
                "job_id": 99583580313,
                "name": (
                    "Chronos PostgreSQL profiles / tests "
                    "(non_superuser_createrole)"
                ),
                "step": "Valider le lifecycle dual-principal et le cycle 0015",
                "failure": "CHRONOS_CI_MIGRATOR_ALTER_ROLE_NONMINIMAL",
            },
            {
                "job_id": 99583580492,
                "name": "Chronos PostgreSQL profiles / Chronos static contracts",
                "step": "Run python scripts/check_no_tracked_absolute_paths.py",
                "failure": "IMMUTABLE_LEDGER_LOCAL_PATH_FALSE_POSITIVE",
            },
        ],
        "dependent_failure_jobs": [
            {
                "job_id": 99585553638,
                "name": "tests",
                "step": "Refuser tout prerequis absent, annule ou en echec",
                "failure": "PREREQUISITE_FAILURE_ONLY",
            }
        ],
        "all_terminal_jobs_collected": True,
        "failed_run_rerun": False,
    }
    ci_evidence_sha256 = hashlib.sha256(
        json.dumps(
            ci_evidence,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    ci_created_at = _authority_timestamp(
        ci_evidence["created_at"], field="exact_head_safe_v2_created_at"
    )
    ci_completed_at = _authority_timestamp(
        ci_evidence["completed_at"], field="exact_head_safe_v2_completed_at"
    )
    root_causes = [
        {
            "root_cause": "SCOPE_GUARD_CLEAN_RUNNER_IMPORTS_NOT_BOOTSTRAPPED",
            "affected_job_ids": [99581398120],
            "correction_paths": [
                ".github/workflows/ci-safe-v2.yml",
                "tests/data_torrent/test_ci_lock_contract_v1.py",
            ],
        },
        {
            "root_cause": "IMMUTABLE_RECORD_194_LOCAL_PATH_REJECTED_BY_GLOBAL_SCANNER",
            "affected_job_ids": [99581398246, 99583580492],
            "correction_paths": [
                "scripts/check_no_tracked_absolute_paths.py",
                "tests/portability/test_no_tracked_absolute_paths.py",
            ],
        },
        {
            "root_cause": "MIGRATOR_ASSERTION_SCANNED_UNRELATED_EXECUTOR_SOURCE",
            "affected_job_ids": [99583580309, 99583580313],
            "correction_paths": [
                "scripts/run_chronos_dual_principal_ci_v2.py",
                "tests/chronos/test_chronos_dual_principal_v2.py",
            ],
        },
    ]
    expected_failure_context = {
        "mission_id": "DATA_TORRENT_RECOVERY_V2",
        "phase": "PR_A_EXACT_HEAD_SAFE_V2_CYCLE_1_FAILURE",
        "program_start_sha": DATA_TORRENT_RECOVERY_V2_START_SHA,
        "release_decision_id": base_release.get("decision_id"),
        "release_record_hash": base_release.get("hash"),
        "active_release_claim_id": _RECOVERY_V2_STATIC_CORRECTION_RELEASE_CLAIM,
        "writer": "C0",
        "worktree": "ENGINEERING_WORKTREE:data-torrent-recovery-v2",
        "branch": "codex/data-torrent-recovery-v2",
        "head": DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_1_HEAD,
        "pr": pr_binding,
        "exact_head_safe_v2": ci_evidence,
        "exact_head_safe_v2_sha256": ci_evidence_sha256,
        "root_causes": root_causes,
        "correction_authority": (
            "FIRST_EXACT_HEAD_CI_FAILURE_ONE_COHERENT_CORRECTION_NEW_SHA_CYCLE_2"
        ),
        "ci_cycle_budget": {
            "maximum": 3,
            "consumed": 1,
            "remaining": 2,
            "next_cycle": 2,
            "failed_run_rerun": False,
            "new_head_required": True,
        },
        "observed_delivery_effects": delivery_effects,
        "observed_production_effects": production_zero,
        "full_suite_rerun": False,
        "data_torrent_ready": False,
    }
    if (
        failure.get("decision_id") != "RCV3-20260831-201"
        or failure.get("decision_id")
        != _recovery_v2_next_decision_id(
            cast(str, base_release.get("decision_id")), failure_date
        )
        or failure.get("record_type") != "FAILURE"
        or failure.get("decision") != "PASS_AND_HOLD"
        or failure.get("responsible") != "C0"
        or failure.get("dissent") is not None
        or failure.get("proposal")
        != (
            "Record exact-head SAFE V2 cycle 1 as a terminal failed attempt, hold "
            "merge and every production effect, and authorize only one coherent "
            "three-root-cause correction on a new SHA for cycle 2."
        )
        or failure.get("objections")
        != [
            "The failed run is immutable and must never be rerun.",
            "Five root-failure jobs reduce to three local causes; the tests job failed only on prerequisites.",
            "The successful jobs are retained as evidence but cannot override the failed exact-head gate.",
            "PR-B, merge, production workflows, secrets, Neon, PostgreSQL, R2, official reads and provider calls remain unused.",
        ]
        or failure.get("proof") != [_RECOVERY_V2_EXACT_HEAD_CI_FAILURE_CLAIM]
        or failure.get("previous_hash") != base_release.get("hash")
        or not _json_exact_equal(failure.get("context"), expected_failure_context)
        or ci_created_at > ci_completed_at
        or ci_completed_at >= failure_date
        or failure_date <= base_release_date
        or failure_date > observed_now
        or failure_date > expires_at
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")

    release_context = release.get("context")
    if (
        release.get("decision_id") != DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_RELEASE_ID
        or release.get("decision_id")
        != _recovery_v2_next_decision_id(
            cast(str, failure.get("decision_id")), release_date
        )
        or release.get("record_type") != "DECISION"
        or release.get("decision") != "PASS_AND_HOLD"
        or release.get("responsible") != "C0"
        or release.get("dissent") is not None
        or release.get("proposal")
        != (
            "Release the independently reviewed three-root-cause correction to one "
            "new exact-head SAFE V2 cycle while merge, production and every one-shot "
            "effect remain held."
        )
        or release.get("objections")
        != [
            "Cycle 1 remains a terminal failed attempt and is never rerun.",
            "The scope guard now bootstraps only the hash-locked Recovery dependency set before proof.",
            "The immutable ledger exception is record-, hash-, value- and cardinality-bound, and the migrator check is function-scoped.",
            "The sole full suite was not rerun; cycle 2 on a new SHA remains the required complete gate.",
            "Every production and one-shot effect remains dormant until its exact predecessor gate.",
        ]
        or release.get("proof")
        != [_RECOVERY_V2_EXACT_HEAD_CI_CORRECTION_RELEASE_CLAIM]
        or release.get("previous_hash") != failure.get("hash")
        or release.get("hash") != DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_RELEASE_HASH
        or not isinstance(release_context, dict)
        or release_date <= failure_date
        or release_date > observed_now
        or release_date > expires_at
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    reviewed_candidate = cast(dict[str, Any], release_context.get("reviewed_candidate"))
    runtime_release = cast(dict[str, Any], release_context.get("runtime_release"))
    _validate_recovery_v2_frozen_projection(reviewed_candidate)
    _validate_recovery_v2_frozen_projection(runtime_release)
    if (
        release_context.get("reviewed_snapshot_sha256")
        != DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_REVIEWED_SNAPSHOT_SHA256
        or reviewed_candidate.get("projection_sha256")
        != DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_REVIEWED_SNAPSHOT_SHA256
        or runtime_release.get("projection_sha256")
        != DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_RUNTIME_SHA256
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    reviewed_snapshot = DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_REVIEWED_SNAPSHOT_SHA256
    _validate_recovery_v2_agent_reports(
        root,
        bindings=release_context.get("independent_reviews"),
        reviewed_snapshot_sha256=reviewed_snapshot,
        review_paths=DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_REVIEW_PATHS,
    )
    _validate_recovery_v2_final_review(
        root,
        binding=release_context.get("final_review"),
        relative=DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_FINAL_REVIEW_PATH,
        reviewed_snapshot_sha256=reviewed_snapshot,
        schema_version="data-torrent-recovery-v2-exact-head-ci-cycle-1-final-review-v3",
        review_paths=DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_REVIEW_PATHS,
        reviewed_file_count=len(cast(list[object], reviewed_candidate["files"])),
        reviewed_at_not_after=release_date,
        reviewed_at_not_before=failure_date,
    )
    return release_date


def _validate_recovery_v2_post_202_b101_correction_pair(
    failure: dict[str, Any],
    release: dict[str, Any],
    *,
    root: Path,
    base_release: dict[str, Any],
    base_release_date: datetime,
    observed_now: datetime,
    expected_manifest: Mapping[str, str],
    expected_effect: Mapping[str, str],
    expected_call_graph: Mapping[str, str],
) -> datetime:
    """Validate the append-only post-202 Bandit finding and fail-closed closure."""

    try:
        failure_date = _authority_timestamp(
            failure.get("date"), field="post_202_b101_failure_date"
        )
        release_date = _authority_timestamp(
            release.get("date"), field="post_202_b101_correction_date"
        )
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    expires_at = _authority_timestamp(
        DATA_TORRENT_RECOVERY_V2_EXPIRES_AT,
        field="recovery_v2_expiry",
    )
    production_zero = {
        "neon_gets": 0,
        "neon_mutations": 0,
        "postgresql_production_connections": 0,
        "postgresql_production_writes": 0,
        "r2_gets": 0,
        "r2_puts": 0,
        "official_reads": 0,
        "provider_requests": 0,
        "secret_writes": 0,  # nosec B105 - effect counter, not a credential.
        "production_workflow_dispatches": 0,
    }
    delivery_effects = {
        "git_remote_writes": 1,
        "github_pull_request_writes": 1,
        "github_merge_commits": 0,
        "github_safe_v2_runs": 1,
        "failed_run_reruns": 0,
    }
    pr_binding = {
        "number": 80,
        "url": "https://github.com/dddur75/robin-stades-ng/pull/80",
        "head_ref": "codex/data-torrent-recovery-v2",
        "base_ref": "main",
    }
    finding = {
        "tool": "bandit -q -r src/robin",
        "rule": "B101",
        "path": "src/robin/recovery_v2_filesystem.py",
        "symbol": "publish_exclusive_bytes",
        "vulnerable_lf_sha256": (
            "d770f9fbcac097161b4be909a289e5dddd7884d2ac9015ce3185acbf6e4ace60"
        ),
        "risk": "PYTHON_OPTIMIZATION_REMOVES_POSIX_ROLLBACK_ASSERTION",
    }
    correction = {
        "path": "src/robin/recovery_v2_filesystem.py",
        "test_path": "tests/activation/test_recovery_v2_atomic_evidence.py",
        "implementation": "EXPLICIT_FAIL_CLOSED_METADATA_GUARD",
    }
    expected_failure_context = {
        "mission_id": "DATA_TORRENT_RECOVERY_V2",
        "phase": "POST_202_PRE_CYCLE_2_BANDIT_B101_FAILURE",
        "program_start_sha": DATA_TORRENT_RECOVERY_V2_START_SHA,
        "release_decision_id": base_release.get("decision_id"),
        "release_record_hash": base_release.get("hash"),
        "active_release_claim_id": _RECOVERY_V2_EXACT_HEAD_CI_CORRECTION_RELEASE_CLAIM,
        "writer": "C0",
        "writer_count": 1,
        "worktree": "ENGINEERING_WORKTREE:data-torrent-recovery-v2",
        "branch": "codex/data-torrent-recovery-v2",
        "head": DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_1_HEAD,
        "pr": pr_binding,
        "finding": finding,
        "authorized_correction": correction,
        "correction_policy": "FIRST_SIMILAR_FAILURE_SMALLEST_CORRECTION_SAME_LEVEL",
        "failure_class_distinct_from_record_199": {
            "record_id": "RCV3-20260831-199",
            "record_hash": (
                "25eb2b9c2fbc10fb54525bb646d35c6cf0003e14e4445cf40248125b55befb75"
            ),
            "prior_class": "BANDIT_B105_FALSE_POSITIVES_AND_OPERABILITY_FINDINGS",
            "current_class": "BANDIT_B101_OPTIMIZATION_REMOVABLE_ROLLBACK_ASSERTION",
            "same_failure_class": False,
            "current_class_attempt": 1,
        },
        "ci_cycle_contract": {
            "maximum": 3,
            "consumed": 1,
            "remaining": 2,
            "next_cycle": 2,
            "failed_run_rerun": False,
            "new_head_required": True,
        },
        "observed_delivery_effects": delivery_effects,
        "observed_production_effects": production_zero,
        "full_suite_rerun": False,
        "external_effects_authorized_now": False,
        "data_torrent_ready": False,
    }
    if (
        failure.get("decision_id") != "RCV3-20260831-203"
        or failure.get("decision_id")
        != _recovery_v2_next_decision_id(
            cast(str, base_release.get("decision_id")), failure_date
        )
        or failure.get("record_type") != "FAILURE"
        or failure.get("decision") != "PASS_AND_HOLD"
        or failure.get("responsible") != "C0"
        or failure.get("dissent") is not None
        or failure.get("proposal")
        != (
            "Record the first post-202 Bandit B101 failure of a class distinct from "
            "record 199, preserve release 202 byte-for-byte, hold cycle 2 and every "
            "production effect, and authorize only the explicit fail-closed POSIX "
            "rollback metadata correction with fresh independent QA."
        )
        or failure.get("objections")
        != [
            "Release 202 remains immutable but cannot authorize cycle 2 after the later B101 finding.",
            "Python optimization could remove the rollback assertion on the POSIX exclusive-publication path.",
            "Cycle 2, merge and every production or one-shot effect remain held.",
            "The smallest correction is one explicit metadata guard plus its focused regression and governance closure.",
        ]
        or failure.get("proof") != [_RECOVERY_V2_POST_202_B101_FAILURE_CLAIM]
        or failure.get("previous_hash") != base_release.get("hash")
        or not _json_exact_equal(failure.get("context"), expected_failure_context)
        or failure_date <= base_release_date
        or failure_date > observed_now
        or failure_date > expires_at
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")

    release_context = release.get("context")
    if not isinstance(release_context, dict):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    reviewed_candidate = release_context.get("reviewed_candidate")
    runtime_release = release_context.get("runtime_release")
    _validate_recovery_v2_frozen_projection(reviewed_candidate)
    _validate_recovery_v2_frozen_projection(runtime_release)
    if (
        not isinstance(reviewed_candidate, dict)
        or not isinstance(runtime_release, dict)
        or reviewed_candidate.get("projection_sha256")
        != DATA_TORRENT_RECOVERY_V2_POST_202_B101_REVIEWED_SNAPSHOT_SHA256
        or runtime_release.get("projection_sha256")
        != DATA_TORRENT_RECOVERY_V2_POST_202_B101_RUNTIME_SHA256
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    reviewed_candidate = cast(dict[str, Any], reviewed_candidate)
    runtime_release = cast(dict[str, Any], runtime_release)
    reviews: dict[str, dict[str, object]] = {}
    for agent_id, relative in DATA_TORRENT_RECOVERY_V2_POST_202_B101_REVIEW_PATHS.items():
        payload = _recovery_v2_read_bytes(
            root / relative,
            repository_root=root,
            maximum_bytes=262_144,
        )
        reviews[agent_id] = {
            "path": relative,
            "raw_sha256": hashlib.sha256(payload).hexdigest(),
            "field_count": 15,
            "reviewed_snapshot_sha256": reviewed_candidate["projection_sha256"],
            "recommended_action": "PASS_AND_HOLD_IMPLEMENTATION_RELEASE",
            "p0": 0,
            "p1": 0,
            "p2": 0,
            "open_threads": 0,
        }
    final_path = DATA_TORRENT_RECOVERY_V2_POST_202_B101_FINAL_REVIEW_PATH
    final_payload = _recovery_v2_read_bytes(
        root / final_path,
        repository_root=root,
        maximum_bytes=262_144,
    )
    final_binding = {
        "path": final_path,
        "raw_sha256": hashlib.sha256(final_payload).hexdigest(),
    }
    expected_files = sorted(
        {
            ".github/workflows/ci-safe-v2.yml",
            "configs/agents/mission-activation-matrix-v3.json",
            "docs/operations/DATA-TORRENT-RECOVERY-V2.md",
            *DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_REVIEW_PATHS.values(),
            DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_FINAL_REVIEW_PATH,
            *DATA_TORRENT_RECOVERY_V2_POST_202_B101_REVIEW_PATHS.values(),
            final_path,
            "reports/council/decision-ledger.jsonl",
            "reports/evidence/evidence-graph.json",
            "scripts/check_data_torrent_recovery_v2_scope.py",
            "scripts/check_no_tracked_absolute_paths.py",
            "scripts/materialize_data_torrent_recovery_v2_delivery_evidence.py",
            "scripts/run_chronos_dual_principal_ci_v2.py",
            "src/robin/chronos_production.py",
            "src/robin/recovery_v2_filesystem.py",
            "tests/activation/test_recovery_v2_atomic_evidence.py",
            "tests/chronos/test_chronos_dual_principal_v2.py",
            "tests/council/test_data_torrent_recovery_v2_governance.py",
            "tests/data_torrent/test_ci_lock_contract_v1.py",
            "tests/portability/test_no_tracked_absolute_paths.py",
        }
    )
    expected_release_context = {
        "mission_id": "DATA_TORRENT_RECOVERY_V2",
        "phase": "POST_202_B101_CORRECTION_RELEASE_AFTER_INDEPENDENT_QA",
        "program_start_sha": DATA_TORRENT_RECOVERY_V2_START_SHA,
        "writer": "C0",
        "writer_count": 1,
        "worktree": "ENGINEERING_WORKTREE:data-torrent-recovery-v2",
        "branch": "codex/data-torrent-recovery-v2",
        "head": DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_1_HEAD,
        "candidate_parent": DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_1_HEAD,
        "pr": pr_binding,
        "files": expected_files,
        "supersedes_release_claim_id": _RECOVERY_V2_EXACT_HEAD_CI_CORRECTION_RELEASE_CLAIM,
        "supersedes_release_decision_id": base_release.get("decision_id"),
        "supersedes_release_record_hash": base_release.get("hash"),
        "failure_record_id": failure.get("decision_id"),
        "failure_record_hash": failure.get("hash"),
        "manifest": dict(expected_manifest),
        "effect_contract": dict(expected_effect),
        "postgresql_call_graph": dict(expected_call_graph),
        "reviewed_candidate": reviewed_candidate,
        "reviewed_snapshot_sha256": reviewed_candidate["projection_sha256"],
        "runtime_release": runtime_release,
        "preflight_correction": correction,
        "defects": {"open_p0": 0, "open_p1": 0, "open_p2": 0, "open_threads": 0},
        "release_conditions": {
            "production_effects_authorized_now": False,
            "exact_head_safe_v2_cycle_2_required": True,
            "normal_merge_required": True,
            "postmerge_safe_v2_required": True,
            "immediate_predecessor_required_for_each_stage": True,
        },
        "progression_contract": {
            "council_role": "CONTROL_AND_RECORD_ONLY",
            "progression_mode": "AUTOMATIC_WITHIN_AUTHORIZED_MANIFEST",
            "controller_path": "scripts/dispatch_data_torrent_recovery_v2_stage.py",
            "stage_mapping_bound_to_effect_contract": True,
            "predecessor_attestation_and_semantic_validation_before_effect": True,
            "pr_c_phase_one_stage_finished_record_required": True,
            "pr_c_terminal_decision_record_required": True,
        },
        "ci_cycle_contract": {
            "maximum": 3,
            "consumed": 1,
            "remaining": 2,
            "next_cycle": 2,
            "failed_run_rerun": False,
            "new_head_required": True,
        },
        "observed_delivery_effects": delivery_effects,
        "observed_production_effects": production_zero,
        "independent_reviews": reviews,
        "final_review": final_binding,
        "targeted_tests": {
            "b101_regression": "PASS",
            "ci_root_cause_regressions": "PASS",
            "governance_release": "PASS",
            "recovery_domain": "PASS",
            "ruff_changed_python": "PASS",
            "mypy_recovery_v2_strict": "PASS",
            "bandit_recovery_v2": "PASS",
            "compileall": "PASS",
            "pip_check": "PASS",
            "json_yaml": "PASS",
            "secret_and_local_path_scan": "PASS",  # nosec B105 - QA verdict.
            "full_suite_rerun": "FALSE",
            "unapproved_network_attempts": "0",
        },
        "proofs_reused": [
            f"superseded-release-record:{base_release.get('hash')}",
            f"post-202-b101-failure-record:{failure.get('hash')}",
            f"vulnerable-source-lf:{finding['vulnerable_lf_sha256']}",
            f"manifest-raw:{DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256}",
            f"effect-contract-raw:{DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_SHA256}",
        ],
        "external_effects_authorized_now": False,
        "data_torrent_ready": False,
    }
    if (
        release.get("decision_id") != "RCV3-20260831-204"
        or release.get("decision_id")
        != _recovery_v2_next_decision_id(
            cast(str, failure.get("decision_id")), release_date
        )
        or release.get("record_type") != "DECISION"
        or release.get("decision") != "PASS_AND_HOLD"
        or release.get("responsible") != "C0"
        or release.get("dissent") is not None
        or release.get("proposal")
        != (
            "Release the independently reviewed post-202 B101 fail-closed correction "
            "to one new exact-head SAFE V2 cycle while merge, production and every "
            "one-shot effect remain held."
        )
        or release.get("objections")
        != [
            "Release 202 remains byte-for-byte preserved and is superseded only by this append-only decision.",
            "The POSIX rollback assertion is replaced by an explicit fail-closed metadata guard with a focused regression.",
            "The sole full suite was not rerun; cycle 2 on a new SHA remains the required complete gate.",
            "Every production and one-shot effect remains dormant until its exact predecessor gate.",
        ]
        or release.get("proof")
        != [_RECOVERY_V2_POST_202_B101_CORRECTION_RELEASE_CLAIM]
        or release.get("previous_hash") != failure.get("hash")
        or failure.get("hash") != DATA_TORRENT_RECOVERY_V2_POST_202_B101_FAILURE_HASH
        or release.get("hash") != DATA_TORRENT_RECOVERY_V2_POST_202_B101_RELEASE_HASH
        or not _json_exact_equal(release.get("context"), expected_release_context)
        or release_date <= failure_date
        or release_date > observed_now
        or release_date > expires_at
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    reviewed_snapshot = cast(str, reviewed_candidate["projection_sha256"])
    snapshot_ref = f"REVIEWED_SNAPSHOT_SHA256:{reviewed_snapshot}"
    failure_ref = f"COUNCIL_FAILURE_RECORD_SHA256:{failure.get('hash')}"
    expected_role_facts: dict[str, list[dict[str, object]]] = {
        "C2": [
            {
                "claim": (
                    "The ledger prefix through record 202 is byte-for-byte preserved, "
                    "and records 203 and 204 are its sole contiguous B101 failure and "
                    "reviewed-correction successors."
                ),
                "evidence_refs": [
                    snapshot_ref,
                    (
                        "LEDGER_PREFIX_THROUGH_202_SHA256:"
                        f"{DATA_TORRENT_RECOVERY_V2_LEDGER_PREFIX_THROUGH_202_SHA256}"
                    ),
                    failure_ref,
                ],
                "status": "VERIFIED",
            },
            {
                "claim": (
                    "Record 204 supersedes release 202 without rewriting its decision, "
                    "review reports, or frozen projection bindings."
                ),
                "evidence_refs": [
                    snapshot_ref,
                    (
                        "RECORD_202_SHA256:"
                        f"{DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_RELEASE_HASH}"
                    ),
                    (
                        "src/robin/chronos_production.py:"
                        "_validate_recovery_v2_post_202_b101_correction_pair"
                    ),
                ],
                "status": "VERIFIED",
            },
        ],
        "C4": [
            {
                "claim": (
                    "The POSIX publication rollback path calls an explicit metadata "
                    "guard that remains fail-closed under optimized Python."
                ),
                "evidence_refs": [
                    snapshot_ref,
                    "src/robin/recovery_v2_filesystem.py:publish_exclusive_bytes",
                    (
                        "tests/activation/test_recovery_v2_atomic_evidence.py:"
                        "test_posix_atomic_publish_uses_an_explicit_fail_closed_metadata_guard"
                    ),
                ],
                "status": "VERIFIED",
            },
            {
                "claim": (
                    "The Recovery V2 scope guard binds the expanded 162-path global "
                    "allowlist and 107-path PR-A projection to exact hashes."
                ),
                "evidence_refs": [
                    snapshot_ref,
                    "ALLOWED_PATHS_SHA256:9a0358ef0f4b4161385efe4785a9f5653ececc71dc42d179c4d116bf12a6c9fd",
                    "PR_A_PATHS_SHA256:20f13358feb1f2cfb1e48617f178dc6925f43a765105b9f7ee039fd4cc28a2e1",
                ],
                "status": "VERIFIED",
            },
        ],
        "DP6": [
            {
                "claim": (
                    "Delivery effects remain exactly one branch push, one PR write, "
                    "and one SAFE V2 run while all production-effect counters remain zero."
                ),
                "evidence_refs": [
                    snapshot_ref,
                    "GITHUB_PR:https://github.com/dddur75/robin-stades-ng/pull/80",
                    "SAFE_V2_RUN:https://github.com/dddur75/robin-stades-ng/actions/runs/33420499802",
                ],
                "status": "VERIFIED",
            },
            {
                "claim": (
                    "The immutable record-194 portability exception and dual-principal "
                    "migrator scan remain narrowly value- and function-scoped."
                ),
                "evidence_refs": [
                    snapshot_ref,
                    "scripts/check_no_tracked_absolute_paths.py:LEDGER_EXCEPTION",
                    "scripts/run_chronos_dual_principal_ci_v2.py:provision_migrator",
                ],
                "status": "VERIFIED",
            },
        ],
        "A2": [
            {
                "claim": (
                    "SAFE V2 cycle 1 is terminal and never rerun; only cycle 2 on a "
                    "new exact head is released by record 204."
                ),
                "evidence_refs": [
                    snapshot_ref,
                    "SAFE_V2_RUN_ID:33420499802",
                    failure_ref,
                ],
                "status": "VERIFIED",
            },
            {
                "claim": (
                    "The exact-head CI budget remains maximum three, consumed one, "
                    "remaining two, and merge plus every production stage stay held."
                ),
                "evidence_refs": [
                    snapshot_ref,
                    "CI_CYCLE_BUDGET:MAXIMUM=3;CONSUMED=1;REMAINING=2;NEXT=2",
                    "PRODUCTION_EFFECTS_OBSERVED:0",
                ],
                "status": "VERIFIED",
            },
        ],
    }
    _validate_recovery_v2_agent_reports(
        root,
        bindings=reviews,
        reviewed_snapshot_sha256=reviewed_snapshot,
        review_paths=DATA_TORRENT_RECOVERY_V2_POST_202_B101_REVIEW_PATHS,
        expected_facts=expected_role_facts,
    )
    _validate_recovery_v2_final_review(
        root,
        binding=final_binding,
        relative=final_path,
        reviewed_snapshot_sha256=reviewed_snapshot,
        schema_version="data-torrent-recovery-v2-post-202-b101-correction-final-review-v3",
        review_paths=DATA_TORRENT_RECOVERY_V2_POST_202_B101_REVIEW_PATHS,
        reviewed_file_count=len(cast(list[object], reviewed_candidate["files"])),
        reviewed_at_not_after=release_date,
        reviewed_at_not_before=failure_date,
        reviewed_at_must_precede=True,
        expected_external_effects={
            "git_remote_writes": 1,
            "github_writes": 1,
            "neon_gets": 0,
            "neon_mutations": 0,
            "postgresql_production_connections": 0,
            "postgresql_production_writes": 0,
            "r2_gets": 0,
            "r2_puts": 0,
            "official_reads": 0,
            "provider_requests": 0,
            "secret_writes": 0,  # nosec B105 - effect counter, not a credential.
        },
        expected_delivery_effects=delivery_effects,
    )
    return release_date


def _recovery_v2_cycle_2_expected_role_facts(
    reviewed_snapshot: str,
    failure_hash: object,
) -> dict[str, list[dict[str, object]]]:
    snapshot_ref = f"REVIEWED_SNAPSHOT_SHA256:{reviewed_snapshot}"
    failure_ref = f"COUNCIL_FAILURE_RECORD_SHA256:{failure_hash}"
    return {
        "C2": [
            {
                "claim": (
                    "The ledger prefix through record 204 is byte-for-byte preserved, "
                    "and records 205 and 206 are its sole contiguous cycle-2 failure "
                    "and independently reviewed E1-redesign successors."
                ),
                "evidence_refs": [
                    snapshot_ref,
                    (
                        "LEDGER_PREFIX_THROUGH_204_SHA256:"
                        f"{DATA_TORRENT_RECOVERY_V2_LEDGER_PREFIX_THROUGH_204_SHA256}"
                    ),
                    failure_ref,
                ],
                "status": "VERIFIED",
            },
            {
                "claim": (
                    "The frozen graph prefixes remain byte-identical and the append-only "
                    "suffix binds claims, nodes and edges for records 205 and 206."
                ),
                "evidence_refs": [
                    snapshot_ref,
                    f"CLAIMS_PREFIX_SHA256:{DATA_TORRENT_RECOVERY_V2_GRAPH_CLAIMS_PREFIX_SHA256}",
                    f"NODES_PREFIX_SHA256:{DATA_TORRENT_RECOVERY_V2_GRAPH_NODES_PREFIX_SHA256}",
                    f"EDGES_PREFIX_SHA256:{DATA_TORRENT_RECOVERY_V2_GRAPH_EDGES_PREFIX_SHA256}",
                ],
                "status": "VERIFIED",
            },
        ],
        "C4": [
            {
                "claim": (
                    "The Ubuntu bounded-live-canary checkout now fetches complete history "
                    "so START_SHA is available to its provenance assertion."
                ),
                "evidence_refs": [
                    snapshot_ref,
                    ".github/workflows/ci-safe-v2.yml:bounded-live-canary-ubuntu",
                    "tests/data_torrent/test_ci_lock_contract_v1.py",
                ],
                "status": "VERIFIED",
            },
            {
                "claim": (
                    "The PostgreSQL batch-contract regression now asserts the sanitized "
                    "fail-closed ChronosControlPlaneError; production exception wrapping is unchanged."
                ),
                "evidence_refs": [
                    snapshot_ref,
                    (
                        "src/robin/prospective_observatory/chronos_postgres.py:"
                        "SQLAlchemyPostgresFunctionClient.fetch_one"
                    ),
                    (
                        "tests/data_torrent/test_postgresql_v1.py:"
                        "test_recovery_v2_batch_contract_accepts_exact_created_binding_and_rejects_mutants"
                    ),
                ],
                "status": "VERIFIED",
            },
            {
                "claim": (
                    "The exact Mypy 2.3 CI commands now accept 216 global sources, "
                    "29 PostgreSQL-profile sources and fifteen strict Recovery scripts "
                    "after type-only corrections."
                ),
                "evidence_refs": [
                    snapshot_ref,
                    "src/robin/chronos_production.py",
                    "src/robin/recovery_v2_filesystem.py",
                    ".github/workflows/ci-safe-v2.yml:Typage strict",
                    "tests/data_torrent/test_data_torrent_replay_v2.py",
                    "tests/data_torrent/test_live_seal_provenance_v2.py",
                    "MYPY_GLOBAL_SOURCES:216;MYPY_POSTGRESQL_PROFILE_SOURCES:29;MYPY_RECOVERY_V2_STRICT_SCRIPTS:15",
                ],
                "status": "VERIFIED",
            },
        ],
        "DP6": [
            {
                "claim": (
                    "Delivery effects are exactly two non-force branch pushes, one PR "
                    "write and two SAFE V2 runs; every production-effect counter remains zero."
                ),
                "evidence_refs": [
                    snapshot_ref,
                    "GITHUB_PR:https://github.com/dddur75/robin-stades-ng/pull/80",
                    "SAFE_V2_RUN:https://github.com/dddur75/robin-stades-ng/actions/runs/33420499802",
                    "SAFE_V2_RUN:https://github.com/dddur75/robin-stades-ng/actions/runs/33433893502",
                ],
                "status": "VERIFIED",
            },
            {
                "claim": (
                    "Cycle 2 contains 17 terminal jobs partitioned into ten successes, "
                    "three root failures, one dependent failure and three skipped jobs, "
                    "with exactly two root causes."
                ),
                "evidence_refs": [
                    snapshot_ref,
                    "GITHUB_ACTIONS_RUN:33433893502",
                    "ROOT_FAILURE_JOB_IDS:99625571187,99627665582,99627665711",
                ],
                "status": "VERIFIED",
            },
        ],
        "A2": [
            {
                "claim": (
                    "SAFE V2 cycles 1 and 2 are terminal and never rerun; only cycle 3 "
                    "on a new SHA remains within the maximum-three budget."
                ),
                "evidence_refs": [
                    snapshot_ref,
                    "SAFE_V2_RUN_ID:33420499802",
                    "SAFE_V2_RUN_ID:33433893502",
                    "CI_CYCLE_BUDGET:MAXIMUM=3;CONSUMED=2;REMAINING=1;NEXT=3",
                ],
                "status": "VERIFIED",
            },
            {
                "claim": (
                    "The second similar exact-head failure is recorded as "
                    "FAIL_AND_REDESIGN with an explicit return to E1 before the final cycle."
                ),
                "evidence_refs": [snapshot_ref, failure_ref, "REDESIGN_RETURN_STAGE:E1"],
                "status": "VERIFIED",
            },
        ],
    }


def _validate_recovery_v2_exact_head_ci_cycle_2_correction_pair(
    failure: dict[str, Any],
    release: dict[str, Any],
    *,
    root: Path,
    base_release: dict[str, Any],
    base_release_date: datetime,
    observed_now: datetime,
    expected_manifest: Mapping[str, str],
    expected_effect: Mapping[str, str],
    expected_call_graph: Mapping[str, str],
) -> datetime:
    """Validate cycle-2 evidence and the sole release to a fresh cycle-3 head."""

    try:
        failure_date = _authority_timestamp(
            failure.get("date"), field="exact_head_ci_cycle_2_failure_date"
        )
        release_date = _authority_timestamp(
            release.get("date"), field="exact_head_ci_cycle_2_correction_date"
        )
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    expires_at = _authority_timestamp(
        DATA_TORRENT_RECOVERY_V2_EXPIRES_AT,
        field="recovery_v2_expiry",
    )
    production_zero = {
        "neon_gets": 0,
        "neon_mutations": 0,
        "postgresql_production_connections": 0,
        "postgresql_production_writes": 0,
        "r2_gets": 0,
        "r2_puts": 0,
        "official_reads": 0,
        "provider_requests": 0,
        "secret_writes": 0,  # nosec B105 - effect counter, not a credential.
        "production_workflow_dispatches": 0,
    }
    delivery_effects = {
        "git_remote_writes": 2,
        "github_pull_request_writes": 1,
        "github_merge_commits": 0,
        "github_safe_v2_runs": 2,
        "failed_run_reruns": 0,
    }
    pr_binding = {
        "number": 80,
        "url": "https://github.com/dddur75/robin-stades-ng/pull/80",
        "head_ref": "codex/data-torrent-recovery-v2",
        "base_ref": "main",
    }
    exact_head_safe_v2 = {
        "workflow": "00 - Qualite continue SAFE V2",
        "run_id": DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_2_RUN_ID,
        "run_attempt": 1,
        "url": "https://github.com/dddur75/robin-stades-ng/actions/runs/33433893502",
        "head_sha": DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_2_HEAD,
        "event": "pull_request",
        "status": "completed",
        "conclusion": "failure",
        "created_at": "2026-08-31T20:03:07Z",
        "completed_at": "2026-08-31T20:16:10Z",
        "job_partition": {
            "total": 17,
            "success": 10,
            "root_failure": 3,
            "dependent_failure": 1,
            "skipped": 3,
        },
        "successful_job_ids": [
            99625570557,
            99625570766,
            99625570925,
            99625570974,
            99625570980,
            99625571068,
            99625571101,
            99625571158,
            99627665678,
            99627665727,
        ],
        "skipped_job_ids": [99628437177, 99629477488, 99629478331],
        "all_terminal_jobs_collected": True,
        "failed_run_rerun": False,
        "root_failure_jobs": [
            {
                "job_id": 99625571187,
                "name": "Bounded live canary - Ubuntu",
                "status": "completed",
                "conclusion": "failure",
                "started_at": "2026-08-31T20:03:12Z",
                "completed_at": "2026-08-31T20:07:06Z",
                "cause_id": "SAFE_V2_UBUNTU_START_SHA_ABSENT_AFTER_SHALLOW_CHECKOUT",
            },
            {
                "job_id": 99627665582,
                "name": "Chronos PostgreSQL profiles / tests (non_superuser_createrole)",
                "status": "completed",
                "conclusion": "failure",
                "started_at": "2026-08-31T20:10:12Z",
                "completed_at": "2026-08-31T20:12:40Z",
                "cause_id": "RECOVERY_V2_POSTGRES_SANITIZED_EXCEPTION_EXPECTATION_MISMATCH",
            },
            {
                "job_id": 99627665711,
                "name": "Chronos PostgreSQL profiles / tests (superuser)",
                "status": "completed",
                "conclusion": "failure",
                "started_at": "2026-08-31T20:10:12Z",
                "completed_at": "2026-08-31T20:12:20Z",
                "cause_id": "RECOVERY_V2_POSTGRES_SANITIZED_EXCEPTION_EXPECTATION_MISMATCH",
            },
        ],
        "dependent_failure_jobs": [
            {
                "job_id": 99629340727,
                "name": "tests",
                "status": "completed",
                "conclusion": "failure",
                "started_at": "2026-08-31T20:15:45Z",
                "completed_at": "2026-08-31T20:16:09Z",
                "cause_id": "PREREQUISITE_FAILURE_ONLY",
            }
        ],
    }
    exact_head_safe_v2_sha256 = hashlib.sha256(
        json.dumps(
            exact_head_safe_v2,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    root_causes = [
        {
            "cause_id": "SAFE_V2_UBUNTU_START_SHA_ABSENT_AFTER_SHALLOW_CHECKOUT",
            "job_ids": [99625571187],
            "diagnosis": (
                "The Ubuntu canary used a depth-one checkout, so git show of the "
                "immutable START_SHA failed before that governance assertion could complete."
            ),
        },
        {
            "cause_id": "RECOVERY_V2_POSTGRES_SANITIZED_EXCEPTION_EXPECTATION_MISMATCH",
            "job_ids": [99627665582, 99627665711],
            "diagnosis": (
                "The database correctly rejected Recovery V2 mutants, while the test "
                "asserted the raw DBAPI exception instead of the client's sanitized "
                "ChronosControlPlaneError contract."
            ),
        },
    ]
    corrections = [
        {
            "cause_id": "SAFE_V2_UBUNTU_START_SHA_ABSENT_AFTER_SHALLOW_CHECKOUT",
            "paths": [
                ".github/workflows/ci-safe-v2.yml",
                "tests/data_torrent/test_ci_lock_contract_v1.py",
            ],
            "implementation": "FETCH_FULL_HISTORY_FOR_UBUNTU_IMMUTABLE_START_SHA_CHECK",
        },
        {
            "cause_id": "RECOVERY_V2_POSTGRES_SANITIZED_EXCEPTION_EXPECTATION_MISMATCH",
            "paths": ["tests/data_torrent/test_postgresql_v1.py"],
            "implementation": "ASSERT_SANITIZED_PUBLIC_CONTROL_PLANE_ERROR_CONTRACT",
        },
    ]
    cycle_contract = {
        "maximum": 3,
        "consumed": 2,
        "remaining": 1,
        "next_cycle": 3,
        "failed_run_rerun": False,
        "new_head_required": True,
    }
    expected_failure_context = {
        "mission_id": "DATA_TORRENT_RECOVERY_V2",
        "phase": "PR_A_EXACT_HEAD_SAFE_V2_CYCLE_2_FAILURE",
        "program_start_sha": DATA_TORRENT_RECOVERY_V2_START_SHA,
        "release_decision_id": base_release.get("decision_id"),
        "release_record_hash": base_release.get("hash"),
        "active_release_claim_id": _RECOVERY_V2_POST_202_B101_CORRECTION_RELEASE_CLAIM,
        "writer": "C0",
        "writer_count": 1,
        "worktree": "ENGINEERING_WORKTREE:data-torrent-recovery-v2",
        "branch": "codex/data-torrent-recovery-v2",
        "head": DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_2_HEAD,
        "pr": pr_binding,
        "exact_head_safe_v2": exact_head_safe_v2,
        "exact_head_safe_v2_sha256": exact_head_safe_v2_sha256,
        "root_causes": root_causes,
        "authorized_corrections": corrections,
        "correction_policy": "SECOND_SIMILAR_FAILURE_FAIL_AND_REDESIGN_RETURN_TO_E1",
        "similar_failure_predecessor": {
            "record_id": "RCV3-20260831-201",
            "record_hash": "be424917364ab1f68919a7b43e30ee45114ca2347229ce7ef01fcb5166536ff2",
            "failure_class": "EXACT_HEAD_SAFE_V2_FAILURE",
            "current_class_attempt": 2,
        },
        "redesign": {
            "return_stage": "E1",
            "design_revision": 2,
            "unchanged_third_attempt_forbidden": True,
            "cycle_3_requires_fresh_head": True,
        },
        "ci_cycle_contract": cycle_contract,
        "observed_delivery_effects": delivery_effects,
        "observed_production_effects": production_zero,
        "full_suite_rerun": False,
        "external_effects_authorized_now": False,
        "data_torrent_ready": False,
    }
    if (
        failure.get("decision_id") != "RCV3-20260831-205"
        or failure.get("decision_id")
        != _recovery_v2_next_decision_id(
            cast(str, base_release.get("decision_id")), failure_date
        )
        or failure.get("record_type") != "FAILURE"
        or failure.get("decision") != "FAIL_AND_REDESIGN"
        or failure.get("responsible") != "C0"
        or failure.get("dissent") is not None
        or failure.get("proposal")
        != (
            "Record the second terminal exact-head SAFE V2 failure, return to E1 "
            "for the smallest redesign of its two root causes, forbid every rerun "
            "of cycle 2 and every unchanged third attempt, and keep all effects held."
        )
        or failure.get("objections")
        != [
            "Cycle 2 is terminal failure and consumes the second of three exact-head CI cycles.",
            "A second similar exact-head failure requires FAIL_AND_REDESIGN and a return to E1.",
            "The Ubuntu shallow checkout could not read immutable START_SHA history.",
            "Both PostgreSQL profiles exposed one stale raw-exception test expectation; the client remained fail-closed and sanitized.",
            "The tests gate failure is dependent only and no production or one-shot effect occurred.",
        ]
        or failure.get("proof") != [_RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_FAILURE_CLAIM]
        or failure.get("previous_hash") != base_release.get("hash")
        or not _json_exact_equal(failure.get("context"), expected_failure_context)
        or failure_date
        <= _authority_timestamp(
            cast(str, exact_head_safe_v2["completed_at"]),
            field="exact_head_ci_cycle_2_completed_at",
        )
        or failure_date <= base_release_date
        or failure_date > observed_now
        or failure_date > expires_at
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")

    reviewed_candidate = data_torrent_recovery_v2_reviewed_candidate_projection(root)
    runtime_release = data_torrent_recovery_v2_release_projection(root)
    reviews: dict[str, dict[str, object]] = {}
    for agent_id, relative in DATA_TORRENT_RECOVERY_V2_CYCLE_2_CORRECTION_REVIEW_PATHS.items():
        payload = _recovery_v2_read_bytes(
            root / relative,
            repository_root=root,
            maximum_bytes=262_144,
        )
        reviews[agent_id] = {
            "path": relative,
            "raw_sha256": hashlib.sha256(payload).hexdigest(),
            "field_count": 15,
            "reviewed_snapshot_sha256": reviewed_candidate["projection_sha256"],
            "recommended_action": "PASS_AND_HOLD_IMPLEMENTATION_RELEASE",
            "p0": 0,
            "p1": 0,
            "p2": 0,
            "open_threads": 0,
        }
    final_path = DATA_TORRENT_RECOVERY_V2_CYCLE_2_CORRECTION_FINAL_REVIEW_PATH
    final_payload = _recovery_v2_read_bytes(
        root / final_path,
        repository_root=root,
        maximum_bytes=262_144,
    )
    final_binding = {
        "path": final_path,
        "raw_sha256": hashlib.sha256(final_payload).hexdigest(),
    }
    expected_files = sorted(
        {
            ".github/workflows/ci-safe-v2.yml",
            "configs/agents/mission-activation-matrix-v3.json",
            "docs/operations/DATA-TORRENT-RECOVERY-V2.md",
            *DATA_TORRENT_RECOVERY_V2_CYCLE_2_CORRECTION_REVIEW_PATHS.values(),
            final_path,
            "reports/council/decision-ledger.jsonl",
            "reports/evidence/evidence-graph.json",
            "scripts/check_data_torrent_recovery_v2_scope.py",
            "scripts/materialize_data_torrent_recovery_v2_delivery_evidence.py",
            "src/robin/chronos_production.py",
            "src/robin/recovery_v2_filesystem.py",
            "tests/activation/test_recovery_v2_atomic_evidence.py",
            "tests/council/test_data_torrent_recovery_v2_governance.py",
            "tests/data_torrent/test_ci_lock_contract_v1.py",
            "tests/data_torrent/test_data_torrent_replay_v2.py",
            "tests/data_torrent/test_live_seal_provenance_v2.py",
            "tests/data_torrent/test_postgresql_v1.py",
        }
    )
    expected_release_context = {
        "mission_id": "DATA_TORRENT_RECOVERY_V2",
        "phase": "PR_A_EXACT_HEAD_SAFE_V2_CYCLE_2_CORRECTION_RELEASE_AFTER_INDEPENDENT_QA",
        "program_start_sha": DATA_TORRENT_RECOVERY_V2_START_SHA,
        "writer": "C0",
        "writer_count": 1,
        "worktree": "ENGINEERING_WORKTREE:data-torrent-recovery-v2",
        "branch": "codex/data-torrent-recovery-v2",
        "head": DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_2_HEAD,
        "candidate_parent": DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_2_HEAD,
        "pr": pr_binding,
        "files": expected_files,
        "supersedes_release_claim_id": _RECOVERY_V2_POST_202_B101_CORRECTION_RELEASE_CLAIM,
        "supersedes_release_decision_id": base_release.get("decision_id"),
        "supersedes_release_record_hash": base_release.get("hash"),
        "failure_record_id": failure.get("decision_id"),
        "failure_record_hash": failure.get("hash"),
        "manifest": dict(expected_manifest),
        "effect_contract": dict(expected_effect),
        "postgresql_call_graph": dict(expected_call_graph),
        "reviewed_candidate": reviewed_candidate,
        "reviewed_snapshot_sha256": reviewed_candidate["projection_sha256"],
        "runtime_release": runtime_release,
        "failed_cycle": {
            "run_id": DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_2_RUN_ID,
            "head_sha": DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_2_HEAD,
            "evidence_sha256": exact_head_safe_v2_sha256,
            "rerun_authorized": False,
        },
        "redesign_closure": {
            "failure_decision": "FAIL_AND_REDESIGN",
            "return_stage": "E1",
            "design_revision": 2,
            "root_causes_closed": [
                "SAFE_V2_UBUNTU_START_SHA_ABSENT_AFTER_SHALLOW_CHECKOUT",
                "RECOVERY_V2_POSTGRES_SANITIZED_EXCEPTION_EXPECTATION_MISMATCH",
            ],
            "unchanged_third_attempt_authorized": False,
        },
        "corrections": corrections,
        "pre_cycle_3_qa_correction": {
            "mypy_version_family": "2.3",
            "findings": [
                {
                    "finding_id": "RECOVERY_V2_MYPY_TRANSITIVE_SOURCE_ERRORS",
                    "diagnostics_before": 51,
                    "paths": [
                        "src/robin/chronos_production.py",
                        "src/robin/recovery_v2_filesystem.py",
                    ],
                },
                {
                    "finding_id": "RECOVERY_V2_MYPY_MODULE_IDENTITY_COLLISION",
                    "diagnostics_before": 1,
                    "paths": [".github/workflows/ci-safe-v2.yml"],
                },
                {
                    "finding_id": "RECOVERY_V2_MYPY_TEST_EXPORT_ERRORS",
                    "diagnostics_before": 23,
                    "paths": [
                        "tests/data_torrent/test_data_torrent_replay_v2.py",
                        "tests/data_torrent/test_live_seal_provenance_v2.py",
                    ],
                },
            ],
            "resolution": "TYPE_NARROWING_AND_EXPLICIT_MODULE_BOUNDARIES_WITHOUT_RUNTIME_EFFECT_PATH_CHANGE",
        },
        "defects": {"open_p0": 0, "open_p1": 0, "open_p2": 0, "open_threads": 0},
        "release_conditions": {
            "production_effects_authorized_now": False,
            "exact_head_safe_v2_cycle_3_required": True,
            "normal_merge_required": True,
            "postmerge_safe_v2_required": True,
            "immediate_predecessor_required_for_each_stage": True,
        },
        "progression_contract": {
            "council_role": "CONTROL_AND_RECORD_ONLY",
            "progression_mode": "AUTOMATIC_WITHIN_AUTHORIZED_MANIFEST",
            "controller_path": "scripts/dispatch_data_torrent_recovery_v2_stage.py",
            "stage_mapping_bound_to_effect_contract": True,
            "predecessor_attestation_and_semantic_validation_before_effect": True,
            "pr_c_phase_one_stage_finished_record_required": True,
            "pr_c_terminal_decision_record_required": True,
        },
        "ci_cycle_contract": cycle_contract,
        "observed_delivery_effects": delivery_effects,
        "observed_production_effects": production_zero,
        "independent_reviews": reviews,
        "final_review": final_binding,
        "targeted_tests": {
            "ci_lock_contract": "PASS",
            "chronos_postgres_client": "PASS",
            "postgresql_recovery_v2_exact_test": "REQUIRED_IN_CYCLE_3_BOTH_PROFILES",
            "governance_release": "PASS",
            "mypy_2_3_ci_global_216_sources": "PASS",
            "mypy_2_3_postgresql_profile_29_sources": "PASS",
            "mypy_2_3_recovery_v2_strict_15_scripts": "PASS",
            "prior_consolidated_recovery_suite": "331 passed, 4 skipped",
            "ruff_changed_python": "PASS",
            "json_yaml": "PASS",
            "secret_and_local_path_scan": "PASS",
            "full_suite_rerun": "FALSE",
            "unapproved_network_attempts": "0",
        },
        "proofs_reused": [
            f"superseded-release-record:{base_release.get('hash')}",
            f"cycle-2-failure-record:{failure.get('hash')}",
            f"cycle-2-evidence:{exact_head_safe_v2_sha256}",
            f"manifest-raw:{DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256}",
            f"effect-contract-raw:{DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_SHA256}",
        ],
        "external_effects_authorized_now": False,
        "data_torrent_ready": False,
    }
    if (
        release.get("decision_id") != "RCV3-20260831-206"
        or release.get("decision_id")
        != _recovery_v2_next_decision_id(
            cast(str, failure.get("decision_id")), release_date
        )
        or release.get("record_type") != "DECISION"
        or release.get("decision") != "PASS_AND_HOLD"
        or release.get("responsible") != "C0"
        or release.get("dissent") is not None
        or release.get("proposal")
        != (
            "Release the independently reviewed E1 redesign for both cycle-2 root "
            "causes to the third and last exact-head SAFE V2 cycle on one new SHA "
            "while merge, production and every one-shot effect remain held."
        )
        or release.get("objections")
        != [
            "Record 204 remains byte-for-byte preserved and is superseded only by this append-only decision.",
            "Record 205 returns the second similar exact-head failure to E1 before this redesign release.",
            "Cycle 2 is terminal and must never be rerun; cycle 3 requires a distinct exact head.",
            "The Ubuntu history binding and PostgreSQL sanitized-exception contract each have focused regressions.",
            "Pre-cycle-3 QA closed 51 source diagnostics, one module-identity collision and 23 test-export diagnostics under Mypy 2.3 without changing an effect path.",
            "Cycle 3 is the final permitted exact-head CI cycle; every production effect remains dormant.",
        ]
        or release.get("proof")
        != [_RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_CORRECTION_RELEASE_CLAIM]
        or release.get("previous_hash") != failure.get("hash")
        or not _json_exact_equal(release.get("context"), expected_release_context)
        or release_date <= failure_date
        or release_date > observed_now
        or release_date > expires_at
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    reviewed_snapshot = cast(str, reviewed_candidate["projection_sha256"])
    _validate_recovery_v2_agent_reports(
        root,
        bindings=reviews,
        reviewed_snapshot_sha256=reviewed_snapshot,
        review_paths=DATA_TORRENT_RECOVERY_V2_CYCLE_2_CORRECTION_REVIEW_PATHS,
        expected_facts=_recovery_v2_cycle_2_expected_role_facts(
            reviewed_snapshot,
            failure.get("hash"),
        ),
    )
    _validate_recovery_v2_final_review(
        root,
        binding=final_binding,
        relative=final_path,
        reviewed_snapshot_sha256=reviewed_snapshot,
        schema_version="data-torrent-recovery-v2-exact-head-ci-cycle-2-correction-final-review-v3",
        review_paths=DATA_TORRENT_RECOVERY_V2_CYCLE_2_CORRECTION_REVIEW_PATHS,
        reviewed_file_count=len(cast(list[object], reviewed_candidate["files"])),
        reviewed_at_not_after=release_date,
        reviewed_at_not_before=failure_date,
        reviewed_at_must_precede=True,
        expected_external_effects={
            "git_remote_writes": 2,
            "github_writes": 1,
            "neon_gets": 0,
            "neon_mutations": 0,
            "postgresql_production_connections": 0,
            "postgresql_production_writes": 0,
            "r2_gets": 0,
            "r2_puts": 0,
            "official_reads": 0,
            "provider_requests": 0,
            "secret_writes": 0,
        },
        expected_delivery_effects=delivery_effects,
    )
    return release_date


def _validate_recovery_v2_pr_b_release(
    record: dict[str, Any],
    *,
    root: Path,
    base_release: dict[str, Any],
    base_release_claim: str,
    base_release_date: datetime,
    observed_now: datetime,
    expected_manifest: Mapping[str, str],
    expected_effect: Mapping[str, str],
    expected_call_graph: Mapping[str, str],
) -> datetime:
    context = record.get("context")
    try:
        record_date = _authority_timestamp(record.get("date"), field="pr_b_council_release_date")
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    reviewed_candidate = data_torrent_recovery_v2_pr_b_reviewed_candidate_projection(root)
    runtime_release = data_torrent_recovery_v2_pr_b_release_projection(root)
    conditional_trigger = context.get("conditional_trigger") if isinstance(context, dict) else None
    trigger_evidence = context.get("trigger_evidence") if isinstance(context, dict) else None
    trigger_hash = context.get("trigger_evidence_sha256") if isinstance(context, dict) else None
    if not isinstance(trigger_evidence, dict):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    pr_a_merge = trigger_evidence.get("pr_a_merge")
    try:
        pr_a_merged_at = _authority_timestamp(
            pr_a_merge.get("merged_at") if isinstance(pr_a_merge, dict) else None,
            field="pr_a_merged_at",
        )
        trigger_observed_at = _authority_timestamp(
            trigger_evidence.get("observed_at"),
            field="pr_b_trigger_observed_at",
        )
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    if (
        not isinstance(pr_a_merge, dict)
        or set(pr_a_merge)
        != {
            "role",
            "number",
            "head_ref",
            "head_sha",
            "base_ref",
            "merged_at",
            "state",
            "merge_commit_sha",
            "merge_method",
            "first_parent_sha",
            "second_parent_sha",
            "merge_commit_subject",
            "merge_commit_body",
        }
        or pr_a_merge.get("role") != "PR_A"
        or type(pr_a_merge.get("number")) is not int
        or cast(int, pr_a_merge["number"]) <= 0
        or pr_a_merge.get("head_ref") != "codex/data-torrent-recovery-v2"
        or not isinstance(pr_a_merge.get("head_sha"), str)
        or _HEX_40.fullmatch(cast(str, pr_a_merge["head_sha"])) is None
        or pr_a_merge.get("base_ref") != "main"
        or pr_a_merge.get("state") != "MERGED"
        or not isinstance(pr_a_merge.get("merge_commit_sha"), str)
        or _HEX_40.fullmatch(cast(str, pr_a_merge["merge_commit_sha"])) is None
        or pr_a_merge.get("merge_method") != "MERGE_COMMIT"
        or pr_a_merge.get("first_parent_sha") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or pr_a_merge.get("second_parent_sha") != pr_a_merge.get("head_sha")
        or pr_a_merge.get("merge_commit_subject")
        != "[DATA_TORRENT_RECOVERY_V2] PR-A"
        or pr_a_merge.get("merge_commit_body") != ""
        or not base_release_date <= pr_a_merged_at <= trigger_observed_at <= record_date
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    pr_a_runtime_main_sha = cast(str, pr_a_merge["merge_commit_sha"])
    pr_a_scope_guard = trigger_evidence.get("pr_a_scope_guard")
    pr_a_scope_guard_binding = trigger_evidence.get("pr_a_scope_guard_binding")
    topology = (
        pr_a_scope_guard.get("candidate_topology")
        if isinstance(pr_a_scope_guard, dict)
        else None
    )
    expected_parent = DATA_TORRENT_RECOVERY_V2_START_SHA
    topology_valid = isinstance(topology, list) and bool(topology)
    if topology_valid:
        for item in cast(list[object], topology):
            if (
                not isinstance(item, dict)
                or set(item)
                != {
                    "sha",
                    "parent_sha",
                    "subject",
                    "changed_paths_sha256",
                    "changed_path_count",
                }
                or item.get("parent_sha") != expected_parent
                or not isinstance(item.get("sha"), str)
                or _HEX_40.fullmatch(cast(str, item["sha"])) is None
                or not isinstance(item.get("subject"), str)
                or not cast(str, item["subject"]).strip()
                or not isinstance(item.get("changed_paths_sha256"), str)
                or _HEX_64.fullmatch(cast(str, item["changed_paths_sha256"])) is None
                or type(item.get("changed_path_count")) is not int
                or cast(int, item["changed_path_count"]) <= 0
            ):
                topology_valid = False
                break
            expected_parent = cast(str, item["sha"])
    if not isinstance(pr_a_scope_guard, dict):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    scope_raw = (
        json.dumps(
            pr_a_scope_guard,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    if (
        set(pr_a_scope_guard)
        != {
            "schema_version",
            "start_sha",
            "phase",
            "event_label",
            "base_sha",
            "head_sha",
            "allowed_paths_sha256",
            "phase_allowed_paths_sha256",
            "changed_paths_sha256",
            "changed_path_count",
            "phase_changed_paths_sha256",
            "phase_changed_path_count",
            "history_changed_paths_sha256",
            "history_changed_path_count",
            "phase_history_changed_paths_sha256",
            "phase_history_changed_path_count",
            "candidate_tip_sha",
            "candidate_topology",
            "engineering_chain",
            "merge_first_parent",
            "merge_parent_count",
            "outside_paths",
            "phase_outside_paths",
            "terminal_candidate_complete",
            "verdict",
        }
        or pr_a_scope_guard.get("schema_version")
        != "data-torrent-recovery-v2-scope-guard-v4"
        or pr_a_scope_guard.get("start_sha") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or pr_a_scope_guard.get("phase") != "PR_A"
        or pr_a_scope_guard.get("event_label") != "[DATA_TORRENT_RECOVERY_V2] PR-A"
        or pr_a_scope_guard.get("base_sha") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or pr_a_scope_guard.get("head_sha") != pr_a_runtime_main_sha
        or pr_a_scope_guard.get("allowed_paths_sha256")
        != "47e703278d4ef33bc8fd236d970063dc0832749dcc3ea3b15e58ee9cb532a460"
        or pr_a_scope_guard.get("phase_allowed_paths_sha256")
        != "482652675444b1c84c3ccbf608da1cbf4bebe8bcd05b9dfb584cc371a278d0eb"
        or any(
            not isinstance(pr_a_scope_guard.get(field), str)
            or _HEX_64.fullmatch(cast(str, pr_a_scope_guard[field])) is None
            for field in (
                "changed_paths_sha256",
                "phase_changed_paths_sha256",
                "history_changed_paths_sha256",
                "phase_history_changed_paths_sha256",
            )
        )
        or any(
            type(pr_a_scope_guard.get(field)) is not int
            or cast(int, pr_a_scope_guard[field]) <= 0
            for field in (
                "changed_path_count",
                "phase_changed_path_count",
                "history_changed_path_count",
                "phase_history_changed_path_count",
            )
        )
        or not topology_valid
        or expected_parent != pr_a_merge.get("head_sha")
        or pr_a_scope_guard.get("candidate_tip_sha") != pr_a_merge.get("head_sha")
        or pr_a_scope_guard.get("engineering_chain") != []
        or pr_a_scope_guard.get("merge_first_parent")
        != DATA_TORRENT_RECOVERY_V2_START_SHA
        or pr_a_scope_guard.get("merge_parent_count") != 2
        or pr_a_scope_guard.get("outside_paths") != []
        or pr_a_scope_guard.get("phase_outside_paths") != []
        or pr_a_scope_guard.get("terminal_candidate_complete") is not True
        or pr_a_scope_guard.get("verdict") != "SCOPE_GUARD_PASS"
        or pr_a_scope_guard_binding
        != {
            "raw_sha256": hashlib.sha256(scope_raw).hexdigest(),
            "canonical_sha256": hashlib.sha256(
                canonical_json_bytes(pr_a_scope_guard)
            ).hexdigest(),
        }
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    affected_paths = trigger_evidence.get("affected_paths")
    if (
        not isinstance(affected_paths, list)
        or not affected_paths
        or any(not isinstance(path, str) for path in affected_paths)
        or affected_paths != sorted(set(cast(list[str], affected_paths)))
        or any(
            path not in DATA_TORRENT_RECOVERY_V2_RELEASE_PATHS
            or path in DATA_TORRENT_RECOVERY_V2_RELEASE_EXCLUDED_PATHS
            or path.startswith("reports/council/data-torrent-recovery-v2-")
            or path.startswith(f"{DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR}/")
            or path == "configs/execution/data-torrent-recovery-v2.json"
            for path in affected_paths
        )
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    expected_pr_b_files = sorted(
        {
            *cast(list[str], affected_paths),
            *DATA_TORRENT_RECOVERY_V2_PR_B_REVIEW_PATHS.values(),
            DATA_TORRENT_RECOVERY_V2_PR_B_FINAL_REVIEW_PATH,
            "reports/council/decision-ledger.jsonl",
            "reports/evidence/evidence-graph.json",
        }
    )
    computed_trigger_hash = hashlib.sha256(
        json.dumps(
            trigger_evidence,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    trigger_valid = False
    if conditional_trigger == "SAFE_V2_POSTMERGE_CONSEQUENTIAL_DEFECT":
        trigger_valid = (
            set(trigger_evidence)
            == {
                "workflow_path",
                "run_id",
                "run_attempt",
                "status",
                "event",
                "ref",
                "head_sha",
                "main_sha_at_observation",
                "conclusion",
                "scope_guard_job_id",
                "scope_guard_conclusion",
                "defect_class",
                "affected_paths",
                "observed_at",
                "pr_a_merge",
                "pr_a_scope_guard",
                "pr_a_scope_guard_binding",
                "production_runtime_effects_started",
            }
            and trigger_evidence.get("workflow_path") == ".github/workflows/ci-safe-v2.yml"
            and type(trigger_evidence.get("run_id")) is int
            and cast(int, trigger_evidence["run_id"]) > 0
            and type(trigger_evidence.get("run_attempt")) is int
            and trigger_evidence.get("run_attempt") == 1
            and trigger_evidence.get("status") == "completed"
            and trigger_evidence.get("event") == "push"
            and trigger_evidence.get("ref") == "refs/heads/main"
            and trigger_evidence.get("head_sha") == pr_a_runtime_main_sha
            and trigger_evidence.get("main_sha_at_observation") == pr_a_runtime_main_sha
            and trigger_evidence.get("conclusion") == "failure"
            and type(trigger_evidence.get("scope_guard_job_id")) is int
            and cast(int, trigger_evidence["scope_guard_job_id"]) > 0
            and trigger_evidence.get("scope_guard_conclusion") == "success"
            and trigger_evidence.get("defect_class") == "DIRECTLY_CONSEQUENTIAL_A_B_C"
            and trigger_evidence.get("production_runtime_effects_started") is False
        )
    elif conditional_trigger == "MATERIAL_RUNTIME_GUARD_CONTRACT_DEFECT":
        trigger_valid = (
            set(trigger_evidence)
            == {
                "failing_test",
                "affected_paths",
                "defect_class",
                "observed_at",
                "pr_a_merge",
                "pr_a_scope_guard",
                "pr_a_scope_guard_binding",
                "production_runtime_effects_started",
            }
            and isinstance(trigger_evidence.get("failing_test"), str)
            and bool(cast(str, trigger_evidence["failing_test"]).strip())
            and isinstance(affected_paths, list)
            and bool(affected_paths)
            and all(
                isinstance(path, str) and path in DATA_TORRENT_RECOVERY_V2_RELEASE_PATHS
                for path in affected_paths
            )
            and affected_paths == sorted(set(cast(list[str], affected_paths)))
            and trigger_evidence.get("defect_class")
            == "MATERIAL_RUNTIME_GUARD_OR_CONTRACT"
            and trigger_evidence.get("production_runtime_effects_started") is False
        )
    observed_external_effects = context.get("observed_external_effects") if isinstance(context, dict) else None
    safe_v2_runs = (
        observed_external_effects.get("github_safe_v2_runs")
        if isinstance(observed_external_effects, dict)
        else None
    )
    safe_v2_cycles = (
        safe_v2_runs.get("pr_a_exact_head_cycles") if isinstance(safe_v2_runs, dict) else None
    )
    expected_observed_external_effects = {
        "engineering_pull_requests": 1,
        "git_remote_writes": 1,
        "github_merges": 1,
        "github_safe_v2_runs": {
            "pr_a_exact_head_cycles": safe_v2_cycles,
            "pr_a_postmerge_runs": 1,
            "total": safe_v2_cycles + 1
            if type(safe_v2_cycles) is int
            else -1,
            "run_attempts_above_one": 0,
            "failed_run_reruns": 0,
            "historical_ci_runs": 0,
        },
        "neon_gets": 0,
        "neon_mutations": 0,
        "postgresql_production_connections": 0,
        "postgresql_production_writes": 0,
        "r2_gets": 0,
        "r2_puts": 0,
        "official_reads": 0,
        "provider_requests": 0,
        "secret_writes": 0,  # nosec B105
    }
    if (
        record.get("decision_id")
        != _recovery_v2_next_decision_id(cast(str, base_release["decision_id"]), record_date)
        or record.get("record_type") != "DECISION"
        or record.get("decision") != "PASS_AND_HOLD"
        or record.get("responsible") != "C0"
        or record.get("dissent") is not None
        or record.get("objections") != []
        or record.get("proof") != [_RECOVERY_V2_PR_B_RELEASE_CLAIM]
        or record.get("previous_hash") != base_release.get("hash")
        or not isinstance(record.get("proposal"), str)
        or not cast(str, record["proposal"]).strip()
        or not isinstance(context, dict)
        or set(context)
        != {
            "mission_id",
            "phase",
            "program_start_sha",
            "writer",
            "writer_count",
            "worktree",
            "branch",
            "head",
            "pr",
            "files",
            "targeted_tests",
            "proofs_reused",
            "pr_a_runtime_main_sha",
            "conditional_trigger",
            "trigger_evidence",
            "trigger_evidence_sha256",
            "production_runtime_effects_started",
            "supersedes_release_claim_id",
            "supersedes_release_decision_id",
            "supersedes_release_record_hash",
            "manifest",
            "effect_contract",
            "postgresql_call_graph",
            "reviewed_candidate",
            "reviewed_snapshot_sha256",
            "runtime_release",
            "defects",
            "release_conditions",
            "progression_contract",
            "observed_external_effects",
            "independent_reviews",
            "final_review",
        }
        or context.get("mission_id") != "DATA_TORRENT_RECOVERY_V2"
        or context.get("phase") != "PR_B_CORRECTION_RELEASE_AFTER_INDEPENDENT_QA"
        or context.get("program_start_sha") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or context.get("writer") != "C0"
        or type(context.get("writer_count")) is not int
        or context.get("writer_count") != 1
        or context.get("worktree") != "ENGINEERING_WORKTREE:data-torrent-recovery-v2"
        or context.get("branch") != "codex/data-torrent-recovery-v2"
        or context.get("head") != pr_a_runtime_main_sha
        or context.get("pr") != "PR_B_PENDING"
        or context.get("files") != expected_pr_b_files
        or context.get("targeted_tests")
        != {
            "conditional_trigger_reproduction": "PASS",
            "independent_qa": "PASS",
            "pr_b_corrective_tests": "PASS",
            "scope_guard_pr_b": "PASS",
        }
        or context.get("proofs_reused")
        != [
            f"base-release-record:{base_release.get('hash')}",
            f"pr-a-runtime-main:{pr_a_runtime_main_sha}",
            f"pr-a-scope-guard:{cast(dict[str, str], pr_a_scope_guard_binding)['raw_sha256']}",
            f"pr-b-trigger:{computed_trigger_hash}",
        ]
        or context.get("pr_a_runtime_main_sha") != pr_a_runtime_main_sha
        or not trigger_valid
        or trigger_hash != computed_trigger_hash
        or context.get("production_runtime_effects_started") is not False
        or context.get("supersedes_release_claim_id") != base_release_claim
        or context.get("supersedes_release_decision_id") != base_release.get("decision_id")
        or context.get("supersedes_release_record_hash") != base_release.get("hash")
        or context.get("manifest") != dict(expected_manifest)
        or context.get("effect_contract") != dict(expected_effect)
        or context.get("postgresql_call_graph") != dict(expected_call_graph)
        or context.get("reviewed_candidate") != reviewed_candidate
        or context.get("reviewed_snapshot_sha256") != reviewed_candidate["projection_sha256"]
        or context.get("runtime_release") != runtime_release
        or not isinstance(context.get("defects"), dict)
        or not _exact_integer_fields(
            cast(dict[str, object], context["defects"]),
            {"open_p0", "open_p1", "open_p2", "open_threads"},
        )
        or context.get("defects")
        != {"open_p0": 0, "open_p1": 0, "open_p2": 0, "open_threads": 0}
        or not _json_exact_equal(
            context.get("release_conditions"),
            {
            "production_effects_authorized_now": False,
            "exact_head_safe_v2_required": True,
            "normal_merge_required": True,
            "postmerge_safe_v2_required": True,
            "immediate_predecessor_required_for_each_stage": True,
            },
        )
        or not _json_exact_equal(
            context.get("progression_contract"),
            {
            "council_role": "CONTROL_AND_RECORD_ONLY",
            "progression_mode": "AUTOMATIC_WITHIN_AUTHORIZED_MANIFEST",
            "controller_path": "scripts/dispatch_data_torrent_recovery_v2_stage.py",
            "stage_mapping_bound_to_effect_contract": True,
            "predecessor_attestation_and_semantic_validation_before_effect": True,
            "pr_c_phase_one_stage_finished_record_required": True,
            "pr_c_terminal_decision_record_required": True,
            },
        )
        or type(safe_v2_cycles) is not int
        or not 1 <= safe_v2_cycles <= 3
        or not isinstance(observed_external_effects, dict)
        or not _exact_integer_fields(
            cast(dict[str, object], observed_external_effects),
            set(expected_observed_external_effects) - {"github_safe_v2_runs"},
        )
        or not isinstance(safe_v2_runs, dict)
        or not _exact_integer_fields(
            cast(dict[str, object], safe_v2_runs),
            {
                "pr_a_exact_head_cycles",
                "pr_a_postmerge_runs",
                "total",
                "run_attempts_above_one",
                "failed_run_reruns",
                "historical_ci_runs",
            },
        )
        or not _json_exact_equal(
            observed_external_effects, expected_observed_external_effects
        )
        or record_date <= base_release_date
        or record_date > observed_now
        or record_date
        > _authority_timestamp(DATA_TORRENT_RECOVERY_V2_EXPIRES_AT, field="recovery_v2_expiry")
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    _validate_recovery_v2_agent_reports(
        root,
        bindings=context.get("independent_reviews"),
        reviewed_snapshot_sha256=cast(str, reviewed_candidate["projection_sha256"]),
        review_paths=DATA_TORRENT_RECOVERY_V2_PR_B_REVIEW_PATHS,
    )
    trigger_ref = f"PR_B_TRIGGER_SHA256:{computed_trigger_hash}"
    for relative in DATA_TORRENT_RECOVERY_V2_PR_B_REVIEW_PATHS.values():
        _review_payload, review = _recovery_v2_strict_json(
            root / relative,
            maximum_bytes=262_144,
            repository_root=root,
        )
        facts = review.get("facts_verified")
        if not isinstance(facts, list) or not any(
            isinstance(fact, dict)
            and isinstance(fact.get("evidence_refs"), list)
            and trigger_ref in fact["evidence_refs"]
            for fact in facts
        ):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    _validate_recovery_v2_final_review(
        root,
        binding=context.get("final_review"),
        relative=DATA_TORRENT_RECOVERY_V2_PR_B_FINAL_REVIEW_PATH,
        reviewed_snapshot_sha256=cast(str, reviewed_candidate["projection_sha256"]),
        schema_version="data-torrent-recovery-v2-pr-b-final-review-v3",
        review_paths=DATA_TORRENT_RECOVERY_V2_PR_B_REVIEW_PATHS,
        reviewed_file_count=len(cast(list[object], reviewed_candidate["files"])),
        reviewed_at_not_after=record_date,
        reviewed_at_not_before=trigger_observed_at,
    )
    return record_date


def _validate_recovery_v2_release_graph(
    root: Path,
    *,
    initial_release: Mapping[str, object],
    base_release: Mapping[str, object],
    local_qa_failure: Mapping[str, object],
    local_correction_release: Mapping[str, object],
    static_qa_failure: Mapping[str, object],
    static_correction_release: Mapping[str, object],
    exact_head_ci_failure: Mapping[str, object],
    exact_head_ci_correction_release: Mapping[str, object],
    post_202_b101_failure: Mapping[str, object],
    post_202_b101_correction_release: Mapping[str, object],
    exact_head_ci_cycle_2_failure: Mapping[str, object],
    exact_head_ci_cycle_2_correction_release: Mapping[str, object],
    active_release: Mapping[str, object],
    active_release_claim: str,
    successors: Sequence[Mapping[str, object]],
) -> None:
    if len(successors) > 3:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    downstream_allowed = bool(successors)
    _payload, graph = _recovery_v2_strict_json(
        root / "reports" / "evidence" / "evidence-graph.json",
        maximum_bytes=16 * 1024 * 1024,
        repository_root=root,
    )
    claims = graph.get("claims")
    nodes = graph.get("decision_nodes")
    edges = graph.get("edges")
    if (
        not isinstance(claims, list)
        or not isinstance(nodes, list)
        or not isinstance(edges, list)
        or any(not isinstance(row, dict) for row in (*claims, *nodes, *edges))
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    typed_claims = cast(list[dict[str, object]], claims)
    typed_nodes = cast(list[dict[str, object]], nodes)
    typed_edges = cast(list[dict[str, object]], edges)

    def canonical_sequence_sha256(rows: list[dict[str, object]]) -> str:
        return hashlib.sha256(
            json.dumps(
                rows,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    if (
        set(graph)
        != {
            "schema_version",
            "generated_at",
            "lineage_policy",
            "claims",
            "decision_nodes",
            "edges",
        }
        or graph.get("schema_version") != "robin-evidence-graph-v1"
        or graph.get("generated_at") != "2026-08-30T19:22:00Z"
        or graph.get("lineage_policy")
        != "execution_id, scientific_lineage_id and dataset_lineage_id are independent"
        or canonical_sequence_sha256(typed_claims[:520])
        != DATA_TORRENT_RECOVERY_V2_GRAPH_CLAIMS_PREFIX_SHA256
        or canonical_sequence_sha256(typed_nodes[:194])
        != DATA_TORRENT_RECOVERY_V2_GRAPH_NODES_PREFIX_SHA256
        or canonical_sequence_sha256(typed_edges[:822])
        != DATA_TORRENT_RECOVERY_V2_GRAPH_EDGES_PREFIX_SHA256
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    claim_ids = [row.get("claim_id") for row in typed_claims]
    decision_ids = [row.get("decision_id") for row in typed_nodes]
    edge_ids = [row.get("edge_id") for row in typed_edges]
    if (
        any(not isinstance(value, str) or not value for value in claim_ids)
        or any(not isinstance(value, str) or not value for value in decision_ids)
        or any(
            not isinstance(value, str)
            or re.fullmatch(r"EDGE\.[0-9]+", value) is None
            for value in edge_ids
        )
        or len(claim_ids) != len(set(claim_ids))
        or len(decision_ids) != len(set(decision_ids))
        or len(edge_ids) != len(set(edge_ids))
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    edge_numbers = [int(cast(str, value).split(".", 1)[1]) for value in edge_ids]
    if (
        any(number <= 0 for number in edge_numbers)
        or any(left >= right for left, right in zip(edge_numbers, edge_numbers[1:]))
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    claim_by_id = {cast(str, row["claim_id"]): row for row in typed_claims}
    initial_claim_id = "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION.RELEASE.001"
    initial_claim = claim_by_id.get(initial_claim_id)
    base_claim = claim_by_id.get(_RECOVERY_V2_BASE_RELEASE_CLAIM)
    failure_claim = claim_by_id.get(_RECOVERY_V2_LOCAL_QA_FAILURE_CLAIM)
    local_claim = claim_by_id.get(_RECOVERY_V2_LOCAL_CORRECTION_RELEASE_CLAIM)
    static_failure_claim = claim_by_id.get(_RECOVERY_V2_STATIC_QA_FAILURE_CLAIM)
    static_release_claim = claim_by_id.get(_RECOVERY_V2_STATIC_CORRECTION_RELEASE_CLAIM)
    exact_head_failure_claim = claim_by_id.get(_RECOVERY_V2_EXACT_HEAD_CI_FAILURE_CLAIM)
    exact_head_release_claim = claim_by_id.get(
        _RECOVERY_V2_EXACT_HEAD_CI_CORRECTION_RELEASE_CLAIM
    )
    post_202_b101_failure_claim = claim_by_id.get(
        _RECOVERY_V2_POST_202_B101_FAILURE_CLAIM
    )
    post_202_b101_release_claim = claim_by_id.get(
        _RECOVERY_V2_POST_202_B101_CORRECTION_RELEASE_CLAIM
    )
    exact_head_cycle_2_failure_claim = claim_by_id.get(
        _RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_FAILURE_CLAIM
    )
    exact_head_cycle_2_release_claim = claim_by_id.get(
        _RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_CORRECTION_RELEASE_CLAIM
    )
    pr_b_claim = claim_by_id.get(_RECOVERY_V2_PR_B_RELEASE_CLAIM)
    if active_release_claim not in {
        _RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_CORRECTION_RELEASE_CLAIM,
        _RECOVERY_V2_PR_B_RELEASE_CLAIM,
    }:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    expected_claim_suffix = [
        _RECOVERY_V2_EXACT_HEAD_CI_CORRECTION_RELEASE_CLAIM,
        _RECOVERY_V2_POST_202_B101_FAILURE_CLAIM,
        _RECOVERY_V2_POST_202_B101_CORRECTION_RELEASE_CLAIM,
        _RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_FAILURE_CLAIM,
        _RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_CORRECTION_RELEASE_CLAIM,
    ]
    expected_node_suffix = [
        DATA_TORRENT_RECOVERY_V2_EXACT_HEAD_CI_RELEASE_ID,
        "RCV3-20260831-203",
        "RCV3-20260831-204",
        "RCV3-20260831-205",
        "RCV3-20260831-206",
    ]
    expected_edge_suffix = [
        "EDGE.824",
        "EDGE.825",
        "EDGE.826",
        "EDGE.827",
    ]
    if active_release_claim == _RECOVERY_V2_PR_B_RELEASE_CLAIM:
        if not isinstance(active_release.get("decision_id"), str):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        expected_claim_suffix.append(_RECOVERY_V2_PR_B_RELEASE_CLAIM)
        expected_node_suffix.append(cast(str, active_release["decision_id"]))
        expected_edge_suffix.append("EDGE.828")
    expected_claim_suffix.extend(
        [
            _RECOVERY_V2_RESERVATION_CLAIM,
            _RECOVERY_V2_PHASE_ONE_CLAIM,
            _RECOVERY_V2_TERMINAL_CLAIM,
        ][: len(successors)]
    )
    successor_ids = [record.get("decision_id") for record in successors]
    if any(not isinstance(decision_id, str) for decision_id in successor_ids):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    expected_node_suffix.extend(cast(list[str], successor_ids))
    next_runtime_edge = 829 if active_release_claim == _RECOVERY_V2_PR_B_RELEASE_CLAIM else 828
    for proof_count in range(2, 2 + len(successors)):
        expected_edge_suffix.extend(
            f"EDGE.{number}"
            for number in range(next_runtime_edge, next_runtime_edge + proof_count)
        )
        next_runtime_edge += proof_count
    claim_end = 520 + len(expected_claim_suffix)
    node_end = 194 + len(expected_node_suffix)
    edge_end = 822 + len(expected_edge_suffix)
    if (
        claim_ids[520:claim_end] != expected_claim_suffix
        or decision_ids[194:node_end] != expected_node_suffix
        or edge_ids[822:edge_end] != expected_edge_suffix
        or claim_end != len(claim_ids)
        or node_end != len(decision_ids)
        or edge_end != len(edge_ids)
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    initial_context = initial_release.get("context")
    base_context = base_release.get("context")
    local_context = local_correction_release.get("context")
    static_context = static_correction_release.get("context")
    exact_head_context = exact_head_ci_correction_release.get("context")
    exact_head_failure_context = exact_head_ci_failure.get("context")
    post_202_b101_context = post_202_b101_correction_release.get("context")
    post_202_b101_failure_context = post_202_b101_failure.get("context")
    exact_head_cycle_2_context = exact_head_ci_cycle_2_correction_release.get("context")
    exact_head_cycle_2_failure_context = exact_head_ci_cycle_2_failure.get("context")
    active_context = active_release.get("context")
    if (
        not isinstance(initial_context, dict)
        or not isinstance(base_context, dict)
        or not isinstance(local_context, dict)
        or not isinstance(static_context, dict)
        or not isinstance(exact_head_context, dict)
        or not isinstance(exact_head_failure_context, dict)
        or not isinstance(post_202_b101_context, dict)
        or not isinstance(post_202_b101_failure_context, dict)
        or not isinstance(exact_head_cycle_2_context, dict)
        or not isinstance(exact_head_cycle_2_failure_context, dict)
        or not isinstance(active_context, dict)
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    initial_review = cast(dict[str, object], initial_context).get("final_review")
    base_review = cast(dict[str, object], base_context).get("final_review")
    local_review = cast(dict[str, object], local_context).get("final_review")
    static_review = cast(dict[str, object], static_context).get("final_review")
    exact_head_review = cast(dict[str, object], exact_head_context).get("final_review")
    post_202_b101_review = cast(dict[str, object], post_202_b101_context).get(
        "final_review"
    )
    exact_head_cycle_2_review = cast(dict[str, object], exact_head_cycle_2_context).get(
        "final_review"
    )
    active_review = cast(dict[str, object], active_context).get("final_review")
    if (
        not isinstance(initial_review, dict)
        or not isinstance(base_review, dict)
        or not isinstance(local_review, dict)
        or not isinstance(static_review, dict)
        or not isinstance(exact_head_review, dict)
        or not isinstance(post_202_b101_review, dict)
        or not isinstance(exact_head_cycle_2_review, dict)
        or not isinstance(active_review, dict)
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")

    def release_claim_valid(
        claim: object,
        *,
        claim_id: str,
        decision: Mapping[str, object],
        review: Mapping[str, object],
        successor_of: str,
        status: str,
        superseded_by: str | None,
    ) -> bool:
        if not isinstance(claim, dict):
            return False
        decision_context = decision.get("context")
        if not isinstance(decision_context, dict):
            return False
        reviewed_candidate = decision_context.get("reviewed_candidate")
        independent_reviews = decision_context.get("independent_reviews")
        if (
            not isinstance(reviewed_candidate, dict)
            or not isinstance(reviewed_candidate.get("files"), list)
            or not isinstance(independent_reviews, dict)
            or any(
                not isinstance(independent_reviews.get(agent_id), dict)
                for agent_id in ("C2", "C4", "DP6", "A2")
            )
        ):
            return False
        expected_claim = (
            "Four independent reviews bind the exact "
            f"{len(cast(list[object], reviewed_candidate['files']))}-file "
            "DATA TORRENT RECOVERY V2 candidate, close the record-to-graph "
            "self-reference with an acyclic runtime projection, verify the "
            "immutable owner manifest and non-fungible effect ceilings, and "
            "release only the implementation to exact-head SAFE V2 while every "
            "production effect remains dormant."
        )
        typed_reviews = cast(dict[str, dict[str, object]], independent_reviews)
        expected_source = (
            "Reviewed candidate SHA-256 "
            f"{reviewed_candidate.get('projection_sha256')}; "
            f"C2 report SHA-256 {typed_reviews['C2'].get('raw_sha256')}; "
            f"C4 report SHA-256 {typed_reviews['C4'].get('raw_sha256')}; "
            f"DP6 report SHA-256 {typed_reviews['DP6'].get('raw_sha256')}; "
            f"A2 report SHA-256 {typed_reviews['A2'].get('raw_sha256')}; "
            f"final review SHA-256 {review.get('raw_sha256')}"
        )
        expected_fields = {
            "claim_id",
            "claim",
            "scope",
            "source",
            "grain",
            "temporal_class",
            "artifact",
            "hash",
            "code_revision",
            "execution_id",
            "scientific_lineage_id",
            "dataset_lineage_id",
            "status",
            "verified_by",
            "successor_of",
        }
        if superseded_by is not None:
            expected_fields.add("superseded_by")
        return (
            set(claim) == expected_fields
            and claim.get("claim_id") == claim_id
            and claim.get("claim") == expected_claim
            and claim.get("scope")
            == "DATA_TORRENT_RECOVERY_V2_E1_IMPLEMENTATION_RELEASE_AFTER_INDEPENDENT_QA"
            and claim.get("source") == expected_source
            and claim.get("grain")
            == "ONE_FROZEN_IMPLEMENTATION_CANDIDATE_TO_FOUR_INDEPENDENT_REVIEWS_AND_ONE_RELEASE_DECISION"
            and claim.get("temporal_class") == "DECISION_AS_OF"
            and claim.get("artifact") == review.get("path")
            and claim.get("hash") == review.get("raw_sha256")
            and claim.get("code_revision") == decision_context.get("head")
            and isinstance(decision_context.get("head"), str)
            and _HEX_40.fullmatch(cast(str, decision_context["head"])) is not None
            and claim.get("execution_id") == f"council-record:{decision.get('decision_id')}"
            and claim.get("scientific_lineage_id") == "DATA_TORRENT_RECOVERY_V2"
            and claim.get("dataset_lineage_id") == "NO_DATASET_IMPLEMENTATION_RELEASE"
            and claim.get("status") == status
            and claim.get("verified_by") == ["C0", "C2", "C4", "DP6", "A2"]
            and claim.get("successor_of") == successor_of
            and claim.get("superseded_by") == superseded_by
        )

    if not release_claim_valid(
        initial_claim,
        claim_id=initial_claim_id,
        decision=initial_release,
        review=cast(dict[str, object], initial_review),
        successor_of="GOV.AUTHORIZATION.DATA_TORRENT_RECOVERY.V2.MANIFEST.001",
        status="SUPERSEDED",
        superseded_by=_RECOVERY_V2_BASE_RELEASE_CLAIM,
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    base_successor = initial_claim_id
    if not release_claim_valid(
        base_claim,
        claim_id=_RECOVERY_V2_BASE_RELEASE_CLAIM,
        decision=base_release,
        review=cast(dict[str, object], base_review),
        successor_of=base_successor,
        status="SUPERSEDED",
        superseded_by=_RECOVERY_V2_LOCAL_CORRECTION_RELEASE_CLAIM,
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    expected_failure_claim = {
        "claim_id": _RECOVERY_V2_LOCAL_QA_FAILURE_CLAIM,
        "claim": (
            "The post-196 targeted governance run failed in one stale terminal-helper "
            "fan-out affecting 29 tests; all external effects remained zero"
        ),
        "scope": "DATA_TORRENT_RECOVERY_V2_POST_196_LOCAL_QA_FAILURE",
        "source": (
            "pytest -q tests/council/test_data_torrent_recovery_v2_governance.py: "
            "29 failed, 130 passed in 20.15s"
        ),
        "grain": "ONE_STALE_HELPER_ROOT_CAUSE_TO_29_TARGETED_TEST_FAILURES",
        "temporal_class": "DECISION_AS_OF",
        "artifact": "tests/council/test_data_torrent_recovery_v2_governance.py",
        "hash": "d8de152fd92a64eec2cf92a876d4f2292fe60bc4d006a8eb7d9c20bb8b5371bb",
        "code_revision": DATA_TORRENT_RECOVERY_V2_START_SHA,
        "execution_id": f"council-record:{local_qa_failure.get('decision_id')}",
        "scientific_lineage_id": "DATA_TORRENT_RECOVERY_V2",
        "dataset_lineage_id": "NO_DATASET_LOCAL_QA_FAILURE",
        "status": "VERIFIED",
        "verified_by": ["C0", "C2", "C4"],
        "successor_of": _RECOVERY_V2_BASE_RELEASE_CLAIM,
    }
    if failure_claim != expected_failure_claim:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    if not release_claim_valid(
        local_claim,
        claim_id=_RECOVERY_V2_LOCAL_CORRECTION_RELEASE_CLAIM,
        decision=local_correction_release,
        review=cast(dict[str, object], local_review),
        successor_of=_RECOVERY_V2_LOCAL_QA_FAILURE_CLAIM,
        status="SUPERSEDED",
        superseded_by=_RECOVERY_V2_STATIC_CORRECTION_RELEASE_CLAIM,
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    expected_static_failure_claim = {
        "claim_id": _RECOVERY_V2_STATIC_QA_FAILURE_CLAIM,
        "claim": (
            "The post-198 pre-commit review found nine Bandit B105 false positives and "
            "eight bounded operability and delivery defects across R3-to-R5, R4, E1, "
            "and merge CAS; all external "
            "effects remained zero"
        ),
        "scope": "DATA_TORRENT_RECOVERY_V2_POST_198_PRECOMMIT_STATIC_RUNTIME_QA_FAILURE",
        "source": (
            "Bandit Recovery V2 scope: 9 low-severity B105 findings; independent "
            "operability and delivery review: R3-to-R5 handoff=2, R4 schedule=1, "
            "E1 deadlines=2, local prerequisite ordering=2, merge CAS=1"
        ),
        "grain": "ONE_POST_198_REVIEW_TO_SEVENTEEN_STATIC_RUNTIME_AND_DELIVERY_FINDINGS",
        "temporal_class": "DECISION_AS_OF",
        "artifact": "scripts/install_chronos_runtime_bindings_v2.py",
        "hash": "db54cfa8b188d667abe0b642b499babe11efe3b345ab5515fc6880d577684b48",
        "code_revision": DATA_TORRENT_RECOVERY_V2_START_SHA,
        "execution_id": f"council-record:{static_qa_failure.get('decision_id')}",
        "scientific_lineage_id": "DATA_TORRENT_RECOVERY_V2",
        "dataset_lineage_id": "NO_DATASET_LOCAL_STATIC_RUNTIME_QA_FAILURE",
        "status": "VERIFIED",
        "verified_by": ["C0", "C2", "C4", "DP6", "A2"],
        "successor_of": _RECOVERY_V2_LOCAL_CORRECTION_RELEASE_CLAIM,
    }
    if static_failure_claim != expected_static_failure_claim:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    if not release_claim_valid(
        static_release_claim,
        claim_id=_RECOVERY_V2_STATIC_CORRECTION_RELEASE_CLAIM,
        decision=static_correction_release,
        review=cast(dict[str, object], static_review),
        successor_of=_RECOVERY_V2_STATIC_QA_FAILURE_CLAIM,
        status="SUPERSEDED",
        superseded_by=_RECOVERY_V2_EXACT_HEAD_CI_CORRECTION_RELEASE_CLAIM,
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    expected_exact_head_failure_claim = {
        "claim_id": _RECOVERY_V2_EXACT_HEAD_CI_FAILURE_CLAIM,
        "claim": (
            "Exact-head SAFE V2 cycle 1 failed in five root jobs that reduce to three "
            "local causes; its dependent tests failure adds no fourth cause and every "
            "production effect remained zero"
        ),
        "scope": "DATA_TORRENT_RECOVERY_V2_PR_A_EXACT_HEAD_SAFE_V2_CYCLE_1_FAILURE",
        "source": (
            "GitHub Actions run 33420499802; attempt 1; head "
            "a0a043f3222e467e6d904c90878be5718cac8ace; completed "
            "2026-08-31T17:50:55Z; conclusion failure"
        ),
        "grain": "ONE_TERMINAL_EXACT_HEAD_CI_ATTEMPT_TO_THREE_ROOT_CAUSES",
        "temporal_class": "DECISION_AS_OF",
        "artifact": (
            "https://github.com/dddur75/robin-stades-ng/actions/runs/33420499802"
        ),
        "hash": exact_head_failure_context.get("exact_head_safe_v2_sha256"),
        "code_revision": DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_1_HEAD,
        "execution_id": f"council-record:{exact_head_ci_failure.get('decision_id')}",
        "scientific_lineage_id": "DATA_TORRENT_RECOVERY_V2",
        "dataset_lineage_id": "NO_DATASET_EXACT_HEAD_SAFE_V2_CYCLE_1_FAILURE",
        "status": "VERIFIED",
        "verified_by": ["C0", "CI_SAFE_V2", "C2", "C4", "DP6", "A2"],
        "successor_of": _RECOVERY_V2_STATIC_CORRECTION_RELEASE_CLAIM,
    }
    if exact_head_failure_claim != expected_exact_head_failure_claim:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    if not release_claim_valid(
        exact_head_release_claim,
        claim_id=_RECOVERY_V2_EXACT_HEAD_CI_CORRECTION_RELEASE_CLAIM,
        decision=exact_head_ci_correction_release,
        review=cast(dict[str, object], exact_head_review),
        successor_of=_RECOVERY_V2_EXACT_HEAD_CI_FAILURE_CLAIM,
        status="SUPERSEDED",
        superseded_by=_RECOVERY_V2_POST_202_B101_CORRECTION_RELEASE_CLAIM,
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    expected_post_202_b101_failure_claim = {
        "claim_id": _RECOVERY_V2_POST_202_B101_FAILURE_CLAIM,
        "claim": (
            "A post-202 whole-src Bandit preflight found one B101 assertion in the "
            "POSIX exclusive-publication rollback path, a failure class distinct from "
            "record 199; cycle 2 and every production effect remained held"
        ),
        "scope": "DATA_TORRENT_RECOVERY_V2_POST_202_PRE_CYCLE_2_B101_FAILURE",
        "source": (
            "bandit -q -r src/robin; B101; vulnerable LF SHA-256 "
            "d770f9fbcac097161b4be909a289e5dddd7884d2ac9015ce3185acbf6e4ace60; "
            "record 199 hash 25eb2b9c2fbc10fb54525bb646d35c6cf0003e14e4445cf40248125b55befb75"
        ),
        "grain": "ONE_POST_202_STATIC_PREFLIGHT_FINDING_TO_ONE_FAIL_CLOSED_CORRECTION",
        "temporal_class": "DECISION_AS_OF",
        "artifact": "src/robin/recovery_v2_filesystem.py",
        "hash": "d770f9fbcac097161b4be909a289e5dddd7884d2ac9015ce3185acbf6e4ace60",
        "code_revision": DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_1_HEAD,
        "execution_id": f"council-record:{post_202_b101_failure.get('decision_id')}",
        "scientific_lineage_id": "DATA_TORRENT_RECOVERY_V2",
        "dataset_lineage_id": "NO_DATASET_POST_202_B101_PREFLIGHT_FAILURE",
        "status": "VERIFIED",
        "verified_by": ["C0", "C4", "A2"],
        "successor_of": _RECOVERY_V2_EXACT_HEAD_CI_CORRECTION_RELEASE_CLAIM,
    }
    if post_202_b101_failure_claim != expected_post_202_b101_failure_claim:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    if not release_claim_valid(
        post_202_b101_release_claim,
        claim_id=_RECOVERY_V2_POST_202_B101_CORRECTION_RELEASE_CLAIM,
        decision=post_202_b101_correction_release,
        review=cast(dict[str, object], post_202_b101_review),
        successor_of=_RECOVERY_V2_POST_202_B101_FAILURE_CLAIM,
        status="SUPERSEDED",
        superseded_by=_RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_CORRECTION_RELEASE_CLAIM,
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    expected_exact_head_cycle_2_failure_claim = {
        "claim_id": _RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_FAILURE_CLAIM,
        "claim": (
            "Exact-head SAFE V2 cycle 2 failed in three root jobs that reduce to two "
            "local causes; its dependent tests failure adds no third cause and every "
            "production effect remained zero"
        ),
        "scope": "DATA_TORRENT_RECOVERY_V2_PR_A_EXACT_HEAD_SAFE_V2_CYCLE_2_FAILURE",
        "source": (
            "GitHub Actions run 33433893502; attempt 1; head "
            "21d6a928c5998cca86cebbb0dc078aba4cd20cb5; completed "
            "2026-08-31T20:16:10Z; conclusion failure"
        ),
        "grain": "ONE_TERMINAL_EXACT_HEAD_CI_ATTEMPT_TO_TWO_ROOT_CAUSES",
        "temporal_class": "DECISION_AS_OF",
        "artifact": "https://github.com/dddur75/robin-stades-ng/actions/runs/33433893502",
        "hash": exact_head_cycle_2_failure_context.get("exact_head_safe_v2_sha256"),
        "code_revision": DATA_TORRENT_RECOVERY_V2_PR_A_CYCLE_2_HEAD,
        "execution_id": f"council-record:{exact_head_ci_cycle_2_failure.get('decision_id')}",
        "scientific_lineage_id": "DATA_TORRENT_RECOVERY_V2",
        "dataset_lineage_id": "NO_DATASET_EXACT_HEAD_SAFE_V2_CYCLE_2_FAILURE",
        "status": "VERIFIED",
        "verified_by": ["C0", "CI_SAFE_V2", "C2", "C4", "DP6", "A2"],
        "successor_of": _RECOVERY_V2_POST_202_B101_CORRECTION_RELEASE_CLAIM,
    }
    if exact_head_cycle_2_failure_claim != expected_exact_head_cycle_2_failure_claim:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    cycle_2_release_status = (
        "VERIFIED"
        if active_release_claim
        == _RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_CORRECTION_RELEASE_CLAIM
        else "SUPERSEDED"
    )
    if not release_claim_valid(
        exact_head_cycle_2_release_claim,
        claim_id=_RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_CORRECTION_RELEASE_CLAIM,
        decision=exact_head_ci_cycle_2_correction_release,
        review=cast(dict[str, object], exact_head_cycle_2_review),
        successor_of=_RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_FAILURE_CLAIM,
        status=cycle_2_release_status,
        superseded_by=(
            None
            if active_release_claim
            == _RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_CORRECTION_RELEASE_CLAIM
            else _RECOVERY_V2_PR_B_RELEASE_CLAIM
        ),
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    if active_release_claim == _RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_CORRECTION_RELEASE_CLAIM:
        if pr_b_claim is not None:
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    elif active_release_claim != _RECOVERY_V2_PR_B_RELEASE_CLAIM or not release_claim_valid(
        pr_b_claim,
        claim_id=_RECOVERY_V2_PR_B_RELEASE_CLAIM,
        decision=active_release,
        review=cast(dict[str, object], active_review),
        successor_of=_RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_CORRECTION_RELEASE_CLAIM,
        status="VERIFIED",
        superseded_by=None,
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    fixed_edge_ids = {
        (
            "RCV3-20260830-193",
            "GOV.AUTHORIZATION.DATA_TORRENT_RECOVERY.V2.MANIFEST.001",
        ): "EDGE.812",
        (
            "RCV3-20260830-193",
            "GOV.COUNCIL.DATA_TORRENT_READY.EVIDENCE.SUCCESSION.LEDGER.V1.009",
        ): "EDGE.813",
        ("RCV3-20260830-194", initial_claim_id): "EDGE.814",
        ("RCV3-20260830-195", initial_claim_id): "EDGE.816",
        (
            DATA_TORRENT_RECOVERY_V2_BASE_RELEASE_ID,
            _RECOVERY_V2_BASE_RELEASE_CLAIM,
        ): "EDGE.817",
        (
            "RCV3-20260831-197",
            _RECOVERY_V2_LOCAL_QA_FAILURE_CLAIM,
        ): "EDGE.818",
        (
            "RCV3-20260831-198",
            _RECOVERY_V2_LOCAL_CORRECTION_RELEASE_CLAIM,
        ): "EDGE.819",
        (
            "RCV3-20260831-199",
            _RECOVERY_V2_STATIC_QA_FAILURE_CLAIM,
        ): "EDGE.820",
        (
            "RCV3-20260831-200",
            _RECOVERY_V2_STATIC_CORRECTION_RELEASE_CLAIM,
        ): "EDGE.821",
        (
            "RCV3-20260831-201",
            _RECOVERY_V2_EXACT_HEAD_CI_FAILURE_CLAIM,
        ): "EDGE.822",
        (
            "RCV3-20260831-202",
            _RECOVERY_V2_EXACT_HEAD_CI_CORRECTION_RELEASE_CLAIM,
        ): "EDGE.823",
        (
            "RCV3-20260831-203",
            _RECOVERY_V2_POST_202_B101_FAILURE_CLAIM,
        ): "EDGE.824",
        (
            "RCV3-20260831-204",
            _RECOVERY_V2_POST_202_B101_CORRECTION_RELEASE_CLAIM,
        ): "EDGE.825",
        (
            "RCV3-20260831-205",
            _RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_FAILURE_CLAIM,
        ): "EDGE.826",
        (
            "RCV3-20260831-206",
            _RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_CORRECTION_RELEASE_CLAIM,
        ): "EDGE.827",
    }
    if active_release_claim == _RECOVERY_V2_PR_B_RELEASE_CLAIM:
        fixed_edge_ids[
            (
                cast(str, active_release.get("decision_id")),
                _RECOVERY_V2_PR_B_RELEASE_CLAIM,
            )
        ] = "EDGE.828"
    for (decision_id, claim_id), edge_id in fixed_edge_ids.items():
        if [
            edge
            for edge in typed_edges
            if edge.get("to_decision_id") == decision_id
            and edge.get("from_claim_id") == claim_id
        ] != [
            {
                "edge_id": edge_id,
                "from_claim_id": claim_id,
                "to_decision_id": decision_id,
                "relation": "SUPPORTS",
                "status": "RECORDED",
            }
        ]:
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    release_decisions = [
        initial_release,
        base_release,
        local_qa_failure,
        local_correction_release,
        static_qa_failure,
        static_correction_release,
        exact_head_ci_failure,
        exact_head_ci_correction_release,
        post_202_b101_failure,
        post_202_b101_correction_release,
        exact_head_ci_cycle_2_failure,
        exact_head_ci_cycle_2_correction_release,
    ]
    release_proofs = [
        initial_claim_id,
        _RECOVERY_V2_BASE_RELEASE_CLAIM,
        _RECOVERY_V2_LOCAL_QA_FAILURE_CLAIM,
        _RECOVERY_V2_LOCAL_CORRECTION_RELEASE_CLAIM,
        _RECOVERY_V2_STATIC_QA_FAILURE_CLAIM,
        _RECOVERY_V2_STATIC_CORRECTION_RELEASE_CLAIM,
        _RECOVERY_V2_EXACT_HEAD_CI_FAILURE_CLAIM,
        _RECOVERY_V2_EXACT_HEAD_CI_CORRECTION_RELEASE_CLAIM,
        _RECOVERY_V2_POST_202_B101_FAILURE_CLAIM,
        _RECOVERY_V2_POST_202_B101_CORRECTION_RELEASE_CLAIM,
        _RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_FAILURE_CLAIM,
        _RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_CORRECTION_RELEASE_CLAIM,
    ]
    if active_release_claim == _RECOVERY_V2_PR_B_RELEASE_CLAIM:
        release_decisions.append(active_release)
        release_proofs.append(_RECOVERY_V2_PR_B_RELEASE_CLAIM)
    for decision, proof in zip(release_decisions, release_proofs, strict=True):
        matching_nodes = [
            row for row in typed_nodes if row.get("decision_id") == decision.get("decision_id")
        ]
        matching_edges = [
            row for row in typed_edges if row.get("to_decision_id") == decision.get("decision_id")
        ]
        if (
            matching_nodes
            != [
                {
                    "decision_id": decision.get("decision_id"),
                    "ledger_record_hash": decision.get("hash"),
                }
            ]
            or len(matching_edges) != 1
            or matching_edges[0].get("from_claim_id") != proof
            or not _recovery_v2_successor_edges_are_canonical(
                typed_edges, matching_edges, [proof]
            )
            or set(matching_edges[0])
            != {"edge_id", "from_claim_id", "to_decision_id", "relation", "status"}
            or matching_edges[0].get("relation") != "SUPPORTS"
            or matching_edges[0].get("status") != "RECORDED"
        ):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    correction_decision_ids = {
        base_release.get("decision_id"),
        local_qa_failure.get("decision_id"),
        local_correction_release.get("decision_id"),
        static_qa_failure.get("decision_id"),
        static_correction_release.get("decision_id"),
        exact_head_ci_failure.get("decision_id"),
        exact_head_ci_correction_release.get("decision_id"),
        post_202_b101_failure.get("decision_id"),
        post_202_b101_correction_release.get("decision_id"),
        exact_head_ci_cycle_2_failure.get("decision_id"),
        exact_head_ci_cycle_2_correction_release.get("decision_id"),
    }
    correction_proofs = [
        _RECOVERY_V2_BASE_RELEASE_CLAIM,
        _RECOVERY_V2_LOCAL_QA_FAILURE_CLAIM,
        _RECOVERY_V2_LOCAL_CORRECTION_RELEASE_CLAIM,
        _RECOVERY_V2_STATIC_QA_FAILURE_CLAIM,
        _RECOVERY_V2_STATIC_CORRECTION_RELEASE_CLAIM,
        _RECOVERY_V2_EXACT_HEAD_CI_FAILURE_CLAIM,
        _RECOVERY_V2_EXACT_HEAD_CI_CORRECTION_RELEASE_CLAIM,
        _RECOVERY_V2_POST_202_B101_FAILURE_CLAIM,
        _RECOVERY_V2_POST_202_B101_CORRECTION_RELEASE_CLAIM,
        _RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_FAILURE_CLAIM,
        _RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_CORRECTION_RELEASE_CLAIM,
    ]
    if active_release_claim == _RECOVERY_V2_PR_B_RELEASE_CLAIM:
        correction_decision_ids.add(active_release.get("decision_id"))
        correction_proofs.append(_RECOVERY_V2_PR_B_RELEASE_CLAIM)
    correction_edges = [
        edge
        for edge in typed_edges
        if edge.get("to_decision_id") in correction_decision_ids
    ]
    if not _recovery_v2_successor_edges_are_canonical(
        typed_edges,
        correction_edges,
        correction_proofs,
        require_tail=not downstream_allowed,
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")


def _validate_recovery_v2_council_successors(
    successors: list[dict[str, Any]],
    *,
    root: Path,
    release_id: str,
    release_hash: str,
    release_claim: str,
    release_date: datetime,
    observed_now: datetime,
    closure_phase: str,
) -> str:
    if closure_phase == "PRE_RUNTIME":
        if successors:
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        return release_hash
    expected_successors = {"RESERVATION": 1, "PHASE_ONE": 2, "TERMINAL": 3}
    if (
        closure_phase not in expected_successors
        or len(successors) != expected_successors[closure_phase]
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    reservation_record = successors[0]
    reservation_date, reservation_runtime_main_sha, _live_run_id, _engineering_numbers = (
        _validate_recovery_v2_reservation_record(
            reservation_record,
            root=root,
            release_id=release_id,
            release_hash=release_hash,
            release_claim=release_claim,
            release_date=release_date,
            observed_now=observed_now,
        )
    )
    _validate_recovery_v2_reservation_graph(
        root,
        record=reservation_record,
        release_claim=release_claim,
        downstream_allowed=closure_phase != "RESERVATION",
    )
    if closure_phase == "RESERVATION":
        return str(reservation_record["hash"])
    phase_one_record = successors[1]
    phase_one_date, phase_one_runtime_main_sha, phase_one_projection = (
        _validate_recovery_v2_phase_one_record(
            phase_one_record,
            root=root,
            release_id=release_id,
            release_hash=release_hash,
            release_claim=release_claim,
            reservation_record=reservation_record,
            reservation_date=reservation_date,
            observed_now=observed_now,
        )
    )
    if phase_one_runtime_main_sha != reservation_runtime_main_sha:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    _validate_recovery_v2_phase_one_graph(
        root,
        record=phase_one_record,
        release_claim=release_claim,
        terminal_allowed=closure_phase == "TERMINAL",
    )
    if closure_phase == "PHASE_ONE":
        return str(phase_one_record["hash"])
    record = successors[2]
    context = record.get("context")
    try:
        record_date = _authority_timestamp(record.get("date"), field="terminal_council_date")
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    expected_terminal_id = _recovery_v2_next_decision_id(
        str(phase_one_record["decision_id"]), record_date
    )
    terminal_proofs = (
        release_claim,
        _RECOVERY_V2_RESERVATION_CLAIM,
        _RECOVERY_V2_PHASE_ONE_CLAIM,
        _RECOVERY_V2_TERMINAL_CLAIM,
    )
    expires_at = _authority_timestamp(
        DATA_TORRENT_RECOVERY_V2_EXPIRES_AT,
        field="recovery_v2_expiry",
    )
    expected_postmerge_final_gate = data_torrent_recovery_v2_postmerge_final_gate_contract(
        root
    )
    expected_postmerge_final_gate_sha256 = hashlib.sha256(
        canonical_json_bytes(expected_postmerge_final_gate)
    ).hexdigest()
    expected_closure_files = sorted(
        {
            DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_EVIDENCE_PATH,
            DATA_TORRENT_RECOVERY_V2_DELIVERY_EVIDENCE_PATH,
            *DATA_TORRENT_RECOVERY_V2_TERMINAL_REVIEW_PATHS.values(),
            DATA_TORRENT_RECOVERY_V2_TERMINAL_REPORT_PATH,
            "reports/council/decision-ledger.jsonl",
            "reports/evidence/evidence-graph.json",
        }
    )
    if (
        record.get("decision_id") != expected_terminal_id
        or record.get("record_type") != "DECISION"
        or record.get("decision") != "PASS_AND_HOLD"
        or record.get("responsible") != "C0"
        or record.get("dissent") is not None
        or record.get("objections") != []
        or record.get("proof") != list(terminal_proofs)
        or record.get("proposal")
        != (
            "Record the Recovery V2 PR-C terminal candidate pending merge and "
            "postmerge SAFE V2."
        )
        or not isinstance(context, dict)
        or set(context)
        != {
            "mission_id",
            "program_start_sha",
            "release_decision_id",
            "release_record_hash",
            "active_release_claim_id",
            "reservation_decision_id",
            "reservation_record_hash",
            "phase_one_decision_id",
            "phase_one_record_hash",
            "phase_one_projection_sha256",
            "scale_stage",
            "phase",
            "writer",
            "worktree",
            "branch",
            "head",
            "pr",
            "files",
            "targeted_tests",
            "proofs_reused",
            "terminal_report",
            "postmerge_final_gate_contract_sha256",
            "data_torrent_ready",
            "runtime_main_sha",
        }
        or context.get("mission_id") != "DATA_TORRENT_RECOVERY_V2"
        or context.get("program_start_sha") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or context.get("release_decision_id") != release_id
        or context.get("release_record_hash") != release_hash
        or context.get("active_release_claim_id") != release_claim
        or context.get("reservation_decision_id") != reservation_record.get("decision_id")
        or context.get("reservation_record_hash") != reservation_record.get("hash")
        or context.get("phase_one_decision_id") != phase_one_record.get("decision_id")
        or context.get("phase_one_record_hash") != phase_one_record.get("hash")
        or context.get("phase_one_projection_sha256")
        != phase_one_projection.get("projection_sha256")
        or context.get("scale_stage") != "E4"
        or context.get("phase") != "TERMINAL_EVIDENCE_PR_C"
        or context.get("writer") != "C0"
        or context.get("worktree") != "ENGINEERING_WORKTREE:data-torrent-recovery-v2"
        or context.get("branch") != "codex/data-torrent-recovery-v2"
        or not isinstance(context.get("head"), str)
        or _HEX_40.fullmatch(cast(str, context["head"])) is None
        or context.get("files") != expected_closure_files
        or context.get("targeted_tests")
        != {
            "scope_guard_pr_c_c2": "PASS",
            "terminal_independent_qa": "PASS",
            "terminal_runtime_semantics": "PASS",
        }
        or context.get("data_torrent_ready") is not False
        or context.get("postmerge_final_gate_contract_sha256")
        != expected_postmerge_final_gate_sha256
        or not isinstance(context.get("runtime_main_sha"), str)
        or _HEX_40.fullmatch(cast(str, context["runtime_main_sha"])) is None
        or not isinstance(context.get("terminal_report"), dict)
        or set(cast(dict[str, object], context["terminal_report"])) != {"path", "raw_sha256"}
        or cast(dict[str, object], context["terminal_report"]).get("path")
        != DATA_TORRENT_RECOVERY_V2_TERMINAL_REPORT_PATH
        or not isinstance(
            cast(dict[str, object], context["terminal_report"]).get("raw_sha256"), str
        )
        or _HEX_64.fullmatch(
            cast(str, cast(dict[str, object], context["terminal_report"])["raw_sha256"])
        )
        is None
        or context.get("runtime_main_sha") != phase_one_runtime_main_sha
        or record.get("previous_hash") != phase_one_record.get("hash")
        or record_date <= phase_one_date
        or record_date > observed_now
        or record_date > expires_at
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    terminal_binding = cast(dict[str, object], context["terminal_report"])
    terminal_relative = cast(str, terminal_binding["path"])
    terminal_payload, terminal_report = _recovery_v2_strict_json(
        root / terminal_relative,
        maximum_bytes=2 * 1024 * 1024,
        repository_root=root,
    )
    terminal_hash = hashlib.sha256(terminal_payload).hexdigest()
    if (
        terminal_binding["raw_sha256"] != terminal_hash
        or set(terminal_report)
        != {
            "schema_version",
            "report_role",
            "mission_id",
            "program_start_sha",
            "runtime_main_sha",
            "generated_at",
            "duration_seconds",
            "mission_complete",
            "data_torrent_ready",
            "final_verdict",
            "completion_states",
            "delivery",
            "runtime_postmerge_safe_v2",
            "postmerge_final_gate",
            "provider_neutralization",
            "postmerge_quarantine",
            "runtime_stages",
            "production_state",
            "data_metrics",
            "terminal_artifacts",
            "qa",
            "effect_counters",
            "all_run_ids",
            "all_artifact_ids",
            "all_payload_sha256",
            "all_archive_sha256",
            "runtime_close_quiescence",
            "global_quiescence",
            "worktree_status",
            "reviewed_runtime_snapshot_sha256",
            "independent_reviews",
        }
        or terminal_report.get("schema_version") != "data-torrent-recovery-v2-terminal-report-v1"
        or terminal_report.get("report_role") != "CANDIDATE_NOT_TERMINAL"
        or terminal_report.get("mission_id") != "DATA_TORRENT_RECOVERY_V2"
        or terminal_report.get("program_start_sha") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or not isinstance(terminal_report.get("runtime_main_sha"), str)
        or _HEX_40.fullmatch(cast(str, terminal_report["runtime_main_sha"])) is None
        or terminal_report.get("runtime_main_sha") != context.get("runtime_main_sha")
        or type(terminal_report.get("duration_seconds")) is not int
        or not 1 <= cast(int, terminal_report["duration_seconds"]) <= 604_800
        or terminal_report.get("mission_complete") is not False
        or terminal_report.get("data_torrent_ready") is not False
        or terminal_report.get("final_verdict") != "PASS_AND_HOLD"
        or terminal_report.get("global_quiescence") is not False
        or terminal_report.get("worktree_status")
        != "PENDING_C2_COMMIT_AND_EPHEMERAL_CLEANUP"
        or not isinstance(terminal_report.get("reviewed_runtime_snapshot_sha256"), str)
        or _HEX_64.fullmatch(cast(str, terminal_report["reviewed_runtime_snapshot_sha256"])) is None
        or any(
            not isinstance(terminal_report.get(field), dict)
            for field in (
                "runtime_postmerge_safe_v2",
                "postmerge_final_gate",
                "provider_neutralization",
                "postmerge_quarantine",
                "runtime_stages",
                "completion_states",
                "delivery",
                "production_state",
                "data_metrics",
                "qa",
                "effect_counters",
                "runtime_close_quiescence",
            )
        )
        or any(
            not isinstance(terminal_report.get(field), list)
            for field in (
                "all_run_ids",
                "all_artifact_ids",
                "all_payload_sha256",
                "all_archive_sha256",
            )
        )
        or not isinstance(terminal_report.get("terminal_artifacts"), list)
        or len(cast(list[object], terminal_report["terminal_artifacts"])) != 19
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    runtime_main_sha = cast(str, terminal_report["runtime_main_sha"])
    completion_states = cast(dict[str, object], terminal_report["completion_states"])
    delivery = cast(dict[str, object], terminal_report["delivery"])
    runtime_postmerge_safe = cast(
        dict[str, object], terminal_report["runtime_postmerge_safe_v2"]
    )
    postmerge_final_gate = cast(dict[str, object], terminal_report["postmerge_final_gate"])
    provider = cast(dict[str, object], terminal_report["provider_neutralization"])
    quarantine = cast(dict[str, object], terminal_report["postmerge_quarantine"])
    runtime_stages = cast(dict[str, object], terminal_report["runtime_stages"])
    production_state = cast(dict[str, object], terminal_report["production_state"])
    data_metrics = cast(dict[str, object], terminal_report["data_metrics"])
    qa = cast(dict[str, object], terminal_report["qa"])
    effect_counters = cast(dict[str, object], terminal_report["effect_counters"])
    artifacts = cast(list[object], terminal_report["terminal_artifacts"])
    live_attestation_payload, live_attestation, live_artifact_payloads = (
        _recovery_v2_terminal_live_bundle(root, runtime_main_sha=runtime_main_sha)
    )
    live_semantics = _recovery_v2_terminal_live_semantics(
        live_artifact_payloads,
        repository_root=root,
    )
    stage_evidence = _recovery_v2_terminal_stage_evidence(
        root,
        runtime_main_sha=runtime_main_sha,
        live_attestation=live_attestation,
        live_artifact_payloads=live_artifact_payloads,
        live_semantics=live_semantics,
    )
    quiescence_payload, quiescence = _recovery_v2_terminal_quiescence(
        root,
        runtime_main_sha=runtime_main_sha,
        live_attestation_payload=live_attestation_payload,
        live_attestation=live_attestation,
    )
    delivery_reservation_payload, delivery_evidence_payload, derived_delivery = (
        _recovery_v2_terminal_delivery(root, runtime_main_sha=runtime_main_sha)
    )
    quiescence_worktree = quiescence.get("worktree")
    if (
        quiescence.get("production_workflows_quiescent_at_runtime_close") is not True
        or quiescence.get("global_queue_empty_at_runtime_close") is not True
        or not isinstance(quiescence_worktree, dict)
        or quiescence_worktree.get("tracked_status") != "CLEAN"
        or quiescence_worktree.get("unexpected_nonignored_untracked_paths") != []
        or quiescence_worktree.get("ephemeral_release_paths_exact") is not True
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    if not _json_exact_equal(
        terminal_report["runtime_close_quiescence"],
        {
            "path": DATA_TORRENT_RECOVERY_V2_FINAL_QUIESCENCE_PATH,
            "raw_sha256": hashlib.sha256(quiescence_payload).hexdigest(),
        },
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    if not _json_exact_equal(runtime_stages, stage_evidence["runtime_stages"]):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    if not _json_exact_equal(delivery, derived_delivery):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    if (
        not _json_exact_equal(provider, stage_evidence["provider_neutralization"])
        or not _json_exact_equal(quarantine, stage_evidence["postmerge_quarantine"])
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    exact_head_safe = delivery.get("exact_head_safe_v2")
    pr_a = delivery.get("pr_a")
    pr_b = delivery.get("pr_b")
    pr_c = delivery.get("pr_c")

    def merged_engineering_pr(value: object) -> dict[str, object] | None:
        if not isinstance(value, dict):
            return None
        result = cast(dict[str, object], value)
        if (
            set(result)
            != {"number", "head_sha", "merge_commit_sha", "state", "merge_method", "base_ref"}
            or type(result.get("number")) is not int
            or cast(int, result["number"]) <= 0
            or not isinstance(result.get("head_sha"), str)
            or _HEX_40.fullmatch(cast(str, result["head_sha"])) is None
            or not isinstance(result.get("merge_commit_sha"), str)
            or _HEX_40.fullmatch(cast(str, result["merge_commit_sha"])) is None
            or result.get("state") != "MERGED"
            or result.get("merge_method") != "MERGE_COMMIT"
            or result.get("base_ref") != "main"
        ):
            return None
        return result

    pr_a_proof = merged_engineering_pr(pr_a)
    pr_b_proof = None if pr_b == "NOT_OPENED" else merged_engineering_pr(pr_b)
    active_engineering_pr = pr_b_proof or pr_a_proof
    if (
        set(completion_states) != set(_RECOVERY_V2_TERMINAL_COMPLETION_STATES)
        or any(
            completion_states[field] is not (field != "data_torrent_ready")
            for field in completion_states
        )
        or set(delivery)
        != {
            "pr_a",
            "pr_b",
            "pr_c",
            "pr_c_phase_one_head_sha",
            "pr_c_phase_one_safe_v2",
            "pr_c_reservation_parent_sha",
            "engineering_pr_merged",
            "exact_head_safe_v2",
            "final_main_sha",
            "final_main_sha_definition",
            "evidence",
        }
        or pr_a_proof is None
        or (pr_b != "NOT_OPENED" and pr_b_proof is None)
        or type(pr_c) is not int
        or pr_c <= 0
        or len(
            {
                cast(int, pr_a_proof["number"]),
                *(
                    [cast(int, pr_b_proof["number"])]
                    if pr_b_proof is not None
                    else []
                ),
                pr_c,
            }
        )
        != (3 if pr_b_proof is not None else 2)
        or delivery.get("engineering_pr_merged") is not True
        or delivery.get("pr_c_phase_one_head_sha") != context.get("head")
        or delivery.get("pr_c_reservation_parent_sha")
        != cast(dict[str, object], quiescence["reservation"])["reservation_commit_sha"]
        or active_engineering_pr is None
        or active_engineering_pr.get("merge_commit_sha") != runtime_main_sha
        or delivery.get("final_main_sha") is not None
        or delivery.get("final_main_sha_definition")
        != "PENDING_PR_C_MERGE_AND_POSTMERGE_SAFE"
        or not isinstance(exact_head_safe, dict)
        or set(exact_head_safe)
        != {
            "workflow_path",
            "run_id",
            "run_attempt",
            "head_sha",
            "conclusion",
            "scope_guard_job_id",
            "scope_guard_conclusion",
        }
        or exact_head_safe.get("workflow_path") != ".github/workflows/ci-safe-v2.yml"
        or type(exact_head_safe.get("run_id")) is not int
        or cast(int, exact_head_safe["run_id"]) <= 0
        or type(exact_head_safe.get("run_attempt")) is not int
        or exact_head_safe.get("run_attempt") != 1
        or exact_head_safe.get("head_sha") != active_engineering_pr.get("head_sha")
        or exact_head_safe.get("conclusion") != "success"
        or type(exact_head_safe.get("scope_guard_job_id")) is not int
        or cast(int, exact_head_safe["scope_guard_job_id"]) <= 0
        or exact_head_safe.get("scope_guard_conclusion") != "success"
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    if (
        not isinstance(quiescence.get("full_hold"), dict)
        or not isinstance(cast(dict[str, Any], quiescence["full_hold"]).get("post_merge_ci"), dict)
        or not isinstance(
            cast(dict[str, Any], quiescence["full_hold"]).get("recovery_v2_scope_guard"),
            dict,
        )
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    terminal_hold = cast(dict[str, Any], quiescence["full_hold"])
    terminal_hold_ci = cast(dict[str, Any], terminal_hold["post_merge_ci"])
    terminal_hold_scope = cast(dict[str, Any], terminal_hold["recovery_v2_scope_guard"])
    expected_runtime_postmerge_safe = {
        "workflow_path": terminal_hold_ci["workflow_path"],
        "run_id": terminal_hold_ci["run_id"],
        "run_attempt": terminal_hold_ci["run_attempt"],
        "head_sha": terminal_hold_ci["head_sha"],
        "conclusion": terminal_hold_ci["conclusion"],
        "scope_guard_job_id": terminal_hold_scope["job_id"],
        "scope_guard_conclusion": terminal_hold_scope["conclusion"],
    }
    if (
        not _json_exact_equal(runtime_postmerge_safe, expected_runtime_postmerge_safe)
        or set(runtime_postmerge_safe)
        != {
            "workflow_path",
            "run_id",
            "run_attempt",
            "head_sha",
            "conclusion",
            "scope_guard_job_id",
            "scope_guard_conclusion",
        }
        or runtime_postmerge_safe.get("workflow_path")
        != ".github/workflows/ci-safe-v2.yml"
        or type(runtime_postmerge_safe.get("run_id")) is not int
        or cast(int, runtime_postmerge_safe["run_id"]) <= 0
        or type(runtime_postmerge_safe.get("run_attempt")) is not int
        or runtime_postmerge_safe.get("run_attempt") != 1
        or runtime_postmerge_safe.get("head_sha") != runtime_main_sha
        or runtime_postmerge_safe.get("conclusion") != "success"
        or type(runtime_postmerge_safe.get("scope_guard_job_id")) is not int
        or cast(int, runtime_postmerge_safe["scope_guard_job_id"]) <= 0
        or runtime_postmerge_safe.get("scope_guard_conclusion") != "success"
        or not _json_exact_equal(postmerge_final_gate, expected_postmerge_final_gate)
        or set(provider)
        != {
            "receipt_path",
            "receipt_sha256",
            "verdict",
            "required_current_sha",
            "target_main_sha",
            "push_mode",
            "push_attempts",
            "remote_ref_observations",
            "non_fast_forward_updates",
            "branch_deletes",
            "automatic_retries",
        }
        or provider.get("receipt_path") != DATA_TORRENT_RECOVERY_V2_PROVIDER_EVIDENCE_PATH
        or provider.get("verdict") != "LEGACY_PROVIDER_BRANCH_NEUTRALIZED"
        or provider.get("required_current_sha") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or provider.get("target_main_sha") != runtime_main_sha
        or provider.get("push_mode") != "ORDINARY_NON_FORCE_FAST_FORWARD"
        or not _exact_integer_fields(
            provider,
            {
                "push_attempts",
                "remote_ref_observations",
                "non_fast_forward_updates",
                "branch_deletes",
                "automatic_retries",
            },
        )
        or provider.get("push_attempts") != 1
        or provider.get("remote_ref_observations") != 2
        or provider.get("non_fast_forward_updates") != 0
        or provider.get("branch_deletes") != 0
        or provider.get("automatic_retries") != 0
        or not isinstance(provider.get("receipt_sha256"), str)
        or _HEX_64.fullmatch(cast(str, provider["receipt_sha256"])) is None
        or set(quarantine)
        != {
            "receipt_path",
            "receipt_sha256",
            "verdict",
            "automatic_retries",
            "workflows_dormant",
            "global_queue_empty",
        }
        or quarantine.get("receipt_path") != DATA_TORRENT_RECOVERY_V2_QUARANTINE_EVIDENCE_PATH
        or quarantine.get("verdict") != "POSTMERGE_QUARANTINE_CONFIRMED"
        or type(quarantine.get("automatic_retries")) is not int
        or quarantine.get("automatic_retries") != 0
        or quarantine.get("workflows_dormant") is not True
        or quarantine.get("global_queue_empty") is not True
        or not isinstance(quarantine.get("receipt_sha256"), str)
        or _HEX_64.fullmatch(cast(str, quarantine["receipt_sha256"])) is None
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")

    if set(runtime_stages) != {
        *_RECOVERY_V2_TERMINAL_WORKFLOW_STAGES,
        "FOUR_RUNTIME_BINDINGS",
        "REPLAY_100",
    }:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    observed_run_ids: list[int] = []
    observed_artifact_ids: list[int] = []
    stage_effects: dict[str, dict[str, int]] = {}
    workflow_proof_fields = {
        "run_id",
        "run_attempt",
        "workflow_path",
        "head_sha",
        "artifact_id",
        "payload_sha256",
        "payload_filename",
        "archive_sha256",
        "semantic_verdict",
        "effect_counters",
    }
    for stage, (
        workflow_path,
        semantic_verdict,
        payload_filename,
    ) in _RECOVERY_V2_TERMINAL_WORKFLOW_STAGES.items():
        proof = runtime_stages.get(stage)
        if not isinstance(proof, dict):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        run_id = proof.get("run_id")
        artifact_id = proof.get("artifact_id")
        if (
            set(proof) != workflow_proof_fields
            or type(run_id) is not int
            or run_id <= 0
            or type(proof.get("run_attempt")) is not int
            or proof.get("run_attempt") != 1
            or proof.get("workflow_path") != workflow_path
            or proof.get("payload_filename") != payload_filename
            or proof.get("head_sha") != runtime_main_sha
            or type(artifact_id) is not int
            or artifact_id <= 0
            or proof.get("semantic_verdict") != semantic_verdict
            or not isinstance(proof.get("payload_sha256"), str)
            or _HEX_64.fullmatch(cast(str, proof["payload_sha256"])) is None
            or not isinstance(proof.get("archive_sha256"), str)
            or _HEX_64.fullmatch(cast(str, proof["archive_sha256"])) is None
            or not isinstance(proof.get("effect_counters"), dict)
        ):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        stage_effects[stage] = _recovery_v2_terminal_stage_effects(proof["effect_counters"])
        observed_run_ids.append(run_id)
        observed_artifact_ids.append(artifact_id)
    if len(observed_run_ids) != len(set(observed_run_ids)) or len(observed_artifact_ids) != len(
        set(observed_artifact_ids)
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    bindings = runtime_stages["FOUR_RUNTIME_BINDINGS"]
    replay = runtime_stages["REPLAY_100"]
    if (
        not isinstance(bindings, dict)
        or set(bindings)
        != workflow_proof_fields
        | {
            "artifact_relation",
            "carrier_payload_sha256",
            "runtime_bindings_receipt_path",
            "runtime_bindings_receipt_sha256",
            "secret_writes",
        }
        or bindings.get("artifact_relation")
        != "EXACT_RECEIPT_BOUND_BY_MIGRATE_CONTROLLER_INPUT_AND_SIGNED_OBJECT"
        or bindings.get("carrier_payload_sha256")
        != cast(dict[str, Any], runtime_stages["MIGRATE_0015"])["payload_sha256"]
        or bindings.get("runtime_bindings_receipt_path")
        != DATA_TORRENT_RECOVERY_V2_BINDINGS_EVIDENCE_PATH
        or bindings.get("semantic_verdict") != "FOUR_RUNTIME_BINDINGS_INSTALLED_V2"
        or bindings.get("secret_writes") != 4
        or type(bindings.get("run_id")) is not int
        or cast(int, bindings["run_id"]) <= 0
        or type(bindings.get("run_attempt")) is not int
        or bindings.get("run_attempt") != 1
        or type(bindings.get("artifact_id")) is not int
        or cast(int, bindings["artifact_id"]) <= 0
        or not isinstance(bindings.get("runtime_bindings_receipt_sha256"), str)
        or _HEX_64.fullmatch(cast(str, bindings["runtime_bindings_receipt_sha256"])) is None
        or not isinstance(bindings.get("effect_counters"), dict)
        or not isinstance(replay, dict)
        or set(replay)
        != workflow_proof_fields
        | {
            "parent_stage",
            "iterations_exact",
            "equivalent_records",
            "external_effects",
            "output_sha256",
            "records_per_second",
            "p95_latency_ms",
            "peak_memory_bytes",
            "idempotent",
        }
        or replay.get("parent_stage") != "LIVE_ONCE"
        or replay.get("iterations_exact") != 100
        or type(replay.get("run_id")) is not int
        or cast(int, replay["run_id"]) <= 0
        or type(replay.get("run_attempt")) is not int
        or replay.get("run_attempt") != 1
        or type(replay.get("artifact_id")) is not int
        or cast(int, replay["artifact_id"]) <= 0
        or type(replay.get("equivalent_records")) is not int
        or cast(int, replay["equivalent_records"]) <= 0
        or type(replay.get("external_effects")) is not int
        or replay.get("external_effects") != 0
        or replay.get("semantic_verdict") != "REPLAY_100_COMPLETE"
        or replay.get("idempotent") is not True
        or not isinstance(replay.get("output_sha256"), str)
        or _HEX_64.fullmatch(cast(str, replay["output_sha256"])) is None
        or replay.get("payload_filename") != "torrent-load-replay-report-v1.json"
        or not isinstance(replay.get("payload_sha256"), str)
        or _HEX_64.fullmatch(cast(str, replay["payload_sha256"])) is None
        or type(replay.get("records_per_second")) not in {int, float}
        or cast(float, replay["records_per_second"]) <= 0
        or type(replay.get("p95_latency_ms")) not in {int, float}
        or cast(float, replay["p95_latency_ms"]) < 0
        or type(replay.get("peak_memory_bytes")) is not int
        or cast(int, replay["peak_memory_bytes"]) <= 0
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")

    stage_effects["FOUR_RUNTIME_BINDINGS"] = _recovery_v2_terminal_stage_effects(
        cast(dict[str, object], bindings)["effect_counters"]
    )
    stage_effects["REPLAY_100"] = _recovery_v2_terminal_stage_effects(replay.get("effect_counters"))
    live_effects = stage_effects["LIVE_ONCE"]
    expected_bindings = [
        "CHRONOS_AUTHORITY_DATABASE_URL",
        "CHRONOS_RUNTIME_DATABASE_URL",
        "CHRONOS_READER_DATABASE_URL",
        "CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
    ]
    if (
        set(production_state)
        != {
            "production_database_revision",
            "chronos_opportunity_claim_active",
            "runtime_bindings_present",
            "binding_writes",
        }
        or production_state.get("production_database_revision") != "0015_data_torrent_opportunity"
        or production_state.get("chronos_opportunity_claim_active") is not True
        or production_state.get("runtime_bindings_present") != expected_bindings
        or production_state.get("binding_writes") != 4
        or set(data_metrics)
        != {
            "leagues_enabled",
            "leagues_with_real_data",
            "fixtures_captured",
            "markets_requested",
            "markets_returned",
            "league_market_cells",
            "league_market_cells_non_empty",
            "official_physical_reads",
            "odds_provider_requests",
            "odds_credits_used",
            "raw_responses",
            "raw_bytes",
            "normalized_records",
            "rejected_records",
            "rejected_records_reason_coded",
            "silent_drops",
            "logical_duplicates",
            "temporal_leakage",
            "canonical_dataset_sha256",
            "raw_durable",
            "normalized_durable",
            "lineage_complete",
            "missed_windows",
        }
        or data_metrics.get("leagues_enabled") != 5
        or data_metrics.get("leagues_with_real_data") != 5
        or type(data_metrics.get("fixtures_captured")) is not int
        or cast(int, data_metrics["fixtures_captured"]) <= 0
        or data_metrics.get("markets_requested") != ["h2h", "totals"]
        or data_metrics.get("markets_returned") != ["h2h", "totals"]
        or data_metrics.get("league_market_cells") != 10
        or data_metrics.get("league_market_cells_non_empty") is not True
        or data_metrics.get("official_physical_reads") != live_effects["official_reads"]
        or data_metrics.get("odds_provider_requests") != live_effects["provider_requests"]
        or data_metrics.get("odds_credits_used") != live_effects["provider_credits"]
        or any(
            type(data_metrics.get(field)) is not int or cast(int, data_metrics[field]) <= 0
            for field in ("raw_responses", "raw_bytes", "normalized_records")
        )
        or type(data_metrics.get("rejected_records")) is not int
        or cast(int, data_metrics["rejected_records"]) < 0
        or data_metrics.get("rejected_records_reason_coded") is not True
        or not _exact_integer_fields(
            data_metrics,
            {"silent_drops", "logical_duplicates", "temporal_leakage"},
        )
        or any(
            data_metrics.get(field) != 0
            for field in ("silent_drops", "logical_duplicates", "temporal_leakage")
        )
        or not isinstance(data_metrics.get("canonical_dataset_sha256"), str)
        or _HEX_64.fullmatch(cast(str, data_metrics["canonical_dataset_sha256"])) is None
        or any(
            data_metrics.get(field) is not True
            for field in ("raw_durable", "normalized_durable", "lineage_complete")
        )
        or data_metrics.get("missed_windows") != "MISSED_NOT_BACKDATED"
        or replay.get("equivalent_records") != cast(int, data_metrics["normalized_records"]) * 100
        or not _json_exact_equal(production_state, stage_evidence["production_state"])
        or not _json_exact_equal(data_metrics, live_semantics["data_metrics"])
        or not _json_exact_equal(qa, live_semantics["qa"])
        or not _json_exact_equal(
            stage_effects["LIVE_ONCE"], live_semantics["live_effects"]
        )
        or not _json_exact_equal(
            stage_effects["REPLAY_100"], live_semantics["replay_effects"]
        )
        or not _json_exact_equal(
            {
                field: replay.get(field)
                for field in (
                "iterations_exact",
                "equivalent_records",
                "external_effects",
                "output_sha256",
                "payload_filename",
                "payload_sha256",
                "records_per_second",
                "p95_latency_ms",
                "peak_memory_bytes",
                "idempotent",
                )
            },
            live_semantics["replay"],
        )
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")

    if (
        any(not isinstance(item, dict) for item in artifacts)
        or tuple(cast(dict[str, object], item).get("name") for item in artifacts)
        != _RECOVERY_V2_TERMINAL_ARTIFACT_NAMES
        or any(
            set(cast(dict[str, object], item))
            != {"name", "artifact_id", "payload_sha256", "archive_sha256"}
            or type(cast(dict[str, object], item).get("artifact_id")) is not int
            or cast(int, cast(dict[str, object], item)["artifact_id"]) <= 0
            or cast(dict[str, object], item).get("artifact_id")
            != live_attestation["artifact_id"]
            or not isinstance(cast(dict[str, object], item).get("payload_sha256"), str)
            or _HEX_64.fullmatch(cast(str, cast(dict[str, object], item)["payload_sha256"])) is None
            or cast(dict[str, object], item).get("payload_sha256")
            != hashlib.sha256(
                live_artifact_payloads[cast(str, cast(dict[str, object], item)["name"])]
            ).hexdigest()
            or not isinstance(cast(dict[str, object], item).get("archive_sha256"), str)
            or _HEX_64.fullmatch(cast(str, cast(dict[str, object], item)["archive_sha256"])) is None
            or cast(dict[str, object], item).get("archive_sha256")
            != live_attestation["archive_sha256"]
            for item in artifacts
        )
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    artifact_documents = [cast(dict[str, object], item) for item in artifacts]
    live_proof = cast(dict[str, object], runtime_stages["LIVE_ONCE"])
    if (
        live_proof["run_id"] != int(cast(str, live_attestation["run_id"]))
        or live_proof["run_attempt"] != 1
        or live_proof["workflow_path"] != live_attestation["workflow_path"]
        or live_proof["head_sha"] != live_attestation["head_sha"]
        or live_proof["artifact_id"] != live_attestation["artifact_id"]
        or live_proof["archive_sha256"] != live_attestation["archive_sha256"]
        or live_proof["payload_filename"] != "torrent-real-batch-manifest-v1.json"
        or live_proof["payload_sha256"] != artifact_documents[0]["payload_sha256"]
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    evidence_run_ids = [
        cast(int, exact_head_safe["run_id"]),
        cast(
            int,
            cast(dict[str, object], delivery["pr_c_phase_one_safe_v2"])["run_id"],
        ),
        cast(int, runtime_postmerge_safe["run_id"]),
        *observed_run_ids,
    ]
    if len(evidence_run_ids) != len(set(evidence_run_ids)):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    expected_all_run_ids = sorted(evidence_run_ids)
    expected_all_artifact_ids = sorted(
        {
            *observed_artifact_ids,
            *(cast(int, item["artifact_id"]) for item in artifact_documents),
        }
    )
    expected_all_payload_sha256 = sorted(
        {
            *(
                cast(str, cast(dict[str, Any], runtime_stages[stage])["payload_sha256"])
                for stage in _RECOVERY_V2_TERMINAL_WORKFLOW_STAGES
            ),
            *(cast(str, item["payload_sha256"]) for item in artifact_documents),
            cast(str, provider["receipt_sha256"]),
            cast(str, quarantine["receipt_sha256"]),
            cast(str, bindings["runtime_bindings_receipt_sha256"]),
            cast(str, replay["payload_sha256"]),
            hashlib.sha256(live_attestation_payload).hexdigest(),
            hashlib.sha256(quiescence_payload).hexdigest(),
            hashlib.sha256(delivery_reservation_payload).hexdigest(),
            hashlib.sha256(delivery_evidence_payload).hexdigest(),
            *cast(list[str], stage_evidence["payload_sha256"]),
        }
    )
    expected_all_archive_sha256 = sorted(
        {
            *(
                cast(str, cast(dict[str, Any], runtime_stages[stage])["archive_sha256"])
                for stage in _RECOVERY_V2_TERMINAL_WORKFLOW_STAGES
            ),
            *(cast(str, item["archive_sha256"]) for item in artifact_documents),
            *cast(list[str], stage_evidence["archive_sha256"]),
        }
    )
    if (
        not _json_exact_equal(terminal_report["all_run_ids"], expected_all_run_ids)
        or not _json_exact_equal(
            terminal_report["all_artifact_ids"], expected_all_artifact_ids
        )
        or not _json_exact_equal(
            terminal_report["all_payload_sha256"], expected_all_payload_sha256
        )
        or not _json_exact_equal(
            terminal_report["all_archive_sha256"], expected_all_archive_sha256
        )
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    gates = qa.get("gates")
    if (
        set(qa) != {"acceptance_percent", "p0", "p1", "p2", "open_threads", "gates"}
        or qa.get("acceptance_percent") != 100
        or not _exact_integer_fields(qa, {"p0", "p1", "p2", "open_threads"})
        or any(qa.get(field) != 0 for field in ("p0", "p1", "p2", "open_threads"))
        or not isinstance(gates, list)
        or gates != [{"name": name, "status": "PASS"} for name in _RECOVERY_V2_TERMINAL_QA_GATES]
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    expected_effect_fields = {
        "neon_identity_gets",
        "neon_preflight_gets",
        "neon_migrate_validation_gets",
        "neon_posts",
        "neon_patch",
        "neon_delete",
        "postgresql_connection_attempts_upper_bound",
        "postgresql_sql_statements_upper_bound",
        "postgresql_sql_write_statements_upper_bound",
        "postgresql_migrations",
        "postgresql_read_transactions_attempted",
        "postgresql_function_reads_attempted",
        "postgresql_mutating_function_calls_attempted",
        "postgresql_mutating_function_calls_completed",
        "postgresql_mutating_function_outcomes_ambiguous",
        "postgresql_possible_durable_mutations_upper_bound",
        "r2_puts",
        "r2_gets",
        "r2_objects",
        "r2_lists",
        "r2_deletes",
        "r2_overwrites",
        "r2_retries",
        "official_reads",
        "provider_requests",
        "provider_credits",
        "provider_retries",
        "secret_writes",
        "replay_external_effects",
        "automatic_retries",
        "purchases",
        "bet_calls",
        "hypotheses_generated",
        "edge_promotions",
        "social_publications",
        "synthetic_rows",
        "backfilled_rows",
        "leagues",
        "league_market_cells",
    }
    if (
        set(effect_counters) != expected_effect_fields
        or any(type(value) is not int or value < 0 for value in effect_counters.values())
        or cast(int, effect_counters["neon_identity_gets"]) > 25
        or cast(int, effect_counters["neon_preflight_gets"]) > 39
        or cast(int, effect_counters["neon_migrate_validation_gets"]) > 26
        or cast(int, effect_counters["neon_posts"]) > 1
        or any(effect_counters[field] != 0 for field in ("neon_patch", "neon_delete"))
        or effect_counters["r2_puts"] != 3
        or effect_counters["r2_gets"] != 3
        or effect_counters["r2_objects"] != 3
        or any(
            effect_counters[field] != 0
            for field in ("r2_lists", "r2_deletes", "r2_overwrites", "r2_retries")
        )
        or not 1 <= cast(int, effect_counters["official_reads"]) <= 50
        or effect_counters["provider_requests"] != 5
        or cast(int, effect_counters["provider_credits"]) > 1_000
        or effect_counters["provider_retries"] != 0
        or effect_counters["secret_writes"] != 4
        or any(
            effect_counters[field] != 0
            for field in (
                "replay_external_effects",
                "automatic_retries",
                "purchases",
                "bet_calls",
                "hypotheses_generated",
                "edge_promotions",
                "social_publications",
                "synthetic_rows",
                "backfilled_rows",
            )
        )
        or effect_counters["leagues"] != 5
        or effect_counters["league_market_cells"] != 10
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    stage_effect_values = tuple(stage_effects.values())
    if (
        effect_counters["neon_identity_gets"] != stage_effects["RECOVERY_IDENTITY_V2"]["neon_gets"]
        or effect_counters["neon_preflight_gets"]
        != stage_effects["PRODUCTION_PREFLIGHT_V2"]["neon_gets"]
        or effect_counters["neon_migrate_validation_gets"]
        != stage_effects["MIGRATE_0015"]["neon_gets"]
        or any(
            effect_counters[field] != sum(stage[field] for stage in stage_effect_values)
            for field in (
                "neon_posts",
                "neon_patch",
                "neon_delete",
                "postgresql_connection_attempts_upper_bound",
                "postgresql_sql_statements_upper_bound",
                "postgresql_sql_write_statements_upper_bound",
                "postgresql_migrations",
                "postgresql_read_transactions_attempted",
                "postgresql_function_reads_attempted",
                "postgresql_mutating_function_calls_attempted",
                "postgresql_mutating_function_calls_completed",
                "postgresql_mutating_function_outcomes_ambiguous",
                "postgresql_possible_durable_mutations_upper_bound",
                "r2_puts",
                "r2_gets",
                "r2_objects",
                "r2_lists",
                "r2_deletes",
                "r2_overwrites",
                "r2_retries",
                "official_reads",
                "provider_requests",
                "provider_credits",
                "provider_retries",
                "secret_writes",
                "replay_external_effects",
                "automatic_retries",
                "purchases",
                "bet_calls",
                "hypotheses_generated",
                "edge_promotions",
                "social_publications",
                "synthetic_rows",
                "backfilled_rows",
                "leagues",
                "league_market_cells",
            )
        )
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    try:
        delivery_receipt = cast(
            dict[str, Any],
            json.loads(
                delivery_evidence_payload,
                object_pairs_hook=_recovery_v2_unique_json_object,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            ),
        )
        generated_at = _authority_timestamp(
            terminal_report.get("generated_at"), field="terminal_report_generated_at"
        )
        delivery_observed_at = _authority_timestamp(
            delivery_receipt.get("observed_at"), field="delivery_observed_at"
        )
        live_completed_at = _authority_timestamp(
            live_attestation.get("run_completed_observed_at"),
            field="terminal_live_run_completed_observed_at",
        )
        quiescence_observed_at = _authority_timestamp(
            quiescence.get("observed_at"), field="terminal_quiescence_observed_at"
        )
    except (ChronosProductionError, json.JSONDecodeError, TypeError, ValueError):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
    if (
        generated_at < release_date
        or generated_at > record_date
        or not (
            live_completed_at
            <= quiescence_observed_at
            < phase_one_date
            < delivery_observed_at
            <= generated_at
        )
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    mission_started_at = _authority_timestamp(
        DATA_TORRENT_RECOVERY_V2_NOT_BEFORE,
        field="recovery_v2_not_before",
    )
    if terminal_report["duration_seconds"] != int(
        (generated_at - mission_started_at).total_seconds()
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    terminal_snapshot = cast(str, terminal_report["reviewed_runtime_snapshot_sha256"])
    if not hmac.compare_digest(
        terminal_snapshot,
        _recovery_v2_terminal_runtime_snapshot(terminal_report),
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    if (
        context.get("head") != derived_delivery.get("pr_c_phase_one_head_sha")
        or context.get("pr") != f"PR_C:{derived_delivery.get('pr_c')}"
        or context.get("proofs_reused")
        != [
            f"active-release-claim:{release_claim}",
            f"reservation-record:{reservation_record.get('hash')}",
            f"phase-one-record:{phase_one_record.get('hash')}",
            f"terminal-runtime-snapshot:{terminal_snapshot}",
        ]
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    identity_effects = stage_effects["RECOVERY_IDENTITY_V2"]
    seal_effects = stage_effects["DURABLE_IDENTITY_SEAL_V2"]
    preflight_effects = stage_effects["PRODUCTION_PREFLIGHT_V2"]
    migrate_effects = stage_effects["MIGRATE_0015"]
    verify_effects = stage_effects["VERIFY_0015"]
    live_effects = stage_effects["LIVE_ONCE"]
    binding_effects = stage_effects["FOUR_RUNTIME_BINDINGS"]
    replay_effects = stage_effects["REPLAY_100"]

    def zero_outside(effects: Mapping[str, int], allowed: set[str]) -> bool:
        return all(value == 0 for field, value in effects.items() if field not in allowed)

    if (
        not 1 <= identity_effects["neon_gets"] <= 25
        or not zero_outside(identity_effects, {"neon_gets"})
        or seal_effects["r2_puts"] != 1
        or seal_effects["r2_gets"] != 1
        or seal_effects["r2_objects"] != 1
        or not zero_outside(seal_effects, {"r2_puts", "r2_gets", "r2_objects"})
        or not 1 <= preflight_effects["neon_gets"] <= 39
        or preflight_effects["neon_posts"] not in {0, 1}
        or preflight_effects["r2_gets"] != 1
        or preflight_effects["postgresql_connection_attempts_upper_bound"] not in {3, 4}
        or preflight_effects["postgresql_sql_statements_upper_bound"] != 128
        or not zero_outside(
            preflight_effects,
            {
                "neon_gets",
                "neon_posts",
                "r2_gets",
                "postgresql_connection_attempts_upper_bound",
                "postgresql_sql_statements_upper_bound",
            },
        )
        or not 1 <= migrate_effects["neon_gets"] <= 26
        or migrate_effects["postgresql_connection_attempts_upper_bound"] not in {5, 10}
        or migrate_effects["postgresql_sql_statements_upper_bound"] != 2_048
        or migrate_effects["postgresql_sql_write_statements_upper_bound"] != 1_024
        or (
            migrate_effects["postgresql_connection_attempts_upper_bound"],
            migrate_effects["postgresql_migrations"],
        )
        not in {(5, 0), (10, 1)}
        or not zero_outside(
            migrate_effects,
            {
                "neon_gets",
                "postgresql_connection_attempts_upper_bound",
                "postgresql_sql_statements_upper_bound",
                "postgresql_sql_write_statements_upper_bound",
                "postgresql_migrations",
            },
        )
        or verify_effects["postgresql_connection_attempts_upper_bound"] != 4
        or verify_effects["postgresql_sql_statements_upper_bound"] != 128
        or not zero_outside(
            verify_effects,
            {"postgresql_connection_attempts_upper_bound", "postgresql_sql_statements_upper_bound"},
        )
        or not 51 <= live_effects["postgresql_connection_attempts_upper_bound"] <= 53
        or live_effects["postgresql_sql_statements_upper_bound"] != 0
        or live_effects["postgresql_sql_write_statements_upper_bound"] != 0
        or live_effects["postgresql_read_transactions_attempted"] <= 0
        or live_effects["postgresql_function_reads_attempted"] <= 0
        or live_effects["postgresql_mutating_function_calls_attempted"] != 41
        or live_effects["postgresql_mutating_function_calls_completed"] != 41
        or live_effects["postgresql_mutating_function_outcomes_ambiguous"] != 0
        or live_effects["postgresql_possible_durable_mutations_upper_bound"] != 41
        or live_effects["postgresql_connection_attempts_upper_bound"]
        != live_effects["postgresql_read_transactions_attempted"]
        + live_effects["postgresql_function_reads_attempted"]
        + live_effects["postgresql_mutating_function_calls_attempted"]
        or live_effects["r2_puts"] != 2
        or live_effects["r2_gets"] != 1
        or live_effects["r2_objects"] != 2
        or not 1 <= live_effects["official_reads"] <= 50
        or live_effects["provider_requests"] != 5
        or not 1 <= live_effects["provider_credits"] <= 1_000
        or live_effects["leagues"] != 5
        or live_effects["league_market_cells"] != 10
        or not zero_outside(
            live_effects,
            {
                "postgresql_connection_attempts_upper_bound",
                "postgresql_read_transactions_attempted",
                "postgresql_function_reads_attempted",
                "postgresql_mutating_function_calls_attempted",
                "postgresql_mutating_function_calls_completed",
                "postgresql_mutating_function_outcomes_ambiguous",
                "postgresql_possible_durable_mutations_upper_bound",
                "r2_puts",
                "r2_gets",
                "r2_objects",
                "official_reads",
                "provider_requests",
                "provider_credits",
                "leagues",
                "league_market_cells",
            },
        )
        or binding_effects["secret_writes"] != 4
        or not zero_outside(binding_effects, {"secret_writes"})
        or any(replay_effects.values())
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    terminal_reviews = terminal_report.get("independent_reviews")
    if not isinstance(terminal_reviews, dict) or set(terminal_reviews) != set(
        DATA_TORRENT_RECOVERY_V2_TERMINAL_REVIEW_PATHS
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    terminal_snapshot_ref = f"TERMINAL_RUNTIME_SNAPSHOT_SHA256:{terminal_snapshot}"
    for agent_id, relative in DATA_TORRENT_RECOVERY_V2_TERMINAL_REVIEW_PATHS.items():
        review_payload, review = _recovery_v2_strict_json(
            root / relative,
            maximum_bytes=262_144,
            repository_root=root,
        )
        if (
            terminal_reviews.get(agent_id)
            != {"path": relative, "raw_sha256": hashlib.sha256(review_payload).hexdigest()}
            or set(review) != _RECOVERY_V2_AGENT_REPORT_FIELDS
            or review.get("agent_id") != agent_id
            or review.get("mission_id") != "DATA_TORRENT_RECOVERY_V2"
            or review.get("unknowns") != []
            or review.get("assumptions") != []
            or review.get("risks") != []
            or review.get("main_objection")
            != "P0=0; P1=0; P2=0; OPEN_THREADS=0; VERDICT=PASS_AND_HOLD_CANDIDATE"
            or review.get("recommended_action")
            != "RUN_EXTERNAL_PR_C_POSTMERGE_FINAL_GATE"
            or review.get("scale_condition")
            != "PR_C_MERGE_AND_POSTMERGE_SAFE_REQUIRED"
            or type(review.get("confidence")) not in {int, float}
            or not 0.95 <= float(review["confidence"]) <= 1.0
            or any(
                not isinstance(review.get(field), str) or not cast(str, review[field]).strip()
                for field in (
                    "minimum_decisive_test",
                    "estimated_compute",
                    "estimated_external_cost",
                    "estimated_human_time",
                    "maintenance_impact",
                )
            )
        ):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        facts = review.get("facts_verified")
        if (
            not isinstance(facts, list)
            or not facts
            or any(
                not isinstance(fact, dict)
                or set(fact) != {"claim", "evidence_refs", "status"}
                or fact.get("status") != "VERIFIED"
                or not isinstance(fact.get("claim"), str)
                or not cast(str, fact["claim"]).strip()
                or not isinstance(fact.get("evidence_refs"), list)
                or terminal_snapshot_ref not in fact["evidence_refs"]
                or any(
                    not isinstance(reference, str) or not reference
                    for reference in fact["evidence_refs"]
                )
                for fact in facts
            )
        ):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")

    _graph_payload, graph = _recovery_v2_strict_json(
        root / "reports" / "evidence" / "evidence-graph.json",
        maximum_bytes=16 * 1024 * 1024,
        repository_root=root,
    )
    claims = graph.get("claims")
    nodes = graph.get("decision_nodes")
    edges = graph.get("edges")
    if (
        not isinstance(claims, list)
        or not isinstance(nodes, list)
        or not isinstance(edges, list)
        or any(not isinstance(item, dict) for item in (*claims, *nodes, *edges))
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    terminal_claim_id = _RECOVERY_V2_TERMINAL_CLAIM
    terminal_claims = [item for item in claims if item.get("claim_id") == terminal_claim_id]
    phase_one_nodes = [
        item
        for item in nodes
        if item.get("decision_id") == phase_one_record.get("decision_id")
    ]
    phase_one_edges = [
        item
        for item in edges
        if item.get("to_decision_id") == phase_one_record.get("decision_id")
    ]
    terminal_nodes = [
        item for item in nodes if item.get("decision_id") == record.get("decision_id")
    ]
    terminal_edges = [
        item for item in edges if item.get("to_decision_id") == record.get("decision_id")
    ]
    successor_edge_suffix = [
        item
        for item in edges
        if item.get("to_decision_id")
        in {
            reservation_record.get("decision_id"),
            phase_one_record.get("decision_id"),
            record.get("decision_id"),
        }
    ]
    if (
        len(terminal_claims) != 1
        or phase_one_nodes
        != [
            {
                "decision_id": phase_one_record.get("decision_id"),
                "ledger_record_hash": phase_one_record.get("hash"),
            }
        ]
        or len(phase_one_edges) != 3
        or {edge.get("from_claim_id") for edge in phase_one_edges}
        != {release_claim, _RECOVERY_V2_RESERVATION_CLAIM, _RECOVERY_V2_PHASE_ONE_CLAIM}
        or any(
            set(edge)
            != {"edge_id", "from_claim_id", "to_decision_id", "relation", "status"}
            or not isinstance(edge.get("edge_id"), str)
            or not cast(str, edge["edge_id"]).strip()
            or edge.get("relation") != "SUPPORTS"
            or edge.get("status") != "RECORDED"
            for edge in phase_one_edges
        )
        or len(terminal_nodes) != 1
        or len(terminal_edges) != len(terminal_proofs)
        or not _recovery_v2_successor_edges_are_canonical(
            cast(list[dict[str, object]], edges), terminal_edges, list(terminal_proofs)
        )
        or not _recovery_v2_successor_edges_are_canonical(
            cast(list[dict[str, object]], edges),
            cast(list[dict[str, object]], successor_edge_suffix),
            [
                release_claim,
                _RECOVERY_V2_RESERVATION_CLAIM,
                release_claim,
                _RECOVERY_V2_RESERVATION_CLAIM,
                _RECOVERY_V2_PHASE_ONE_CLAIM,
                *terminal_proofs,
            ],
            require_tail=True,
        )
        or set(terminal_claims[0])
        != {
            "claim_id",
            "claim",
            "scope",
            "source",
            "grain",
            "temporal_class",
            "artifact",
            "hash",
            "code_revision",
            "execution_id",
            "scientific_lineage_id",
            "dataset_lineage_id",
            "status",
            "verified_by",
            "successor_of",
        }
        or terminal_claims[0].get("artifact") != terminal_relative
        or terminal_claims[0].get("hash") != terminal_hash
        or terminal_claims[0].get("code_revision") != context.get("head")
        or terminal_claims[0].get("execution_id") != f"council-record:{record.get('decision_id')}"
        or terminal_claims[0].get("status") != "VERIFIED"
        or terminal_claims[0].get("verified_by") != ["C0", "C2", "C4", "DP6", "A2"]
        or terminal_claims[0].get("scope")
        != "DATA_TORRENT_RECOVERY_V2_TERMINAL_CANDIDATE"
        or terminal_claims[0].get("grain")
        != "ONE_TERMINAL_RUNTIME_TO_ONE_POSTMERGE_CANDIDATE"
        or terminal_claims[0].get("temporal_class") != "DECISION_AS_OF"
        or terminal_claims[0].get("scientific_lineage_id") != "DATA_TORRENT_RECOVERY_V2"
        or terminal_claims[0].get("dataset_lineage_id") != terminal_snapshot
        or terminal_claims[0].get("successor_of") != _RECOVERY_V2_PHASE_ONE_CLAIM
        or terminal_claims[0].get("claim")
        != (
            "Recovery V2 terminal runtime evidence and independent QA form a held "
            "PR-C candidate pending merge and postmerge SAFE V2"
        )
        or terminal_claims[0].get("source")
        != (
            f"Terminal report SHA-256 {terminal_hash}; reviewed runtime snapshot "
            f"SHA-256 {terminal_snapshot}"
        )
        or terminal_nodes[0]
        != {
            "decision_id": record.get("decision_id"),
            "ledger_record_hash": record.get("hash"),
        }
        or {edge.get("from_claim_id") for edge in terminal_edges}
        != set(terminal_proofs)
        or any(
            set(edge) != {"edge_id", "from_claim_id", "to_decision_id", "relation", "status"}
            or not isinstance(edge.get("edge_id"), str)
            or not cast(str, edge["edge_id"]).strip()
            or edge.get("relation") != "SUPPORTS"
            or edge.get("status") != "RECORDED"
            for edge in terminal_edges
        )
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    return str(record["hash"])


def _validate_data_torrent_recovery_v2_council_release(
    *,
    repository_root: Path | None = None,
    now: datetime | None = None,
    closure_phase: str,
) -> str:
    """Verify the direct append-only implementation release and its frozen bytes."""

    root = (
        Path(os.path.abspath(Path(__file__))).parents[2]
        if repository_root is None
        else Path(os.path.abspath(repository_root))
    )
    _recovery_v2_require_no_reparse_chain(
        root,
        repository_root=root,
        allow_missing_leaf=False,
    )
    observed_now = datetime.now(UTC) if now is None else now
    if observed_now.tzinfo is None:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    observed_now = observed_now.astimezone(UTC)
    ledger_path = root / "reports" / "council" / "decision-ledger.jsonl"
    ledger_payload = _recovery_v2_evidence_bytes(
        ledger_path,
        repository_root=root,
        maximum_bytes=16 * 1024 * 1024,
    )
    if (
        not ledger_payload
        or len(ledger_payload) > 16 * 1024 * 1024
        or ledger_path.is_symlink()
        or ledger_payload.startswith(b"\xef\xbb\xbf")
        or b"\r" in ledger_payload
        or not ledger_payload.endswith(b"\n")
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    raw_lines = ledger_payload[:-1].split(b"\n")
    if not raw_lines or any(not line or len(line) > 2 * 1024 * 1024 for line in raw_lines):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    records: list[dict[str, Any]] = []
    expected_previous = "0" * 64
    decision_ids: set[str] = set()
    record_hashes: set[str] = set()
    for raw_line in raw_lines:
        try:
            record = json.loads(
                raw_line,
                object_pairs_hook=_recovery_v2_unique_json_object,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID") from None
        if not isinstance(record, dict):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        record = cast(dict[str, Any], record)
        record_hash = record.get("hash")
        decision_id = record.get("decision_id")
        unsigned = {key: value for key, value in record.items() if key != "hash"}
        computed = hashlib.sha256(
            json.dumps(
                unsigned,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if (
            not isinstance(record_hash, str)
            or _HEX_64.fullmatch(record_hash) is None
            or not hmac.compare_digest(record_hash, computed)
            or record.get("hash_algorithm") != "SHA-256"
            or record.get("previous_hash") != expected_previous
            or not isinstance(decision_id, str)
            or decision_id in decision_ids
            or record_hash in record_hashes
        ):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
        records.append(record)
        decision_ids.add(decision_id)
        record_hashes.add(record_hash)
        expected_previous = record_hash
    if len(records) < 4:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_MISSING")
    try:
        anchor_index = next(
            index
            for index, record in enumerate(records)
            if record.get("decision_id") == DATA_TORRENT_RECOVERY_V2_COUNCIL_ANCHOR_ID
        )
        anchor, initial_release, full_suite_failure, release = records[
            anchor_index : anchor_index + 4
        ]
    except (StopIteration, ValueError):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_MISSING") from None
    ledger_prefix = b"\n".join(raw_lines[: anchor_index + 3]) + b"\n"
    ledger_prefix_through_release = b"\n".join(raw_lines[: anchor_index + 4]) + b"\n"
    release_raw_line = raw_lines[anchor_index + 3]
    release_fields = {
        "decision_id",
        "record_type",
        "date",
        "proposal",
        "objections",
        "proof",
        "decision",
        "dissent",
        "responsible",
        "context",
        "previous_hash",
        "hash_algorithm",
        "hash",
    }
    for successor, raw_line in zip(
        records[anchor_index + 3 :],
        raw_lines[anchor_index + 3 :],
        strict=True,
    ):
        if (
            set(successor) != release_fields
            or not _recovery_v2_council_timestamp_is_canonical(successor.get("date"))
            or raw_line
            != json.dumps(
                successor,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    expected_release_proposal = (
        "Release the exact independently re-reviewed DATA TORRENT RECOVERY V2 "
        "implementation candidate after the sole full-suite correction and distinct "
        "E1 QA defect closures, while holding every external effect until exact-head "
        "SAFE V2, normal merge, post-merge SAFE V2 and immediate-predecessor proof."
    )
    expected_release_objections = [
        (
            "Record RCV3-20260830-195 authorized only the initial smallest full-suite "
            "correction; it is not reused as blanket authority for later QA changes."
        ),
        (
            "Later changes are distinct E1 implementation and independent-QA defect "
            "closures under RCV3-20260830-193 and are frozen path-by-path in the new "
            "four-axis reviewed candidate."
        ),
        (
            "The sole full suite remains 29 failed, 3744 passed and 35 skipped; it was "
            "not rerun, and every subsequent verification is targeted and recorded."
        ),
        (
            "This decision authorizes implementation delivery only; GitHub, Neon, "
            "PostgreSQL, R2, official-source, provider and secret-write effects remain "
            "at zero and dormant until their exact gates."
        ),
    ]
    if (
        anchor.get("decision_id") != DATA_TORRENT_RECOVERY_V2_COUNCIL_ANCHOR_ID
        or anchor.get("hash") != DATA_TORRENT_RECOVERY_V2_COUNCIL_ANCHOR_HASH
        or initial_release.get("decision_id") != DATA_TORRENT_RECOVERY_V2_INITIAL_RELEASE_ID
        or initial_release.get("hash") != DATA_TORRENT_RECOVERY_V2_INITIAL_RELEASE_HASH
        or initial_release.get("previous_hash") != DATA_TORRENT_RECOVERY_V2_COUNCIL_ANCHOR_HASH
        or full_suite_failure.get("decision_id") != DATA_TORRENT_RECOVERY_V2_FULL_SUITE_FAILURE_ID
        or full_suite_failure.get("hash") != DATA_TORRENT_RECOVERY_V2_FULL_SUITE_FAILURE_HASH
        or full_suite_failure.get("previous_hash") != DATA_TORRENT_RECOVERY_V2_INITIAL_RELEASE_HASH
        or full_suite_failure.get("record_type") != "FAILURE"
        or full_suite_failure.get("decision") != "PASS_AND_HOLD"
        or not hmac.compare_digest(
            hashlib.sha256(ledger_prefix).hexdigest(),
            DATA_TORRENT_RECOVERY_V2_LEDGER_PREFIX_THROUGH_195_SHA256,
        )
        or release.get("previous_hash") != DATA_TORRENT_RECOVERY_V2_FULL_SUITE_FAILURE_HASH
        or set(release) != release_fields
        or release_raw_line
        != json.dumps(
            release,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        or release.get("decision_id") != DATA_TORRENT_RECOVERY_V2_BASE_RELEASE_ID
        or release.get("hash") != DATA_TORRENT_RECOVERY_V2_BASE_RELEASE_HASH
        or not hmac.compare_digest(
            hashlib.sha256(ledger_prefix_through_release).hexdigest(),
            DATA_TORRENT_RECOVERY_V2_LEDGER_PREFIX_THROUGH_196_SHA256,
        )
        or release.get("record_type") != "DECISION"
        or release.get("decision") != "PASS_AND_HOLD"
        or release.get("dissent") is not None
        or release.get("responsible") != "C0"
        or release.get("proposal") != expected_release_proposal
        or release.get("objections") != expected_release_objections
        or release.get("proof") != ["GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION.RELEASE.002"]
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    initial_context = initial_release.get("context")
    if not isinstance(initial_context, dict):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    initial_context = cast(dict[str, Any], initial_context)
    if (
        initial_context.get("reviewed_snapshot_sha256")
        != DATA_TORRENT_RECOVERY_V2_INITIAL_REVIEWED_SNAPSHOT_SHA256
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    initial_candidate = initial_context.get("reviewed_candidate")
    if not isinstance(initial_candidate, dict) or not isinstance(
        initial_candidate.get("files"), list
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    _validate_recovery_v2_frozen_projection(initial_candidate)
    initial_release_date = _authority_timestamp(
        initial_release.get("date"), field="initial_council_release_date"
    )
    _validate_recovery_v2_agent_reports(
        root,
        bindings=initial_context.get("independent_reviews"),
        reviewed_snapshot_sha256=DATA_TORRENT_RECOVERY_V2_INITIAL_REVIEWED_SNAPSHOT_SHA256,
        review_paths=DATA_TORRENT_RECOVERY_V2_INITIAL_REVIEW_PATHS,
    )
    _validate_recovery_v2_final_review(
        root,
        binding=initial_context.get("final_review"),
        relative=DATA_TORRENT_RECOVERY_V2_INITIAL_FINAL_REVIEW_PATH,
        reviewed_snapshot_sha256=DATA_TORRENT_RECOVERY_V2_INITIAL_REVIEWED_SNAPSHOT_SHA256,
        schema_version="data-torrent-recovery-v2-final-review-v3",
        review_paths=DATA_TORRENT_RECOVERY_V2_INITIAL_REVIEW_PATHS,
        reviewed_file_count=len(initial_candidate["files"]),
        reviewed_at_not_after=initial_release_date,
    )
    full_suite_failure_date = _authority_timestamp(
        full_suite_failure.get("date"),
        field="full_suite_failure_date",
    )
    release_date = _authority_timestamp(release.get("date"), field="council_release_date")
    if (
        release_date <= full_suite_failure_date
        or release_date > observed_now
        or release_date
        > _authority_timestamp(
            DATA_TORRENT_RECOVERY_V2_EXPIRES_AT,
            field="recovery_v2_expiry",
        )
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    context = release.get("context")
    if not isinstance(context, dict):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    context = cast(dict[str, Any], context)
    context_fields = {
        "candidate_context",
        "commit_context",
        "mission_id",
        "phase",
        "program_start_sha",
        "head",
        "branch",
        "worktree",
        "pr",
        "writer",
        "writer_count",
        "files",
        "manifest",
        "effect_contract",
        "postgresql_call_graph",
        "reviewed_candidate",
        "reviewed_snapshot_sha256",
        "runtime_release",
        "defects",
        "release_conditions",
        "progression_contract",
        "observed_external_effects",
        "independent_reviews",
        "final_review",
        "targeted_tests",
        "proofs_reused",
        "full_suite_correction",
        "external_effects_authorized_now",
    }
    if set(context) != context_fields:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    reviewed_snapshot = context.get("reviewed_snapshot_sha256")
    if not isinstance(reviewed_snapshot, str) or _HEX_64.fullmatch(reviewed_snapshot) is None:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    suffix = records[anchor_index + 4 :]
    if len(suffix) < 10:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    local_qa_failure = suffix[0]
    local_correction_release = suffix[1]
    static_qa_failure = suffix[2]
    static_correction_release = suffix[3]
    exact_head_ci_failure = suffix[4]
    exact_head_ci_correction_release = suffix[5]
    post_202_b101_failure = suffix[6]
    post_202_b101_correction_release = suffix[7]
    exact_head_ci_cycle_2_failure = suffix[8]
    exact_head_ci_cycle_2_correction_release = suffix[9]
    release_suffix = suffix[10:]
    ledger_prefix_through_local_correction = (
        b"\n".join(raw_lines[: anchor_index + 6]) + b"\n"
    )
    if (
        local_qa_failure.get("decision_id")
        != DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_FAILURE_ID
        or local_qa_failure.get("hash")
        != DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_FAILURE_HASH
        or local_correction_release.get("decision_id")
        != DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_RELEASE_ID
        or local_correction_release.get("hash")
        != DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_RELEASE_HASH
        or not hmac.compare_digest(
            hashlib.sha256(ledger_prefix_through_local_correction).hexdigest(),
            DATA_TORRENT_RECOVERY_V2_LEDGER_PREFIX_THROUGH_198_SHA256,
        )
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    ledger_prefix_through_static_correction = (
        b"\n".join(raw_lines[: anchor_index + 8]) + b"\n"
    )
    if not hmac.compare_digest(
        hashlib.sha256(ledger_prefix_through_static_correction).hexdigest(),
        DATA_TORRENT_RECOVERY_V2_LEDGER_PREFIX_THROUGH_200_SHA256,
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    ledger_prefix_through_exact_head_correction = (
        b"\n".join(raw_lines[: anchor_index + 10]) + b"\n"
    )
    if not hmac.compare_digest(
        hashlib.sha256(ledger_prefix_through_exact_head_correction).hexdigest(),
        DATA_TORRENT_RECOVERY_V2_LEDGER_PREFIX_THROUGH_202_SHA256,
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    ledger_prefix_through_post_202_b101_correction = (
        b"\n".join(raw_lines[: anchor_index + 12]) + b"\n"
    )
    if not hmac.compare_digest(
        hashlib.sha256(ledger_prefix_through_post_202_b101_correction).hexdigest(),
        DATA_TORRENT_RECOVERY_V2_LEDGER_PREFIX_THROUGH_204_SHA256,
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    pr_b_release = (
        release_suffix[0]
        if release_suffix
        and release_suffix[0].get("record_type") == "DECISION"
        and release_suffix[0].get("proof") == [_RECOVERY_V2_PR_B_RELEASE_CLAIM]
        else None
    )
    expected_manifest = {
        "path": "configs/execution/data-torrent-recovery-v2.json",
        "raw_sha256": DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256,
        "canonical_sha256": DATA_TORRENT_RECOVERY_V2_MANIFEST_CANONICAL_SHA256,
        "source_hash": DATA_TORRENT_RECOVERY_V2_OWNER_DIRECTIVE_SHA256,
        "expires_at": "2026-09-13T23:59:59Z",
    }
    expected_effect = {
        "path": "configs/execution/data-torrent-recovery-v2-effect-contract.json",
        "raw_sha256": DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_SHA256,
        "canonical_sha256": DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_CANONICAL_SHA256,
    }
    expected_call_graph = {
        "path": "configs/execution/data-torrent-live-v2-postgresql-call-graph.json",
        "raw_sha256": DATA_TORRENT_LIVE_V2_POSTGRESQL_CALL_GRAPH_SHA256,
        "canonical_sha256": DATA_TORRENT_LIVE_V2_POSTGRESQL_CALL_GRAPH_CANONICAL_SHA256,
    }
    _validate_recovery_v2_frozen_projection(context.get("reviewed_candidate"))
    _validate_recovery_v2_frozen_projection(context.get("runtime_release"))
    reviewed_candidate = cast(dict[str, Any], context["reviewed_candidate"])
    runtime_release = cast(dict[str, Any], context["runtime_release"])
    initial_files = {
        cast(str, item["path"]): cast(str, item["lf_sha256"])
        for item in cast(list[dict[str, Any]], initial_candidate["files"])
    }
    reviewed_files = {
        cast(str, item["path"]): cast(str, item["lf_sha256"])
        for item in cast(list[dict[str, Any]], reviewed_candidate["files"])
    }
    modified_paths = sorted(
        path
        for path in initial_files.keys() & reviewed_files.keys()
        if initial_files[path] != reviewed_files[path]
    )
    added_paths = sorted(reviewed_files.keys() - initial_files.keys())
    removed_paths = sorted(initial_files.keys() - reviewed_files.keys())
    failure_context = full_suite_failure.get("context")
    if not isinstance(failure_context, dict):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    expected_full_suite_correction = {
        "failure_record_id": DATA_TORRENT_RECOVERY_V2_FULL_SUITE_FAILURE_ID,
        "failure_record_hash": DATA_TORRENT_RECOVERY_V2_FULL_SUITE_FAILURE_HASH,
        "failed_reviewed_snapshot_sha256": DATA_TORRENT_RECOVERY_V2_INITIAL_REVIEWED_SNAPSHOT_SHA256,
        "sole_full_suite_result": failure_context.get("full_suite"),
        "full_suite_rerun": False,
        "record_195_minimal_correction_paths": failure_context.get(
            "minimal_correction_paths"
        ),
        "record_195_scope": "FIRST_FULL_SUITE_FAILURE_SMALLEST_CORRECTION_ONLY",
        "subsequent_qa_authority": (
            "RCV3-20260830-193_E1_LOCAL_IMPLEMENTATION_AND_INDEPENDENT_QA_"
            "WITH_FRESH_FOUR_AXIS_RELEASE_REVIEW"
        ),
        "record_195_reused_as_blanket_authority": False,
        "all_delta_paths_frozen_and_independently_rereviewed": True,
        "review_delta_from_initial_release": {
            "baseline_projection_sha256": DATA_TORRENT_RECOVERY_V2_INITIAL_REVIEWED_SNAPSHOT_SHA256,
            "current_projection_sha256": reviewed_candidate["projection_sha256"],
            "modified_count": len(modified_paths),
            "modified_paths": modified_paths,
            "added_count": len(added_paths),
            "added_paths": added_paths,
            "removed_count": len(removed_paths),
            "removed_paths": removed_paths,
        },
    }
    files = context.get("files")
    targeted_tests = context.get("targeted_tests")
    expected_targeted_test_fields = {
        "sole_full_suite",
        "recovery_supervision",
        "governance_release",
        "recovery_v2_domain",
        "ruff_changed_python",
        "mypy_recovery_v2_strict",
        "bandit_recovery_v2",
        "compileall",
        "pip_check",
        "secret_scan",
        "unapproved_network_attempts",
    }
    expected_proofs_reused = [
        f"owner-directive:{DATA_TORRENT_RECOVERY_V2_OWNER_DIRECTIVE_SHA256}",
        f"manifest-raw:{DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256}",
        f"manifest-canonical:{DATA_TORRENT_RECOVERY_V2_MANIFEST_CANONICAL_SHA256}",
        f"effect-contract-raw:{DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_SHA256}",
        f"effect-contract-canonical:{DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_CANONICAL_SHA256}",
        f"postgresql-call-graph-raw:{DATA_TORRENT_LIVE_V2_POSTGRESQL_CALL_GRAPH_SHA256}",
        f"postgresql-call-graph-canonical:{DATA_TORRENT_LIVE_V2_POSTGRESQL_CALL_GRAPH_CANONICAL_SHA256}",
        f"council-anchor:{DATA_TORRENT_RECOVERY_V2_COUNCIL_ANCHOR_HASH}",
        f"initial-release:{DATA_TORRENT_RECOVERY_V2_INITIAL_RELEASE_HASH}",
        f"full-suite-failure:{DATA_TORRENT_RECOVERY_V2_FULL_SUITE_FAILURE_HASH}",
    ]
    initial_release_files = initial_context.get("files")
    if not isinstance(initial_release_files, list) or any(
        not isinstance(path, str) for path in initial_release_files
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    expected_release_files = sorted(
        {
            *cast(list[str], initial_release_files),
            *modified_paths,
            *added_paths,
            *removed_paths,
            *DATA_TORRENT_RECOVERY_V2_REVIEW_PATHS.values(),
            DATA_TORRENT_RECOVERY_V2_FINAL_REVIEW_PATH,
        }
    )
    expected_targeted_tests = {
        "sole_full_suite": "29 failed, 3744 passed, 35 skipped in 1161.48s; rerun=false",
        "recovery_supervision": "73 passed, 3 skipped",
        "governance_release": "PASS",
        "recovery_v2_domain": "1046 passed, 14 skipped",
        "ruff_changed_python": "PASS",
        "mypy_recovery_v2_strict": "PASS",
        "bandit_recovery_v2": "PASS",
        "compileall": "PASS",
        "pip_check": "PASS",
        "secret_scan": "PASS",  # nosec B105
        "unapproved_network_attempts": "0",
    }
    if (
        context.get("candidate_context") is not True
        or context.get("commit_context") is not False
        or context.get("mission_id") != "DATA_TORRENT_RECOVERY_V2"
        or context.get("phase")
        != "IMPLEMENTATION_RELEASE_AFTER_FULL_SUITE_CORRECTION_AND_INDEPENDENT_QA"
        or context.get("program_start_sha") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or context.get("head") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or context.get("branch") != "codex/data-torrent-recovery-v2"
        or context.get("worktree") != "ENGINEERING_WORKTREE:data-torrent-recovery-v2"
        or context.get("pr") != "PENDING"
        or context.get("writer") != "C0"
        or type(context.get("writer_count")) is not int
        or context.get("writer_count") != 1
        or not isinstance(files, list)
        or files != expected_release_files
        or context.get("manifest") != expected_manifest
        or context.get("effect_contract") != expected_effect
        or context.get("postgresql_call_graph") != expected_call_graph
        or context.get("reviewed_candidate") != reviewed_candidate
        or reviewed_snapshot != reviewed_candidate["projection_sha256"]
        or context.get("runtime_release") != runtime_release
        or not _json_exact_equal(
            context.get("full_suite_correction"), expected_full_suite_correction
        )
        or context.get("external_effects_authorized_now") is not False
        or not isinstance(targeted_tests, dict)
        or set(targeted_tests) != expected_targeted_test_fields
        or targeted_tests != expected_targeted_tests
        or context.get("proofs_reused") != expected_proofs_reused
        or not isinstance(context.get("defects"), dict)
        or not _exact_integer_fields(
            cast(dict[str, object], context["defects"]),
            {"open_p0", "open_p1", "open_p2", "open_threads"},
        )
        or context.get("defects") != {"open_p0": 0, "open_p1": 0, "open_p2": 0, "open_threads": 0}
        or not _json_exact_equal(
            context.get("release_conditions"),
            {
            "production_effects_authorized_now": False,
            "exact_head_safe_v2_required": True,
            "normal_merge_required": True,
            "postmerge_safe_v2_required": True,
            "immediate_predecessor_required_for_each_stage": True,
            },
        )
        or not _json_exact_equal(
            context.get("progression_contract"),
            {
            "council_role": "CONTROL_AND_RECORD_ONLY",
            "progression_mode": "AUTOMATIC_WITHIN_AUTHORIZED_MANIFEST",
            "controller_path": "scripts/dispatch_data_torrent_recovery_v2_stage.py",
            "stage_mapping_bound_to_effect_contract": True,
            "predecessor_attestation_and_semantic_validation_before_effect": True,
            "pr_c_phase_one_stage_finished_record_required": True,
            "pr_c_terminal_decision_record_required": True,
            },
        )
        or context.get("observed_external_effects")
        != {
            "git_remote_writes": 0,
            "github_writes": 0,
            "neon_gets": 0,
            "neon_mutations": 0,
            "postgresql_production_connections": 0,
            "postgresql_production_writes": 0,
            "r2_gets": 0,
            "r2_puts": 0,
            "official_reads": 0,
            "provider_requests": 0,
            "secret_writes": 0,  # nosec B105 - effect counter, not a credential.
        }
        or not isinstance(context.get("observed_external_effects"), dict)
        or not _exact_integer_fields(
            cast(dict[str, object], context["observed_external_effects"]),
            {
                "git_remote_writes",
                "github_writes",
                "neon_gets",
                "neon_mutations",
                "postgresql_production_connections",
                "postgresql_production_writes",
                "r2_gets",
                "r2_puts",
                "official_reads",
                "provider_requests",
                "secret_writes",
            },
        )
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID")
    _validate_recovery_v2_agent_reports(
        root,
        bindings=context.get("independent_reviews"),
        reviewed_snapshot_sha256=reviewed_snapshot,
    )
    _validate_recovery_v2_final_review(
        root,
        binding=context.get("final_review"),
        relative=DATA_TORRENT_RECOVERY_V2_FINAL_REVIEW_PATH,
        reviewed_snapshot_sha256=reviewed_snapshot,
        schema_version="data-torrent-recovery-v2-ci-correction-final-review-v3",
        review_paths=DATA_TORRENT_RECOVERY_V2_REVIEW_PATHS,
        reviewed_file_count=len(reviewed_candidate["files"]),
        reviewed_at_not_after=release_date,
    )
    active_release_date = _validate_recovery_v2_local_correction_pair(
        local_qa_failure,
        local_correction_release,
        root=root,
        base_release=release,
        base_release_date=release_date,
        observed_now=observed_now,
        expected_manifest=expected_manifest,
        expected_effect=expected_effect,
        expected_call_graph=expected_call_graph,
    )
    active_release_date = _validate_recovery_v2_static_correction_pair(
        static_qa_failure,
        static_correction_release,
        root=root,
        base_release=local_correction_release,
        base_release_date=active_release_date,
        observed_now=observed_now,
        expected_manifest=expected_manifest,
        expected_effect=expected_effect,
        expected_call_graph=expected_call_graph,
    )
    active_release_date = _validate_recovery_v2_exact_head_ci_correction_pair(
        exact_head_ci_failure,
        exact_head_ci_correction_release,
        root=root,
        base_release=static_correction_release,
        base_release_date=active_release_date,
        observed_now=observed_now,
        expected_manifest=expected_manifest,
        expected_effect=expected_effect,
        expected_call_graph=expected_call_graph,
    )
    active_release_date = _validate_recovery_v2_post_202_b101_correction_pair(
        post_202_b101_failure,
        post_202_b101_correction_release,
        root=root,
        base_release=exact_head_ci_correction_release,
        base_release_date=active_release_date,
        observed_now=observed_now,
        expected_manifest=expected_manifest,
        expected_effect=expected_effect,
        expected_call_graph=expected_call_graph,
    )
    active_release_date = _validate_recovery_v2_exact_head_ci_cycle_2_correction_pair(
        exact_head_ci_cycle_2_failure,
        exact_head_ci_cycle_2_correction_release,
        root=root,
        base_release=post_202_b101_correction_release,
        base_release_date=active_release_date,
        observed_now=observed_now,
        expected_manifest=expected_manifest,
        expected_effect=expected_effect,
        expected_call_graph=expected_call_graph,
    )
    active_release = exact_head_ci_cycle_2_correction_release
    active_release_claim = _RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_CORRECTION_RELEASE_CLAIM
    active_successors = release_suffix
    if pr_b_release is not None:
        active_release_date = _validate_recovery_v2_pr_b_release(
            pr_b_release,
            root=root,
            base_release=exact_head_ci_cycle_2_correction_release,
            base_release_claim=_RECOVERY_V2_EXACT_HEAD_CI_CYCLE_2_CORRECTION_RELEASE_CLAIM,
            base_release_date=active_release_date,
            observed_now=observed_now,
            expected_manifest=expected_manifest,
            expected_effect=expected_effect,
            expected_call_graph=expected_call_graph,
        )
        active_release = pr_b_release
        active_release_claim = _RECOVERY_V2_PR_B_RELEASE_CLAIM
        active_successors = release_suffix[1:]
    _validate_recovery_v2_release_graph(
        root,
        initial_release=initial_release,
        base_release=release,
        local_qa_failure=local_qa_failure,
        local_correction_release=local_correction_release,
        static_qa_failure=static_qa_failure,
        static_correction_release=static_correction_release,
        exact_head_ci_failure=exact_head_ci_failure,
        exact_head_ci_correction_release=exact_head_ci_correction_release,
        post_202_b101_failure=post_202_b101_failure,
        post_202_b101_correction_release=post_202_b101_correction_release,
        exact_head_ci_cycle_2_failure=exact_head_ci_cycle_2_failure,
        exact_head_ci_cycle_2_correction_release=exact_head_ci_cycle_2_correction_release,
        active_release=active_release,
        active_release_claim=active_release_claim,
        successors=active_successors,
    )
    return str(
        _validate_recovery_v2_council_successors(
            active_successors,
            root=root,
            release_id=str(active_release["decision_id"]),
            release_hash=str(active_release["hash"]),
            release_claim=active_release_claim,
            release_date=active_release_date,
            observed_now=observed_now,
            closure_phase=closure_phase,
        )
    )


def validate_data_torrent_recovery_v2_council_release(
    *,
    repository_root: Path | None = None,
    now: datetime | None = None,
) -> str:
    """Validate the pre-runtime release and reject every Council suffix."""

    return _validate_data_torrent_recovery_v2_council_release(
        repository_root=repository_root,
        now=now,
        closure_phase="PRE_RUNTIME",
    )


def validate_data_torrent_recovery_v2_phase_one_council_closure(
    *,
    repository_root: Path | None = None,
    now: datetime | None = None,
) -> str:
    """Validate the unique phase-one STAGE_FINISHED successor."""

    return _validate_data_torrent_recovery_v2_council_release(
        repository_root=repository_root,
        now=now,
        closure_phase="PHASE_ONE",
    )


def validate_data_torrent_recovery_v2_reservation_council_closure(
    *,
    repository_root: Path | None = None,
    now: datetime | None = None,
) -> str:
    """Validate the unique dual-intent STAGE_STARTED successor."""

    return _validate_data_torrent_recovery_v2_council_release(
        repository_root=repository_root,
        now=now,
        closure_phase="RESERVATION",
    )


def validate_data_torrent_recovery_v2_terminal_council_closure(
    *,
    repository_root: Path | None = None,
    now: datetime | None = None,
) -> str:
    """Validate the unique terminal PR-C closure without reopening any effect."""

    return _validate_data_torrent_recovery_v2_council_release(
        repository_root=repository_root,
        now=now,
        closure_phase="TERMINAL",
    )


def validate_data_torrent_authority(
    *,
    now: datetime | None = None,
    repository_root: Path | None = None,
) -> datetime:
    """Verify the immutable owner authority and its unexpired execution window."""

    root = (
        Path(os.path.abspath(Path(__file__))).parents[2]
        if repository_root is None
        else Path(os.path.abspath(repository_root))
    )
    manifest_path = root / "configs" / "execution" / "data-torrent-ready-v1.json"
    effect_path = (
        root / "configs" / "execution" / "data-torrent-ready-v1-controlled-go-effect-contract.json"
    )
    documents: list[dict[str, Any]] = []
    for path, expected_hash in (
        (manifest_path, DATA_TORRENT_MISSION_MANIFEST_SHA256),
        (effect_path, DATA_TORRENT_CONTROLLED_EFFECT_CONTRACT_SHA256),
    ):
        try:
            payload = _recovery_v2_read_bytes(
                path,
                repository_root=root,
                maximum_bytes=65_536,
            )
        except ChronosProductionError:
            raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_MISSING") from None
        if (
            not payload
            or len(payload) > 65_536
            or path.is_symlink()
            or not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), expected_hash)
        ):
            raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_HASH_MISMATCH")
        try:
            document = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_INVALID") from None
        if not isinstance(document, dict):
            raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_INVALID")
        documents.append(document)

    manifest, effect_contract = documents
    if set(manifest) != {
        "mission_id",
        "authorized_stages",
        "maximum_stage",
        "external_effects",
        "compute_budget",
        "time_budget",
        "source_hash",
        "expires_at",
    }:
        raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_INVALID")
    if (
        manifest.get("mission_id") != DATA_TORRENT_MISSION_ID
        or effect_contract.get("mission_id") != DATA_TORRENT_MISSION_ID
        or manifest.get("source_hash") != DATA_TORRENT_OWNER_DIRECTIVE_SHA256
        or effect_contract.get("owner_directive_source_sha256")
        != DATA_TORRENT_OWNER_DIRECTIVE_SHA256
        or effect_contract.get("parent_manifest_sha256") != DATA_TORRENT_MISSION_MANIFEST_SHA256
        or effect_contract.get("expands_parent_authority") is not False
        or effect_contract.get("expires_at") != manifest.get("expires_at")
        or effect_contract.get("one_shot_not_before") != DATA_TORRENT_ONE_SHOT_NOT_BEFORE
        or effect_contract.get("latest_effect_admission_at")
        != DATA_TORRENT_LATEST_EFFECT_ADMISSION_AT
        or effect_contract.get("maximum_effect_runtime_seconds")
        != DATA_TORRENT_MAXIMUM_EFFECT_RUNTIME_SECONDS
    ):
        raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_BINDING_MISMATCH")
    expiry = _authority_timestamp(manifest.get("expires_at"), field="expiry")
    not_before = _authority_timestamp(
        effect_contract.get("one_shot_not_before"), field="not_before"
    )
    admission_close = _authority_timestamp(
        effect_contract.get("latest_effect_admission_at"),
        field="effect_admission",
    )
    observed_now = datetime.now(UTC) if now is None else now
    if observed_now.tzinfo is None:
        raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_NOW_INVALID")
    observed_now = observed_now.astimezone(UTC)
    if (
        not_before >= admission_close
        or admission_close >= expiry
        or expiry - admission_close < timedelta(seconds=DATA_TORRENT_MAXIMUM_EFFECT_RUNTIME_SECONDS)
    ):
        raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_WINDOW_INVALID")
    if observed_now < not_before:
        raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_NOT_YET_ACTIVE")
    if observed_now >= expiry:
        raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_EXPIRED")
    if observed_now >= admission_close:
        raise ChronosProductionError("CHRONOS_MISSION_EFFECT_ADMISSION_CLOSED")
    return expiry


def validate_data_torrent_recovery_v2_authority(
    *,
    scale_stage: str,
    now: datetime | None = None,
    repository_root: Path | None = None,
    council_closure_phase: str = "PRE_RUNTIME",
) -> datetime:
    """Validate the byte-pinned Recovery V2 successor without touching V1."""

    if (
        scale_stage not in {"E1", "E2", "E3A", "E3B", "E4"}
        or council_closure_phase
        not in {"PRE_RUNTIME", "RESERVATION", "PHASE_ONE", "TERMINAL"}
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_STAGE_INVALID")
    root = (
        Path(os.path.abspath(Path(__file__))).parents[2]
        if repository_root is None
        else Path(os.path.abspath(repository_root))
    )
    _recovery_v2_require_no_reparse_chain(
        root,
        repository_root=root,
        allow_missing_leaf=False,
    )
    paths = (
        (
            root / "configs" / "execution" / "data-torrent-recovery-v2.json",
            DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256,
            DATA_TORRENT_RECOVERY_V2_MANIFEST_CANONICAL_SHA256,
        ),
        (
            root / "configs" / "execution" / "data-torrent-recovery-v2-effect-contract.json",
            DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_SHA256,
            DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_CANONICAL_SHA256,
        ),
    )

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        document: dict[str, object] = {}
        for key, value in pairs:
            if key in document:
                raise ValueError("duplicate JSON key")
            document[key] = value
        return document

    documents: list[dict[str, Any]] = []
    for path, raw_hash, canonical_hash in paths:
        try:
            payload = _recovery_v2_read_bytes(
                path,
                repository_root=root,
                maximum_bytes=65_536,
            )
        except ChronosProductionError:
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_AUTHORITY_MISSING") from None
        if (
            not payload
            or len(payload) > 65_536
            or path.is_symlink()
            or b"\r" in payload
            or payload.startswith(b"\xef\xbb\xbf")
            or not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), raw_hash)
        ):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_AUTHORITY_HASH_MISMATCH")
        try:
            decoded = json.loads(
                payload,
                object_pairs_hook=unique_object,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_AUTHORITY_INVALID") from None
        if not isinstance(decoded, dict):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_AUTHORITY_INVALID")
        canonical = json.dumps(
            decoded,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if not hmac.compare_digest(hashlib.sha256(canonical).hexdigest(), canonical_hash):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_AUTHORITY_HASH_MISMATCH")
        documents.append(cast(dict[str, Any], decoded))

    manifest, effect = documents
    manifest_fields = {
        "mission_id",
        "authorized_stages",
        "maximum_stage",
        "external_effects",
        "compute_budget",
        "time_budget",
        "source_hash",
        "expires_at",
    }
    if set(manifest) != manifest_fields:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_AUTHORITY_INVALID")
    effect_fields = {
        "schema_version",
        "mission_id",
        "start_sha",
        "parent_manifest_raw_sha256",
        "parent_manifest_canonical_sha256",
        "owner_directive_source_sha256",
        "authority_relationship",
        "expands_parent_authority",
        "old_v1_authority_reuse",
        "previous_activation",
        "activation_requirement",
        "one_shot_not_before",
        "latest_effect_admission_at",
        "maximum_effect_runtime_seconds",
        "github_workflow_enable_dispatch_disable_cycles_maximum",
        "controller_pre_effect_gate",
        "postmerge_workflow_quarantine",
        "pr_budget",
        "legacy_provider_branch_neutralization",
        "safe_v2_ci_budget",
        "pr_c_observer_protocol",
        "materializer_execution_reservations",
        "terminal_delivery_protocol",
        "postmerge_scope_trigger",
        "github_release_attestation_transport",
        "effect_stage_supervision",
        "one_shot_receipt_durability",
        "github_read_budgets",
        "stage_order",
        "scale_stage_mapping",
        "stage_timeout_minutes",
        "stage_entrypoints",
        "stage_effect_budgets",
        "neon_phase_totals",
        "r2_mission_totals",
        "required_schemas",
        "branch_inventory_failure_classes",
        "qa_gates",
        "terminal_artifacts",
        "forbidden_effects",
        "expires_at",
    }
    if set(effect) != effect_fields:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_AUTHORITY_INVALID")
    mapping_fields = (
        "previous_activation",
        "controller_pre_effect_gate",
        "postmerge_workflow_quarantine",
        "pr_budget",
        "legacy_provider_branch_neutralization",
        "safe_v2_ci_budget",
        "pr_c_observer_protocol",
        "materializer_execution_reservations",
        "terminal_delivery_protocol",
        "postmerge_scope_trigger",
        "github_release_attestation_transport",
        "effect_stage_supervision",
        "one_shot_receipt_durability",
        "github_read_budgets",
        "scale_stage_mapping",
        "stage_timeout_minutes",
        "stage_entrypoints",
        "stage_effect_budgets",
        "neon_phase_totals",
        "r2_mission_totals",
        "forbidden_effects",
    )
    list_fields = (
        "stage_order",
        "required_schemas",
        "branch_inventory_failure_classes",
        "qa_gates",
        "terminal_artifacts",
    )
    if any(not isinstance(effect.get(field), dict) for field in mapping_fields) or any(
        not isinstance(effect.get(field), list) for field in list_fields
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_AUTHORITY_INVALID")
    if (
        manifest.get("mission_id") != DATA_TORRENT_RECOVERY_V2_MISSION_ID
        or manifest.get("authorized_stages") != ["E1", "E2", "E3A", "E3B", "E4"]
        or manifest.get("maximum_stage") != "E4"
        or manifest.get("external_effects") != list(DATA_TORRENT_RECOVERY_V2_EXTERNAL_EFFECTS)
        or not _json_exact_equal(manifest.get("compute_budget"), 10_000_000)
        or not _json_exact_equal(
            manifest.get("time_budget"), DATA_TORRENT_RECOVERY_V2_TIME_BUDGET_SECONDS
        )
        or manifest.get("source_hash") != DATA_TORRENT_RECOVERY_V2_OWNER_DIRECTIVE_SHA256
        or effect.get("mission_id") != DATA_TORRENT_RECOVERY_V2_MISSION_ID
        or effect.get("start_sha") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or effect.get("parent_manifest_raw_sha256") != DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256
        or effect.get("parent_manifest_canonical_sha256")
        != DATA_TORRENT_RECOVERY_V2_MANIFEST_CANONICAL_SHA256
        or effect.get("owner_directive_source_sha256")
        != DATA_TORRENT_RECOVERY_V2_OWNER_DIRECTIVE_SHA256
        or effect.get("expands_parent_authority") is not False
        or effect.get("old_v1_authority_reuse") is not False
        or effect.get("schema_version") != "data-torrent-recovery-v2-effect-contract-v2"
        or effect.get("authority_relationship")
        != "BOUNDED_SUCCESSOR_EXECUTION_CONTRACT_WITHIN_PARENT_OWNER_AUTHORITY"
        or not _json_exact_equal(
            effect.get("previous_activation"),
            {
            "verdict": "FAIL_AND_STOP",
            "reason": "REQUIRED_SOURCE_MISSING",
            "git_writes": 0,
            "external_effects": 0,
            "production_effects": 0,
            "one_shot_effects": 0,
            },
        )
        or effect.get("activation_requirement")
        != "APPEND_ONLY_COUNCIL_AUTHORIZATION_EXACT_GREEN_FINAL_SHA_AND_IMMEDIATE_PREDECESSOR_PROOF"
        or effect.get("one_shot_not_before") != DATA_TORRENT_RECOVERY_V2_NOT_BEFORE
        or effect.get("latest_effect_admission_at")
        != DATA_TORRENT_RECOVERY_V2_LATEST_EFFECT_ADMISSION_AT
        or effect.get("maximum_effect_runtime_seconds")
        != DATA_TORRENT_RECOVERY_V2_MAXIMUM_EFFECT_RUNTIME_SECONDS
        or not _json_exact_equal(
            effect.get("github_workflow_enable_dispatch_disable_cycles_maximum"), 6
        )
        or not _json_exact_equal(
            effect.get("controller_pre_effect_gate"),
            {
            "path": "scripts/dispatch_data_torrent_recovery_v2_stage.py",
            "authority_guard_before_enable_and_dispatch": True,
            "full_hold_validations_before_enable": 2,
            "predecessor_attestation_and_semantic_validation_before_enable": True,
            "dispatch_ordinal_validation_before_enable": True,
            "final_main_ref_validation_before_enable": True,
            "pre_effect_proof_exact_schema": True,
            "pre_effect_proof_revalidated_in_mutation_child": True,
            "live_postmerge_holds_exact": 2,
            "live_postmerge_holds_identical": True,
            "github_run_id_decimal_digits_maximum": 18,
            "scope_guard_job_success_required": True,
            "mutation_order": ["ENABLE", "DISPATCH", "DISABLE"],
            "mutations_per_cycle": 3,
            "mutation_child_total_timeout_seconds": 15,
            "mutation_child_work_timeout_seconds": 11,
            "mutation_child_terminate_timeout_seconds": 2,
            "github_api_version": "2026-03-10",
            "dispatch_ref": "main",
            "dispatch_return_run_details": True,
            "dispatch_run_id_from_response": True,
            "terminal_run_observations_maximum": 3,
            "terminal_run_observations_are_retries": False,
            "terminal_artifact_attestation_gets_maximum": 3,
            "proxy_enabled": False,
            "redirects_enabled": False,
            "automatic_retries": 0,
            "disable_attempted_after_ambiguous_enable_or_dispatch": True,
            "disable_cleanup_target_allowlisted": True,
            "disable_cleanup_not_blocked_by_late_authority_or_lock_drift": True,
            "receipt_reservation_atomic_no_replace": True,
            "progress_receipt_atomic_replace": True,
            "receipt_file_fsync": True,
            "receipt_directory_ancestry_fsync": True,
            },
        )
        or not _json_exact_equal(
            effect.get("postmerge_workflow_quarantine"),
            {
            "scale_stage": "E1",
            "invocations": 1,
            "workflow_paths": [
                ".github/workflows/chronos-identity-seal-v2.yml",
                ".github/workflows/chronos-neon-branch-identity-v2.yml",
                ".github/workflows/chronos-production-bootstrap-v4.yml",
                ".github/workflows/data-torrent-live-v2.yml",
            ],
            "initial_states_allowed": ["active", "disabled_manually"],
            "github_api_gets_maximum": 25,
            "disable_attempts_maximum": 4,
            "enable_mutations": 0,
            "dispatch_mutations": 0,
            "automatic_retries": 0,
            "mutation_child_total_timeout_seconds": 15,
            "progress_receipt_before_each_disable": True,
            "stop_after_first_ambiguous_disable": False,
            "continue_each_distinct_initially_active_workflow_once": True,
            "second_invocation_refused_before_get": True,
            "proxy_enabled": False,
            "redirects_enabled": False,
            "phase_budget_fungible": False,
            "provider_neutralization_receipt_required": True,
            "receipt_path": ".torrent/release/recovery-v2-postmerge-quarantine.json",
            "receipt_authoritative_without_live_revalidation": False,
            "progress_receipt_atomic_replace": True,
            },
        )
        or not _json_exact_equal(
            effect.get("pr_budget"),
            {
            "engineering_required": 1,
            "engineering_conditional": 1,
            "terminal_evidence": 1,
            "total_maximum": 3,
            "one_open_at_a_time": True,
            "force_pushes": 0,
            "direct_pushes_to_main": 0,
            },
        )
        or not _json_exact_equal(
            effect.get("legacy_provider_branch_neutralization"),
            {
            "scale_stage": "E1",
            "branch": "codex/jalon-12-prospective-deep-data-observatory",
            "required_current_sha": DATA_TORRENT_RECOVERY_V2_START_SHA,
            "required_target": "EXACT_POSTMERGE_MAIN_SHA",
            "timing": "AFTER_POSTMERGE_SAFE_V2_GREEN_BEFORE_POSTMERGE_QUARANTINE",
            "authority_effect": "git_remote_write_non_force_within_successor_pr_budget",
            "delivery_slot": "ENGINEERING_REQUIRED",
            "controller_path": "scripts/dispatch_data_torrent_recovery_v2_stage.py",
            "receipt_path": ".torrent/release/recovery-v2-provider-neutralization.json",
            "live_hold_validations_exact": 2,
            "github_api_gets_maximum": 24,
            "github_reads_charged_to_delivery_slot": "ENGINEERING_REQUIRED",
            "remote_ref_observations_maximum": 2,
            "fast_forward_ancestry_check": True,
            "ordinary_non_force_push": True,
            "push_attempts_maximum": 1,
            "server_non_fast_forward_rejection_required": True,
            "updates_maximum": 1,
            "non_fast_forward_updates": 0,
            "force_pushes": 0,
            "branch_deletes": 0,
            "automatic_retries": 0,
            "progress_receipt_atomic_replace": True,
            },
        )
        or not _json_exact_equal(
            effect.get("safe_v2_ci_budget"),
            {
            "engineering_pull_requests_maximum": 2,
            "consolidated_exact_head_cycles_per_engineering_pr_maximum": 3,
            "engineering_exact_head_cycles_total_maximum": 6,
            "pr_c_phase_one_expected_hold_cycles": 1,
            "pr_c_candidate_exact_head_cycles": 1,
            "pr_c_postmerge_cycles": 1,
            "pr_c_cycles_total": 3,
            "failed_run_reruns": 0,
            "historical_ci_runs": 0,
            "phase_budgets_fungible": False,
            },
        )
        or not _json_exact_equal(
            effect.get("pr_c_observer_protocol"),
            {
            "entrypoint": "scripts/materialize_data_torrent_recovery_v2_delivery_evidence.py",
            "state_scope": "HOST_LOCAL_OS_STATE_OUTSIDE_WORKTREE",
            "state_namespace_root": (
                "RobinCouncilOS/dddur75__robin-stades-ng/data-torrent-recovery-v2/"
                f"{DATA_TORRENT_RECOVERY_V2_START_SHA}"
            ),
            "one_writer_host_pin_required": True,
            "expected_host_identity_sha256": (
                DATA_TORRENT_RECOVERY_V2_ONE_WRITER_HOST_SHA256
            ),
            "reservation_atomic_no_replace_before_first_get": True,
            "second_invocation_refused_before_get": True,
            "predecessor_result_raw_sha256_chain_required": True,
            "automatic_retries": 0,
            "poll_interval_seconds": 30,
            "maximum_runtime_seconds": 1_200,
            "run_inventory_status_filter_forbidden": True,
            "final_run_inventory_recheck_required": True,
            "final_run_inventory_rechecks_exact": 1,
            "state_files": {
                "C1": {
                    "reservation": "pr-c-c1-observer-reservation-v1.json",
                    "result": "pr-c-c1-observer-result-v1.json",
                },
                "C2": {
                    "reservation": "pr-c-c2-observer-reservation-v1.json",
                    "result": "pr-c-c2-observer-result-v1.json",
                },
                "POSTMERGE": {
                    "reservation": "pr-c-postmerge-observer-reservation-v1.json",
                    "result": "pr-c-postmerge-observer-result-v1.json",
                },
            },
            "phase_budgets_fungible": False,
            "phases": {
                "C1": {
                    "github_api_gets_maximum": 30,
                    "pull_request_gets_exact": 1,
                    "run_inventory_observations_minimum": 2,
                    "run_inventory_observations_maximum": 28,
                    "exact_run_jobs_gets_exact": 1,
                    "required_result": (
                        "ATTEMPT1_SCOPE_SUCCESS_TESTS_AND_GATE_FAILURE_RUN_FAILURE"
                    ),
                },
                "C2": {
                    "github_api_gets_maximum": 30,
                    "pull_request_gets_exact": 1,
                    "run_inventory_observations_minimum": 2,
                    "run_inventory_observations_maximum": 28,
                    "exact_run_jobs_gets_exact": 1,
                    "required_result": "ATTEMPT1_SCOPE_TESTS_GATE_AND_RUN_SUCCESS",
                },
                "POSTMERGE": {
                    "github_api_gets_maximum": 19,
                    "merged_pull_request_gets_exact": 1,
                    "run_inventory_observations_minimum": 2,
                    "run_inventory_observations_maximum": 18,
                    "exact_run_jobs_gets_exact": 0,
                    "required_result": "EXACT_MERGE_SHA_PUSH_MAIN_ATTEMPT1_SUCCESS",
                },
            },
            "delivery_requires_c1_result_before_first_external_read": True,
            "finalizer_requires_c1_c2_postmerge_results_before_first_external_read": True,
            "observer_results_authoritative": False,
            },
        )
        or not _json_exact_equal(
            effect.get("materializer_execution_reservations"),
            {
            "state_scope": "HOST_LOCAL_OS_STATE_OUTSIDE_WORKTREE",
            "state_namespace_root": (
                "RobinCouncilOS/dddur75__robin-stades-ng/data-torrent-recovery-v2/"
                f"{DATA_TORRENT_RECOVERY_V2_START_SHA}"
            ),
            "one_writer_host_pin_required": True,
            "expected_host_identity_sha256": (
                DATA_TORRENT_RECOVERY_V2_ONE_WRITER_HOST_SHA256
            ),
            "atomic_no_replace_before_first_external_read": True,
            "terminal_namespace": "terminal-materializer-execution-reservation-v1.json",
            "delivery_namespace": "delivery-materializer-execution-reservation-v1.json",
            "terminal_remote_reads_conservatively_consumed": 14,
            "delivery_remote_reads_conservatively_consumed_maximum": 8,
            "automatic_retries": 0,
            "second_invocation_allowed": False,
            "local_receipts_authoritative": False,
            },
        )
        or not _json_exact_equal(
            effect.get("terminal_delivery_protocol"),
            {
            "council_chain": [
                "C0_STAGE_STARTED_RESERVATION",
                "C1_STAGE_FINISHED_RUNTIME_EVIDENCE",
                "C2_DECISION_TERMINAL_CANDIDATE",
            ],
            "pr_c_commits_exact": 3,
            "pr_c_non_force_pushes_exact": 3,
            "pr_c_force_pushes": 0,
            "pr_c_pull_request_writes": {
                "create": 1,
                "ready_for_review": 0,
                "total": 1,
            },
            "phase_one_gate": {
                "terminal_candidate_complete": False,
                "scope_job_conclusion": "success",
                "tests_job_conclusion": "failure",
                "run_conclusion": "failure",
                "expected_hold_not_rerun": True,
            },
            "candidate_gate": {
                "terminal_candidate_complete": True,
                "scope_job_conclusion": "success",
                "tests_job_conclusion": "success",
                "run_conclusion": "success",
            },
            "postmerge_final_gate": _recovery_v2_postmerge_final_gate_definition(root),
            },
        )
        or not _json_exact_equal(
            effect.get("postmerge_scope_trigger"),
            {
            "pull_request_head_ref": "codex/data-torrent-recovery-v2",
            "event_name": "push",
            "ref": "refs/heads/main",
            "merge_method": "merge",
            "merge_commit_subject_prefix": "[DATA_TORRENT_RECOVERY_V2] ",
            "merge_commit_subjects": [
                "[DATA_TORRENT_RECOVERY_V2] PR-A",
                "[DATA_TORRENT_RECOVERY_V2] PR-B",
                "[DATA_TORRENT_RECOVERY_V2] PR-C",
            ],
            "merge_commit_body": "",
            "merge_commit_parent_count": 2,
            "first_parent_binding": "github.event.before",
            "auto_merge": False,
            "squash": False,
            "rebase": False,
            "force": False,
            },
        )
        or not _json_exact_equal(
            effect.get("github_release_attestation_transport"),
            {
            "api_host": "api.github.com",
            "artifact_download_host_suffixes": [
                ".actions.githubusercontent.com",
                ".blob.core.windows.net",
            ],
            "private_process": True,
            "maximum_response_bytes": 10_485_760,
            "child_total_timeout_seconds": 65,
            "child_work_timeout_seconds": 55,
            "child_terminate_timeout_seconds": 5,
            "proxy_enabled": False,
            "automatic_redirects_enabled": False,
            "validated_artifact_redirects_maximum": 1,
            "automatic_retries": 0,
            "ambient_gh_api_calls_in_v2_production_workflows": 0,
            "exact_main_reads_in_v2_production_workflows": 10,
            "github_run_id_decimal_digits_maximum": 18,
            },
        )
        or not _json_exact_equal(
            effect.get("effect_stage_supervision"),
            {
            "helper_path": "scripts/recovery_v2_supervision.py",
            "deadline_environment": "RECOVERY_V2_EFFECT_DEADLINE_EPOCH",
            "fallback_precreated_before_checkout_setup_or_validation": True,
            "fallback_path_root": "RUNNER_TEMP",
            "fallback_precreated_before_child": True,
            "fallback_adoption_byte_exact": True,
            "pre_effect_failure_upload_always": True,
            "candidate_output_separate": True,
            "candidate_file_fsync_before_promotion": True,
            "promotion_atomic_after_validation": True,
            "promotion_directory_fsync": True,
            "success_requires_child_exit_zero_and_semantic_validation": True,
            "failure_export_sanitized": True,
            "child_process_group": True,
            "terminate_grace_seconds": 5,
            "kill_grace_seconds": 5,
            "finalization_margin_seconds": 20,
            "workflow_effect_deadline_seconds_maximum": {
                "RECOVERY_IDENTITY_V2": 600,
                "DURABLE_IDENTITY_SEAL_V2": 600,
                "PRODUCTION_PREFLIGHT_V2": 900,
                "MIGRATE_0015": 900,
                "VERIFY_0015": 900,
                "LIVE_ONCE": 1_200,
            },
            "post_effect_workflow_terminal_grace_seconds": {
                "RECOVERY_IDENTITY_V2": 630,
                "DURABLE_IDENTITY_SEAL_V2": 630,
                "PRODUCTION_PREFLIGHT_V2": 930,
                "MIGRATE_0015": 930,
                "VERIFY_0015": 930,
                "LIVE_ONCE": 1_230,
            },
            "terminal_status_propagation_margin_seconds": 30,
            "terminal_artifact_attestation_reserve_seconds": 210,
            "controller_terminalization_deadline_is_authority_bounded": True,
            "controller_terminalization_deadline_dispatched_to_workflow": False,
            "terminalization_completed_at_definition": (
                "REMOTE_TERMINALIZER_RETURNED_AND_TERMINAL_SEMANTICS_AND_LOCAL_CACHE_VALIDATED"
            ),
            "terminalization_completed_at_sampled_before_local_success_receipt_publication": True,
            "local_success_receipt_publication_is_external_authority": False,
            "terminalization_completion_must_not_exceed_controller_deadline": True,
            "latest_effect_admission_is_global_ceiling_not_full_cycle_guarantee": True,
            "stage_full_cycle_latest_admission_at": {
                "RECOVERY_IDENTITY_V2": "2026-09-06T12:22:58Z",
                "DURABLE_IDENTITY_SEAL_V2": "2026-09-06T12:22:58Z",
                "PRODUCTION_PREFLIGHT_V2": "2026-09-06T12:12:58Z",
                "MIGRATE_0015": "2026-09-06T12:12:58Z",
                "VERIFY_0015": "2026-09-06T12:12:58Z",
                "LIVE_ONCE": "2026-09-06T12:02:58Z",
            },
            "post_effect_closure_effects": [
                "github_artifact_upload",
                "github_workflow_terminal_state",
            ],
            "post_effect_production_api_calls_allowed": 0,
            "nonterminal_after_controller_deadline": "FAIL_AND_STOP_NO_RETRY",
            "outer_timeout_reserve_seconds": 120,
            "child_timeout_seconds_maximum": {
                "RECOVERY_IDENTITY_V2": 110,
                "DURABLE_IDENTITY_SEAL_V2": 480,
                "PRODUCTION_PREFLIGHT_V2": 780,
                "MIGRATE_0015": 780,
                "VERIFY_0015": 780,
                "LIVE_ONCE": 1_080,
            },
            "automatic_retries": 0,
            },
        )
        or not _json_exact_equal(
            effect.get("one_shot_receipt_durability"),
            {
            "writer_paths": [
                "scripts/dispatch_data_torrent_recovery_v2_stage.py",
                "scripts/install_chronos_runtime_bindings_v2.py",
                "scripts/recovery_v2_supervision.py",
                "scripts/materialize_data_torrent_recovery_v2_terminal_evidence.py",
                "scripts/materialize_data_torrent_recovery_v2_delivery_evidence.py",
                "scripts/verify_data_torrent_recovery_v2_postmerge_gate.py",
            ],
            "same_parent_candidate": True,
            "exclusive_target_publication": "CANDIDATE_FSYNC_HARDLINK_NO_REPLACE",
            "update_publication": "CANDIDATE_FSYNC_ATOMIC_REPLACE",
            "parent_identity_revalidated_before_and_after_publication": True,
            "repository_root_anchored_parent_walk": True,
            "temporary_candidates_within_verified_parent": True,
            "posix_parent_descriptor_held_across_publication": True,
            "windows_target_handle_identity_revalidated_after_publication": True,
            "directory_bundle_expected_hashset_revalidated_before_publication": True,
            "reparse_chain_rejected": True,
            "directory_ancestry_fsync": True,
            "unsafe_recursive_cleanup": False,
            "automatic_retries": 0,
            },
        )
        or not _json_exact_equal(
            effect.get("github_read_budgets"),
            {
            "execution_stages": {
                "RECOVERY_IDENTITY_V2": 22,
                "DURABLE_IDENTITY_SEAL_V2": 25,
                "PRODUCTION_PREFLIGHT_V2": 36,
                "FOUR_RUNTIME_BINDINGS": 55,
                "MIGRATE_0015": 33,
                "VERIFY_0015": 33,
                "LIVE_ONCE": 28,
                "REPLAY_100": 0,
            },
            "execution_stages_total_maximum": 232,
            "controller_cycles": {
                "RECOVERY_IDENTITY_V2": 32,
                "DURABLE_IDENTITY_SEAL_V2": 32,
                "PRODUCTION_PREFLIGHT_V2": 32,
                "MIGRATE_0015": 32,
                "VERIFY_0015": 32,
                "LIVE_ONCE": 32,
            },
            "controller_cycles_total_maximum": 192,
            "delivery_slots": {
                "ENGINEERING_REQUIRED": 136,
                "ENGINEERING_CONDITIONAL": 136,
                "TERMINAL_EVIDENCE": 136,
            },
            "terminal_evidence_delivery_breakdown": {
                "runtime_close_gets_exact": 13,
                "delivery_observation_gets_maximum": 7,
                "pr_c_c1_status_observation_gets_maximum": 30,
                "pr_c_c2_status_observation_gets_maximum": 30,
                "postmerge_run_observation_gets_maximum": 19,
                "postmerge_final_gate_gets_exact": 34,
                "accounted_total_maximum": 133,
                "slot_maximum": 136,
                "unused_headroom": 3,
                "phase_budget_fungible": False,
            },
            "delivery_slots_total_maximum": 408,
            "engineering_required_delivery_breakdown": {
                "pull_request_and_safe_v2_reads_maximum": 112,
                "provider_pre_hold_gets_maximum": 12,
                "provider_post_hold_gets_maximum": 12,
                "total_maximum": 136,
                "phase_budget_fungible": False,
            },
            "postmerge_quarantine": 25,
            "artifact_downloads": {
                "execution_stages_maximum": 8,
                "controller_cycles_maximum": 6,
                "delivery_slots_maximum": 12,
                "mission_total_maximum": 26,
                "phase_budgets_fungible": False,
            },
            "mission_total_maximum": 857,
            "phase_budgets_fungible": False,
            "unclassified_github_reads": 0,
            "automatic_read_retries": 0,
            "actions_checkout_internal_traffic_counted": False,
            },
        )
        or effect.get("stage_order")
        != [
            "LEGACY_PROVIDER_BRANCH_NEUTRALIZATION",
            "POSTMERGE_QUARANTINE",
            "RECOVERY_IDENTITY_V2",
            "DURABLE_IDENTITY_SEAL_V2",
            "PRODUCTION_PREFLIGHT_V2",
            "FOUR_RUNTIME_BINDINGS",
            "MIGRATE_0015",
            "VERIFY_0015",
            "LIVE_ONCE",
            "REPLAY_100",
        ]
        or effect.get("scale_stage_mapping")
        != {
            "E1": [
                "ENGINEERING_AND_INDEPENDENT_QA",
                "LEGACY_PROVIDER_BRANCH_NEUTRALIZATION",
                "POSTMERGE_QUARANTINE",
            ],
            "E2": ["RECOVERY_IDENTITY_V2", "DURABLE_IDENTITY_SEAL_V2"],
            "E3A": ["PRODUCTION_PREFLIGHT_V2", "FOUR_RUNTIME_BINDINGS"],
            "E3B": ["MIGRATE_0015", "VERIFY_0015"],
            "E4": ["LIVE_ONCE", "REPLAY_100"],
        }
        or not _json_exact_equal(
            effect.get("stage_timeout_minutes"),
            {
                "LEGACY_PROVIDER_BRANCH_NEUTRALIZATION": 5,
                "POSTMERGE_QUARANTINE": 5,
                "RECOVERY_IDENTITY_V2": 10,
                "DURABLE_IDENTITY_SEAL_V2": 10,
                "PRODUCTION_PREFLIGHT_V2": 15,
                "FOUR_RUNTIME_BINDINGS": 10,
                "MIGRATE_0015": 15,
                "VERIFY_0015": 15,
                "LIVE_ONCE": 20,
                "REPLAY_100": 20,
            },
        )
        or effect.get("expires_at") != manifest.get("expires_at")
        or scale_stage not in cast(dict[str, object], effect.get("scale_stage_mapping", {}))
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_AUTHORITY_BINDING_MISMATCH")
    entrypoints = cast(dict[str, Any], effect["stage_entrypoints"])
    budgets = cast(dict[str, Any], effect["stage_effect_budgets"])
    if set(budgets) != {
        "LEGACY_PROVIDER_BRANCH_NEUTRALIZATION",
        "POSTMERGE_QUARANTINE",
        "RECOVERY_IDENTITY_V2",
        "DURABLE_IDENTITY_SEAL_V2",
        "PRODUCTION_PREFLIGHT_V2",
        "FOUR_RUNTIME_BINDINGS",
        "MIGRATE_0015",
        "VERIFY_0015",
        "LIVE_ONCE",
        "REPLAY_100",
    } or any(not isinstance(value, dict) for value in budgets.values()):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_EFFECT_CONTRACT_INVALID")
    budget_type_signature = {
        stage: {field: type(value).__name__ for field, value in budget.items()}
        for stage, budget in budgets.items()
    }
    if not hmac.compare_digest(
        hashlib.sha256(canonical_json_bytes(budget_type_signature)).hexdigest(),
        "cfafb15b449f9c5bd6a8ea5332f0dcabb76a17c7d5a367ee3049800622ae743b",
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_EFFECT_CONTRACT_INVALID")
    provider_neutralization = cast(dict[str, Any], budgets["LEGACY_PROVIDER_BRANCH_NEUTRALIZATION"])
    quarantine = cast(dict[str, Any], budgets["POSTMERGE_QUARANTINE"])
    identity = cast(dict[str, Any], budgets["RECOVERY_IDENTITY_V2"])
    seal = cast(dict[str, Any], budgets["DURABLE_IDENTITY_SEAL_V2"])
    preflight = cast(dict[str, Any], budgets["PRODUCTION_PREFLIGHT_V2"])
    live = cast(dict[str, Any], budgets.get("LIVE_ONCE", {}))
    replay = cast(dict[str, Any], budgets.get("REPLAY_100", {}))
    bindings = cast(dict[str, Any], budgets.get("FOUR_RUNTIME_BINDINGS", {}))
    migrate = cast(dict[str, Any], budgets.get("MIGRATE_0015", {}))
    verify = cast(dict[str, Any], budgets.get("VERIFY_0015", {}))
    replay_zero_fields = (
        "postgresql_connections",
        "sql_statements",
        "neon_operations",
        "r2_operations",
        "official_reads",
        "provider_requests",
        "secret_writes",
        "purchases",
        "bet_calls",
        "automatic_retries",
        "external_effects",
    )
    required_schemas = [
        "github-artifact-attestation-v2",
        "neon-branch-identity-go-v2",
        "durable-identity-seal-v2",
        "production-preflight-v2",
        "chronos-runtime-bindings-v2",
        "chronos-production-migrate-v2",
        "chronos-production-verify-v2",
        "robin-data-torrent-live-config-v2",
        "robin-data-torrent-live-runtime-effects-v1",
        "robin-data-torrent-real-batch-manifest-v1",
        "robin-data-torrent-normalized-evidence-binding-v2",
        "robin-data-torrent-load-replay-report-v1",
        "robin-data-torrent-terminal-semantic-qa-v2",
        "data-torrent-recovery-v2-final-gate-witness-v1",
        "data-torrent-recovery-v2-postmerge-final-gate-v1",
    ]
    expected_entrypoints = {
        "LEGACY_PROVIDER_BRANCH_NEUTRALIZATION": {
            "kind": "LOCAL_SINGLE_INVOCATION",
            "path": "scripts/dispatch_data_torrent_recovery_v2_stage.py",
            "mode": "PROVIDER_NEUTRALIZATION",
        },
        "POSTMERGE_QUARANTINE": {
            "kind": "LOCAL_SINGLE_INVOCATION",
            "path": "scripts/dispatch_data_torrent_recovery_v2_stage.py",
            "mode": "POSTMERGE_QUARANTINE",
        },
        "RECOVERY_IDENTITY_V2": {
            "kind": "GITHUB_WORKFLOW",
            "path": ".github/workflows/chronos-neon-branch-identity-v2.yml",
            "mode": "IDENTITY",
        },
        "DURABLE_IDENTITY_SEAL_V2": {
            "kind": "GITHUB_WORKFLOW",
            "path": ".github/workflows/chronos-identity-seal-v2.yml",
            "mode": "SEAL",
        },
        "PRODUCTION_PREFLIGHT_V2": {
            "kind": "GITHUB_WORKFLOW",
            "path": ".github/workflows/chronos-production-bootstrap-v4.yml",
            "mode": "PREFLIGHT",
        },
        "FOUR_RUNTIME_BINDINGS": {
            "kind": "LOCAL_SINGLE_INVOCATION",
            "path": "scripts/install_chronos_runtime_bindings_v2.py",
            "mode": "INSTALL",
        },
        "MIGRATE_0015": {
            "kind": "GITHUB_WORKFLOW",
            "path": ".github/workflows/chronos-production-bootstrap-v4.yml",
            "mode": "MIGRATE",
        },
        "VERIFY_0015": {
            "kind": "GITHUB_WORKFLOW",
            "path": ".github/workflows/chronos-production-bootstrap-v4.yml",
            "mode": "VERIFY",
        },
        "LIVE_ONCE": {
            "kind": "GITHUB_WORKFLOW",
            "path": ".github/workflows/data-torrent-live-v2.yml",
            "mode": "LIVE",
        },
        "REPLAY_100": {
            "kind": "IN_PROCESS_LOCAL_ONLY",
            "path": "src/robin/data_torrent/runtime.py",
            "mode": "REPLAY",
            "parent_stage": "LIVE_ONCE",
            "separate_dispatches": 0,
        },
    }
    secret_names = [
        "CHRONOS_AUTHORITY_DATABASE_URL",
        "CHRONOS_RUNTIME_DATABASE_URL",
        "CHRONOS_READER_DATABASE_URL",
        "CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
    ]
    expected_failure_classes = [
        "NONE",
        "COUNT_CONTRACT_INVALID",
        "COUNT_DRIFT",
        "COUNT_OVERFLOW",
        "COUNT_NOT_REACHED_NO_NEXT",
        "NEXT_INVALID",
        "EMPTY_PAGE_BEFORE_COUNT",
        "PAGE_REPEAT",
        "CURSOR_CYCLE",
        "PAGE_LIMIT",
        "ITEM_LIMIT",
        "BRANCH_CONTRACT_INVALID",
        "DUPLICATE_BRANCH_ID",
        "PROJECT_MISMATCH",
        "DEFAULT_BRANCH_CONTRADICTION",
        "DSN_BRANCH_CONTRADICTION",
        "BRANCH_ENDPOINT_CONTRADICTION",
        "BUDGET_EXHAUSTED",
        "TRANSPORT_AMBIGUOUS",
    ]
    expected_qa_gates = [
        "baseline_identity",
        "cross_run_claim",
        "loser_replay_no_reads",
        "migration_rbac",
        "production_bindings",
        "ordering_one_shot",
        "ledger_caps",
        "forbidden_effects",
        "secret_safety",
        "temporal_safety",
        "scope_horizon",
        "official_breadth",
        "odds_breadth",
        "raw_durability",
        "normalization_lineage",
        "fixture_mapping_coverage",
        "replay",
        "load",
        "artifact_closure",
        "ops_recovery_science",
        "ci_merge_postmerge",
        "qa_terminal",
    ]
    expected_terminal_artifacts = [
        "torrent-real-batch-manifest-v1.json",
        "torrent-real-batch-raw-index-v1.json",
        "torrent-real-batch-normalized-index-v1.json",
        "torrent-real-batch-quality-report-v1.json",
        "torrent-real-batch-coverage-matrix-v1.csv",
        "torrent-load-replay-report-v1.json",
        "torrent-load-replay-report-v1.md",
        "torrent-opportunity-claim-receipt-v1.json",
        "torrent-control-plane-event-chain-v1.json",
        "torrent-official-read-receipts-v1.json",
        "torrent-provider-credit-receipt-v1.json",
        "torrent-r2-inventory-v1.json",
        "torrent-raw-to-normalized-lineage-v1.json",
        "torrent-canonical-dataset-hash-v1.json",
        "torrent-qa-acceptance-matrix-v1.json",
        "robin-data-torrent-operations-pack-v1.md",
        "robin-data-torrent-recovery-pack-v1.md",
        "hypothesis-ready-field-dictionary-v1.json",
        "hypothesis-backlog-from-real-data-v1.md",
    ]
    if (
        not _json_exact_equal(entrypoints, expected_entrypoints)
        or not _json_exact_equal(
            provider_neutralization,
            {
            "invocations": 1,
            "github_api_gets_maximum": 24,
            "github_reads_charged_to_delivery_slot": "ENGINEERING_REQUIRED",
            "git_remote_ref_observations_maximum": 2,
            "git_push_attempts_maximum": 1,
            "git_ref_updates_maximum": 1,
            "non_fast_forward_updates": 0,
            "branch_deletes": 0,
            "automatic_retries": 0,
            "phase_budget_fungible": False,
            },
        )
        or not _json_exact_equal(
            quarantine,
            {
            "invocations": 1,
            "github_api_gets_maximum": 25,
            "workflow_disable_attempts_maximum": 4,
            "workflow_enable_mutations": 0,
            "workflow_dispatch_mutations": 0,
            "automatic_retries": 0,
            "phase_budget_fungible": False,
            },
        )
        or identity.get("dispatches") != 1
        or identity.get("run_attempt") != 1
        or identity.get("neon_gets_maximum") != 25
        or identity.get("neon_post") != 0
        or identity.get("neon_patch") != 0
        or identity.get("neon_delete") != 0
        or identity.get("automatic_retries") != 0
        or seal.get("dispatches") != 1
        or seal.get("run_attempt") != 1
        or seal.get("r2_puts") != 1
        or seal.get("r2_gets") != 1
        or seal.get("r2_objects") != 1
        or seal.get("r2_lists") != 0
        or seal.get("r2_deletes") != 0
        or seal.get("r2_overwrites") != 0
        or seal.get("automatic_retries") != 0
        or preflight.get("dispatches") != 1
        or preflight.get("run_attempt") != 1
        or preflight.get("r2_gets") != 1
        or preflight.get("neon_gets_maximum") != 39
        or preflight.get("neon_posts_maximum") != 1
        or preflight.get("neon_patch") != 0
        or preflight.get("neon_delete") != 0
        or preflight.get("postgresql_connections_pre_0015") != 3
        or preflight.get("postgresql_connections_at_0015") != 4
        or preflight.get("sql_statements_maximum") != 128
        or preflight.get("sql_writes") != 0
        or preflight.get("automatic_retries") != 0
        or bindings.get("invocations") != 1
        or bindings.get("secret_writes") != 4
        or bindings.get("successful_secret_writes") != 4
        or bindings.get("other_secret_writes") != 0
        or bindings.get("secret_names_in_order") != secret_names
        or bindings.get("secret_value_readbacks") != 0
        or bindings.get("secret_value_logging") != 0
        or bindings.get("global_hold_full_validations") != 2
        or bindings.get("concurrent_run_inventory_validations") != 4
        or bindings.get("github_api_gets_maximum") != 55
        or bindings.get("secret_public_key_gets_per_write_maximum") != 1
        or bindings.get("github_cli_version") != "2.96.0"
        or bindings.get("github_cli_windows_amd64_executable_sha256")
        != "cd79f16203f1fbe56937c4c96e2b6eadd10549418dcb241d91576ac77af0ac8b"
        or bindings.get("terminal_main_ref_validation_after_first_full_hold") is not True
        or bindings.get("preflight_run_id_decimal_digits_maximum") != 18
        or bindings.get("secret_put_private_process") is not True
        or bindings.get("secret_put_child_total_timeout_seconds") != 15
        or bindings.get("secret_put_child_work_timeout_seconds") != 10
        or bindings.get("secret_put_child_terminate_timeout_seconds") != 2
        or bindings.get("reservation_effect_counter_certainty")
        != "CONSERVATIVE_UPPER_BOUNDS"
        or bindings.get("reservation_secret_writes_attempted_upper_bound") != 4
        or bindings.get("reservation_secret_writes_confirmed_upper_bound") != 4
        or bindings.get("reservation_atomic_no_replace") is not True
        or bindings.get("final_receipt_atomic_replace") is not True
        or bindings.get("receipt_directory_ancestry_fsync") is not True
        or bindings.get("attestation_bounded_by_stage_outer_deadline") is not True
        or bindings.get("preflight_expiry_revalidated_after_each_concurrency_inventory")
        is not True
        or bindings.get("preflight_and_effect_deadline_revalidated_after_encryption")
        is not True
        or bindings.get("secret_put_child_revalidates_external_deadline") is not True
        or bindings.get("effect_admission_deadline_seconds") != 480
        or bindings.get("stage_outer_timeout_seconds") != 600
        or bindings.get("automatic_retries") != 0
        or "dispatches" in bindings
        or "run_attempt" in bindings
        or migrate.get("github_workflow_dispatches") != 1
        or migrate.get("migration_execution_dispatches_if_absent") != 1
        or migrate.get("migration_execution_dispatches_if_present") != 0
        or migrate.get("neon_authority_validation_gets_maximum") != 26
        or migrate.get("neon_mutations") != 0
        or migrate.get("postgresql_connection_attempts_additional_maximum") != 4
        or migrate.get("postgresql_connection_attempts_total_maximum") != 10
        or migrate.get("sql_statements_maximum") != 2_048
        or migrate.get("sql_writes_maximum") != 1_024
        or migrate.get("postgresql_drop_statements") != 0
        or migrate.get("retained_neutralized_bootstrap_executors") != 1
        or migrate.get("bootstrap_executor_terminal_state")
        != "NOLOGIN_PASSWORD_NULL_NO_MEMBERSHIPS_NO_CHRONOS_FUNCTIONAL_PRIVILEGES_NO_SESSIONS"
        or migrate.get("authorized_revision") != "0015_data_torrent_opportunity"
        or migrate.get("automatic_retries") != 0
        or verify.get("dispatches") != 1
        or verify.get("run_attempt") != 1
        or verify.get("postgresql_connections") != 4
        or verify.get("sql_statements_maximum") != 128
        or verify.get("sql_writes") != 0
        or verify.get("neon_operations") != 0
        or verify.get("r2_operations") != 0
        or verify.get("provider_calls") != 0
        or verify.get("automatic_retries") != 0
        or live.get("leagues") != 5
        or live.get("markets") != ["h2h", "totals"]
        or live.get("official_physical_reads_maximum") != 50
        or live.get("odds_provider_requests_on_success") != 5
        or live.get("odds_credits_maximum") != 1_000
        or live.get("r2_gets") != 1
        or live.get("r2_puts") != 2
        or live.get("r2_objects") != 2
        or live.get("r2_lists") != 0
        or live.get("r2_deletes") != 0
        or live.get("r2_overwrites") != 0
        or live.get("r2_retries") != 0
        or live.get("official_retries") != 0
        or live.get("provider_retries") != 0
        or live.get("postgresql_call_graph_path")
        != "configs/execution/data-torrent-live-v2-postgresql-call-graph.json"
        or live.get("postgresql_call_graph_raw_sha256")
        != DATA_TORRENT_LIVE_V2_POSTGRESQL_CALL_GRAPH_SHA256
        or live.get("postgresql_call_graph_canonical_sha256")
        != DATA_TORRENT_LIVE_V2_POSTGRESQL_CALL_GRAPH_CANONICAL_SHA256
        or live.get("postgresql_direct_read_connections") != 6
        or live.get("postgresql_function_read_connections_nominal") != 4
        or live.get("postgresql_function_read_transition_fallback_connections_maximum") != 2
        or live.get("postgresql_mutating_function_connections") != 41
        or live.get("postgresql_connection_attempts_nominal") != 51
        or live.get("postgresql_connection_attempts_maximum") != 53
        or live.get("postgresql_first_refused_attempt") != 54
        or live.get("postgresql_connection_retries") != 0
        or live.get("terminal_response_observation_within_capture_window") is not True
        or live.get("terminal_operation_clock_skew_seconds_maximum") != 5
        or live.get("terminal_generated_chronology")
        != (
            "LATEST_RETRIEVED_LE_RAW_INDEX_LE_CAPTURE_END_LE_REPLAY_LE_QUALITY_LE_"
            "NORMALIZED_LE_QA_LE_MANIFEST"
        )
        or live.get("terminal_source_request_contracts_reconstructed") is not True
        or live.get("terminal_response_header_allowlist_revalidated") is not True
        or live.get("terminal_official_url_allowlist_revalidated") is not True
        or live.get("purchases") != 0
        or live.get("bet_calls") != 0
        or replay.get("iterations_exact") != 100
        or replay.get("raw_durable_terminal_event") != "CREATED_CONFIRMED"
        or replay.get("normalized_durable_terminal_event") != "CREATED_CONFIRMED"
        or any(replay.get(field) != 0 for field in replay_zero_fields)
        or not _json_exact_equal(
            effect.get("neon_phase_totals"),
            {
            "recovery_identity_gets_maximum": 25,
            "preflight_gets_maximum": 39,
            "migrate_authority_validation_gets_maximum": 26,
            "mission_gets_maximum": 90,
            "phase_budgets_fungible": False,
            },
        )
        or not _json_exact_equal(
            effect.get("r2_mission_totals"),
            {
            "puts": 3,
            "gets": 3,
            "objects": 3,
            "lists": 0,
            "deletes": 0,
            "overwrites": 0,
            "retries": 0,
            },
        )
        or effect.get("required_schemas") != required_schemas
        or effect.get("branch_inventory_failure_classes") != expected_failure_classes
        or effect.get("qa_gates") != expected_qa_gates
        or effect.get("terminal_artifacts") != expected_terminal_artifacts
        or not _json_exact_equal(
            effect.get("forbidden_effects"),
            {
            "hypotheses_generated": 0,
            "purchases": 0,
            "real_bets": 0,
            "edge_promotions": 0,
            "social_publications": 0,
            "r2_deletes": 0,
            "r2_overwrites": 0,
            "neon_patch": 0,
            "neon_delete": 0,
            "postgresql_drop_statements": 0,
            "historical_run_reruns": 0,
            "automatic_retries_after_ambiguous_effect": 0,
            },
        )
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_EFFECT_CONTRACT_INVALID")
    expiry = _authority_timestamp(manifest.get("expires_at"), field="recovery_v2_expiry")
    not_before = _authority_timestamp(
        effect.get("one_shot_not_before"), field="recovery_v2_not_before"
    )
    admission_close = _authority_timestamp(
        effect.get("latest_effect_admission_at"), field="recovery_v2_effect_admission"
    )
    observed_now = datetime.now(UTC) if now is None else now
    if observed_now.tzinfo is None:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_AUTHORITY_NOW_INVALID")
    observed_now = observed_now.astimezone(UTC)
    budget_deadline = min(
        expiry,
        not_before + timedelta(seconds=DATA_TORRENT_RECOVERY_V2_TIME_BUDGET_SECONDS),
    )
    if (
        not_before >= admission_close
        or admission_close > budget_deadline
        or budget_deadline - admission_close
        < timedelta(seconds=DATA_TORRENT_RECOVERY_V2_MAXIMUM_EFFECT_RUNTIME_SECONDS)
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_AUTHORITY_WINDOW_INVALID")
    if observed_now < not_before:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_AUTHORITY_NOT_YET_ACTIVE")
    if observed_now >= expiry:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_AUTHORITY_EXPIRED")
    if observed_now >= budget_deadline:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_TIME_BUDGET_EXHAUSTED")
    if observed_now >= admission_close:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_EFFECT_ADMISSION_CLOSED")
    if scale_stage != "E1":
        _validate_data_torrent_recovery_v2_council_release(
            repository_root=root,
            now=observed_now,
            closure_phase=council_closure_phase,
        )
    return budget_deadline


def assert_production_safety_locks(environment: Mapping[str, str]) -> None:
    invalid = [
        name
        for name, expected in PRODUCTION_SAFETY_LOCKS.items()
        if environment.get(name, "").strip().lower() != expected
    ]
    if invalid:
        raise ChronosProductionError(f"CHRONOS_PRODUCTION_SAFETY_LOCK_MISMATCH:{','.join(invalid)}")


def require_sha(value: str, *, field: str) -> str:
    """Require a Git SHA without retaining an unsafe value in the error."""

    if _HEX_40.fullmatch(value) is None:
        raise ChronosProductionError(f"CHRONOS_{field.upper()}_INVALID")
    return value


def require_hash(value: str, *, field: str) -> str:
    if _HEX_64.fullmatch(value) is None:
        raise ChronosProductionError(f"CHRONOS_{field.upper()}_INVALID")
    return value


def require_identifier(value: str, *, field: str) -> str:
    if _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise ChronosProductionError(f"CHRONOS_{field.upper()}_INVALID")
    return value


@dataclass(frozen=True, slots=True)
class DirectPostgresTarget:
    """Non-secret connection metadata approved for reports and artifacts."""

    host: str
    port: int
    database: str
    username: str
    sslmode: str
    channel_binding: str | None = "require"

    def __post_init__(self) -> None:
        if (
            self.host != self.host.lower()
            or _SAFE_NEON_HOST.fullmatch(self.host) is None
            or _is_neon_pooler_host(self.host)
        ):
            raise ChronosProductionError("CHRONOS_DIRECT_DATABASE_HOST_INVALID")
        if self.port != 5432:
            raise ChronosProductionError("CHRONOS_DATABASE_URL_INVALID")
        if not self.database or "/" in self.database:
            raise ChronosProductionError("CHRONOS_DATABASE_NAME_INVALID")
        if not self.username:
            raise ChronosProductionError("CHRONOS_DATABASE_CREDENTIALS_MISSING")
        if self.sslmode not in _SAFE_SSL_MODES:
            raise ChronosProductionError("CHRONOS_SSL_REQUIRED")
        if self.channel_binding != "require":
            raise ChronosProductionError("CHRONOS_CHANNEL_BINDING_REQUIRED")


def validate_direct_postgres_url(value: str) -> DirectPostgresTarget:
    """Apply the canonical fail-closed Chronos production DSN contract."""

    if not isinstance(value, str) or not value.startswith("postgresql://"):
        raise ChronosProductionError("CHRONOS_DATABASE_SCHEME_INVALID")
    if _INVALID_PERCENT_ESCAPE.search(value) is not None:
        raise ChronosProductionError("CHRONOS_DATABASE_URL_INVALID")
    try:
        parsed = urlparse(value)
        parsed_port = parsed.port
        port = 5432 if parsed_port is None else parsed_port
        username = unquote(parsed.username or "", errors="strict")
        database = unquote(parsed.path.removeprefix("/"), errors="strict")
        query_items = parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
        )
        raw_query_keys = []
        for field in parsed.query.split("&"):
            if field.count("=") != 1:
                raise ValueError("malformed query field")
            raw_query_keys.append(field.partition("=")[0])
    except (TypeError, UnicodeError, ValueError):
        raise ChronosProductionError("CHRONOS_DATABASE_URL_INVALID") from None
    if parsed.scheme != "postgresql":
        raise ChronosProductionError("CHRONOS_DATABASE_SCHEME_INVALID")
    if parsed.params or parsed.fragment or ";" in parsed.path:
        raise ChronosProductionError("CHRONOS_DATABASE_URL_PARAMETERS_FORBIDDEN")
    if parsed.netloc.count("@") != 1:
        raise ChronosProductionError("CHRONOS_DATABASE_CREDENTIALS_INVALID")
    raw_userinfo, _, _ = parsed.netloc.partition("@")
    if raw_userinfo.count(":") != 1:
        raise ChronosProductionError("CHRONOS_DATABASE_CREDENTIALS_INVALID")
    raw_host = parsed.hostname or ""
    host = raw_host.lower()
    if not host or host == "localhost" or host.endswith(".localhost"):
        raise ChronosProductionError("CHRONOS_DIRECT_DATABASE_HOST_INVALID")
    if "%" in raw_host or _SAFE_NEON_HOST.fullmatch(host) is None:
        raise ChronosProductionError("CHRONOS_DIRECT_DATABASE_HOST_INVALID")
    if _is_neon_pooler_host(host):
        raise ChronosProductionError("CHRONOS_POOLED_ENDPOINT_FORBIDDEN")
    try:
        password = unquote(parsed.password or "", errors="strict")
    except (UnicodeError, ValueError):
        raise ChronosProductionError("CHRONOS_DATABASE_CREDENTIALS_INVALID") from None
    if not username or not password:
        raise ChronosProductionError("CHRONOS_DATABASE_CREDENTIALS_MISSING")
    if len(password) < 8:
        raise ChronosProductionError("CHRONOS_DATABASE_CREDENTIALS_INVALID")
    if not database or "/" in database:
        raise ChronosProductionError("CHRONOS_DATABASE_NAME_INVALID")
    query: dict[str, str] = {}
    if any(key not in _SAFE_QUERY_KEYS for key in raw_query_keys):
        raise ChronosProductionError("CHRONOS_DATABASE_URL_PARAMETERS_FORBIDDEN")
    for key, item in query_items:
        if key not in _SAFE_QUERY_KEYS or not item or key in query:
            raise ChronosProductionError("CHRONOS_DATABASE_URL_PARAMETERS_FORBIDDEN")
        query[key] = item
    if set(query) != _SAFE_QUERY_KEYS:
        raise ChronosProductionError("CHRONOS_DATABASE_URL_PARAMETERS_FORBIDDEN")
    sslmode = query["sslmode"]
    if sslmode not in _SAFE_SSL_MODES:
        raise ChronosProductionError("CHRONOS_SSL_REQUIRED")
    channel_binding = query.get("channel_binding")
    if channel_binding != "require":
        raise ChronosProductionError("CHRONOS_CHANNEL_BINDING_REQUIRED")
    return DirectPostgresTarget(
        host=host,
        port=port,
        database=database,
        username=username,
        sslmode=sslmode,
        channel_binding=channel_binding,
    )


def build_scoped_database_url(
    target: DirectPostgresTarget,
    *,
    username: str,
    password: str,
) -> str:
    """Build a URL outside logs with RFC3986-encoded credentials."""

    require_identifier(username, field="scoped_username")
    if not password:
        raise ChronosProductionError("CHRONOS_SCOPED_PASSWORD_MISSING")
    netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{target.host}"
    if target.port != 5432:
        netloc += f":{target.port}"
    query_items = [("sslmode", target.sslmode)]
    if target.channel_binding is not None:
        if target.channel_binding != "require":
            raise ChronosProductionError("CHRONOS_CHANNEL_BINDING_REQUIRED")
        query_items.append(("channel_binding", target.channel_binding))
    return urlunparse(
        (
            "postgresql",
            netloc,
            "/" + quote(target.database, safe=""),
            "",
            urlencode(query_items),
            "",
        )
    )


def canonical_json_bytes(document: dict[str, Any]) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_document(document: dict[str, Any], key: str) -> dict[str, Any]:
    """Return a detached HMAC envelope without logging key material."""

    if not key:
        raise ChronosProductionError("CHRONOS_SIGNING_KEY_MISSING")
    unsigned = dict(document)
    unsigned.pop("signature", None)
    digest = hmac.new(
        key.encode("utf-8"), canonical_json_bytes(unsigned), hashlib.sha256
    ).hexdigest()
    return {
        **unsigned,
        "signature": {
            "algorithm": "HMAC-SHA256",
            "value": digest,
        },
    }


def verify_signed_document(document: dict[str, Any], key: str) -> dict[str, Any]:
    """Verify an HMAC envelope and return only the unsigned document."""

    signature = document.get("signature")
    if not isinstance(signature, dict):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_SIGNATURE_MISSING")
    if signature.get("algorithm") != "HMAC-SHA256":
        raise ChronosProductionError("CHRONOS_PREFLIGHT_SIGNATURE_ALGORITHM_INVALID")
    supplied = signature.get("value")
    if not isinstance(supplied, str) or _HEX_64.fullmatch(supplied) is None:
        raise ChronosProductionError("CHRONOS_PREFLIGHT_SIGNATURE_INVALID")
    unsigned = dict(document)
    unsigned.pop("signature", None)
    expected = hmac.new(
        key.encode("utf-8"), canonical_json_bytes(unsigned), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_SIGNATURE_MISMATCH")
    return unsigned


def preflight_hash(document: dict[str, Any]) -> str:
    unsigned = dict(document)
    unsigned.pop("signature", None)
    unsigned.pop("preflight_hash", None)
    return hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest()


def generation_hash(nonce_hex: str) -> str:
    require_hash(nonce_hex, field="generation_nonce")
    return hashlib.sha256(bytes.fromhex(nonce_hex)).hexdigest()


def build_generation_bound_password(*, nonce_hex: str, entropy: str) -> str:
    """Bind a scoped credential to the nonce that activates its generation."""

    digest = generation_hash(nonce_hex)
    if _GENERATION_PASSWORD_ENTROPY.fullmatch(entropy) is None:
        raise ChronosProductionError("CHRONOS_SCOPED_PASSWORD_ENTROPY_INVALID")
    return f"g1_{digest}_{entropy}"


def require_generation_bound_password(*, password: str, nonce_hex: str) -> str:
    """Reject a partial or mixed GitHub secret rotation before any DB effect."""

    parts = password.split("_", 2)
    if (
        len(parts) != 3
        or parts[0] != "g1"
        or _HEX_64.fullmatch(parts[1]) is None
        or _GENERATION_PASSWORD_ENTROPY.fullmatch(parts[2]) is None
        or not hmac.compare_digest(parts[1], generation_hash(nonce_hex))
    ):
        raise ChronosProductionError("CHRONOS_SCOPED_PASSWORD_GENERATION_MISMATCH")
    return password


def validate_neon_branch_identity_go_v2(
    value: object,
    *,
    main_sha: str,
) -> dict[str, Any]:
    """Accept only the zero-wake, zero-SQL Recovery V2 identity GO."""

    expected_main_sha = require_sha(main_sha, field="main_sha")
    top_fields = {
        "schema_version",
        "observed_at",
        "source",
        "verdict",
        "effect_counter_certainty",
        "github_actions",
        "neon",
        "effects",
    }
    source_fields = {
        "repository",
        "ref",
        "main_sha",
        "workflow_path",
        "run_id",
        "run_attempt",
    }
    github_fields = {
        "queued",
        "in_progress",
        "current_run_excluded",
        "exact_main_dispatch_count",
        "authority_window_dispatch_count",
    }
    effect_fields = {
        "neon_gets",
        "neon_post",
        "neon_patch",
        "neon_delete",
        "compute_wakes",
        "postgresql_connections",
        "sql_statements",
        "r2_operations",
        "official_reads",
        "odds_requests",
        "secret_writes",
        "purchases",
        "http_retries",
        "redirects_followed",
    }
    neon_fields = {
        "identity_path",
        "identity_proof_mode",
        "project_identity_verdict",
        "neon_project_identity_verdict",
        "project_inventory_exhaustive",
        "project_pages_read",
        "projects_observed",
        "endpoint_projects_inspected",
        "endpoint_inventory_reads",
        "endpoint_detail_reads",
        "project_detail_reads",
        "branch_pages_read",
        "branch_endpoint_reads",
        "cursor_continuation_requested",
        "cursor_cycle_encountered",
        "positive_witness_checks",
        "project_id_sha256",
        "project_name_sha256",
        "region",
        "production_branch_id_sha256",
        "production_branch_name_sha256",
        "production_branch_default",
        "production_branch_parent_id_sha256",
        "recovery_parent_id_sha256",
        "endpoint_id_sha256",
        "endpoint_host_sha256",
        "endpoint_state",
        "suspend_timeout_seconds",
        "branch_state",
        "owner_id_sha256",
        "owner_branch_count",
        "branch_limit",
        "branch_capacity_proven",
        "bill_free_branch_capacity_proven",
        "owner_scope_verdict",
        "branch_count_reads",
        "subscription_type",
        "billing_plan",
        "target_project_branch_count",
        "history_retention_seconds",
        "postgresql_major",
        "autoscaling_limit_max_cu",
        "api_get_count",
        "api_post_count",
        "api_put_count",
        "api_patch_count",
        "api_delete_count",
        "branch_count_before",
        "branch_count_after",
        "branches_observed",
        "inventory_exhaustive",
        "terminal_by_cardinality",
        "continuation_required",
        "continuation_followed_count",
        "terminal_pagination_metadata_present",
        "default_branch_count",
        "dsn_branch_matches_default",
        "branch_endpoint_concordant",
        "identity_intersection_size",
        "branch_inventory_failure_class",
    }
    if not isinstance(value, dict) or set(value) != top_fields:
        raise ChronosProductionError("CHRONOS_IDENTITY_GO_V2_INVALID")
    report = dict(value)
    source = report.get("source")
    github = report.get("github_actions")
    effects = report.get("effects")
    neon = report.get("neon")
    if (
        not isinstance(source, dict)
        or set(source) != source_fields
        or not isinstance(github, dict)
        or set(github) != github_fields
        or not isinstance(effects, dict)
        or set(effects) != effect_fields
        or not isinstance(neon, dict)
        or set(neon) != neon_fields
    ):
        raise ChronosProductionError("CHRONOS_IDENTITY_GO_V2_INVALID")
    run_id = source.get("run_id")
    neon_gets = effects.get("neon_gets")
    counts = (
        neon.get("branch_count_before"),
        neon.get("branch_count_after"),
        neon.get("branches_observed"),
        neon.get("target_project_branch_count"),
    )
    hash_fields = (
        "project_id_sha256",
        "project_name_sha256",
        "region",
        "production_branch_id_sha256",
        "production_branch_name_sha256",
        "recovery_parent_id_sha256",
        "endpoint_id_sha256",
        "endpoint_host_sha256",
        "owner_id_sha256",
    )
    positive_witness_checks = [
        "EXACT_DSN_HOST_MATCH",
        "PROJECT_SCOPED_ENDPOINT_INVENTORY",
        "ENDPOINT_DETAIL_CONCORDANT",
        "PROJECT_DETAIL_CONCORDANT",
        "DEFAULT_BRANCH_RELATIONSHIP_CONCORDANT",
        "BRANCH_ENDPOINT_CONCORDANT",
    ]
    positive_int_fields = (
        "project_pages_read",
        "projects_observed",
        "endpoint_projects_inspected",
        "endpoint_inventory_reads",
        "endpoint_detail_reads",
        "project_detail_reads",
        "branch_pages_read",
        "branch_endpoint_reads",
        "owner_branch_count",
        "branch_limit",
        "history_retention_seconds",
        "postgresql_major",
    )
    subscription_plans = {
        "free_v2": "free",
        "free_v3": "free",
        "launch": "launch",
        "launch_v3": "launch",
        "scale": "scale",
        "scale_v3": "scale",
    }
    zero_effects = effect_fields - {"neon_gets"}
    neon_integer_fields = set(positive_int_fields) | {
        "api_get_count",
        "api_post_count",
        "api_put_count",
        "api_patch_count",
        "api_delete_count",
        "branch_count_before",
        "branch_count_after",
        "branches_observed",
        "branch_count_reads",
        "continuation_followed_count",
        "default_branch_count",
        "identity_intersection_size",
        "suspend_timeout_seconds",
        "target_project_branch_count",
    }
    if (
        report.get("schema_version") != "neon-branch-identity-go-v2"
        or report.get("verdict") != "NEON_BRANCH_IDENTITY_GO_V2"
        or report.get("effect_counter_certainty") != "OBSERVED"
        or source.get("repository") != EXPECTED_REPOSITORY
        or source.get("ref") != EXPECTED_REF
        or source.get("main_sha") != expected_main_sha
        or source.get("workflow_path") != ".github/workflows/chronos-neon-branch-identity-v2.yml"
        or not isinstance(run_id, str)
        or _RUN_ID.fullmatch(run_id) is None
        or source.get("run_attempt") != "1"
        or not _exact_integer_fields(github, github_fields)
        or github
        != {
            "queued": 0,
            "in_progress": 0,
            "current_run_excluded": int(run_id),
            "exact_main_dispatch_count": 1,
            "authority_window_dispatch_count": 1,
        }
        or not _exact_integer_fields(effects, effect_fields)
        or type(neon_gets) is not int
        or not 1 <= neon_gets <= 25
        or any(effects.get(field) != 0 for field in zero_effects)
        or neon.get("api_get_count") != neon_gets
        or any(
            neon.get(field) != 0
            for field in (
                "api_post_count",
                "api_put_count",
                "api_patch_count",
                "api_delete_count",
            )
        )
        or neon.get("identity_path") != "POSITIVE_ENDPOINT_WITNESS"
        or neon.get("identity_proof_mode") != "POSITIVE_OWNERSHIP"
        or neon.get("project_identity_verdict") != "POSITIVE_PROJECT_OWNERSHIP_WITNESS_PROVEN"
        or neon.get("neon_project_identity_verdict") != "NEON_PROJECT_IDENTITY_PROVEN"
        or neon.get("project_inventory_exhaustive") is not True
        or neon.get("inventory_exhaustive") is not True
        or neon.get("terminal_by_cardinality") is not True
        or neon.get("cursor_cycle_encountered") is not False
        or neon.get("branch_inventory_failure_class") != "NONE"
        or not _exact_integer_fields(neon, neon_integer_fields)
        or neon.get("branch_count_reads") != 2
        or not all(type(count) is int and count >= 1 for count in counts)
        or len(set(cast(tuple[int, int, int, int], counts))) != 1
        or neon.get("default_branch_count") != 1
        or neon.get("production_branch_default") is not True
        or neon.get("production_branch_parent_id_sha256") is not None
        or neon.get("dsn_branch_matches_default") is not True
        or neon.get("branch_endpoint_concordant") is not True
        or neon.get("identity_intersection_size") != 1
        or neon.get("positive_witness_checks") != positive_witness_checks
        or any(
            type(neon.get(field)) is not int or not 1 <= cast(int, neon.get(field)) <= 1_000_000_000
            for field in positive_int_fields
        )
        or any(
            cast(int, neon.get(field)) > neon_gets
            for field in {
                "project_pages_read",
                "endpoint_projects_inspected",
                "endpoint_inventory_reads",
                "endpoint_detail_reads",
                "project_detail_reads",
                "branch_pages_read",
                "branch_endpoint_reads",
            }
        )
        or neon.get("endpoint_inventory_reads") != neon.get("endpoint_projects_inspected")
        or neon.get("endpoint_detail_reads") != 1
        or neon.get("project_detail_reads") != 1
        or neon.get("branch_endpoint_reads") != 1
        or type(neon.get("continuation_followed_count")) is not int
        or cast(int, neon.get("continuation_followed_count")) < 0
        or neon.get("branch_pages_read") != cast(int, neon.get("continuation_followed_count")) + 1
        or neon.get("continuation_required")
        is not (cast(int, neon.get("continuation_followed_count")) > 0)
        or neon.get("cursor_continuation_requested") is not neon.get("continuation_required")
        or type(neon.get("terminal_pagination_metadata_present")) is not bool
        or cast(int, neon.get("owner_branch_count"))
        < cast(int, neon.get("target_project_branch_count"))
        or cast(int, neon.get("branch_limit")) <= cast(int, neon.get("owner_branch_count"))
        or neon.get("recovery_parent_id_sha256") != neon.get("production_branch_id_sha256")
        or neon.get("owner_scope_verdict")
        not in {
            "ORGANIZATION_WIDE_API_KEY",
            "PERSONAL_ADMIN_ORGANIZATION_PROVEN",
        }
        or neon.get("subscription_type") not in subscription_plans
        or subscription_plans.get(cast(str, neon.get("subscription_type")))
        != neon.get("billing_plan")
        or type(neon.get("suspend_timeout_seconds")) is not int
        or not -1 <= cast(int, neon.get("suspend_timeout_seconds")) <= 604_800
        or 0 < cast(int, neon.get("suspend_timeout_seconds")) < 60
        or isinstance(neon.get("autoscaling_limit_max_cu"), bool)
        or not isinstance(neon.get("autoscaling_limit_max_cu"), (int, float))
        or not 0 < cast(float, neon.get("autoscaling_limit_max_cu")) <= 1_000
        or neon.get("branch_capacity_proven") is not True
        or neon.get("bill_free_branch_capacity_proven") is not True
        or neon.get("branch_state") != "ready"
        or neon.get("endpoint_state") not in {"active", "idle"}
        or any(
            not isinstance(neon.get(field), str)
            or _HEX_64.fullmatch(cast(str, neon.get(field))) is None
            for field in hash_fields
        )
    ):
        raise ChronosProductionError("CHRONOS_IDENTITY_GO_V2_INVALID")
    _authority_timestamp(report.get("observed_at"), field="identity_go_v2_observed_at")
    return report


def validate_identity_seal_v2(
    value: object,
    *,
    main_sha: str,
    expected_identity_run_id: str,
) -> dict[str, Any]:
    """Accept only the immutable Recovery V2 identity seal and its exact counters."""

    expected_main_sha = require_sha(main_sha, field="main_sha")
    if _RUN_ID.fullmatch(expected_identity_run_id) is None or expected_identity_run_id == "0":
        raise ChronosProductionError("CHRONOS_IDENTITY_SEAL_V2_INVALID")
    top_fields = {
        "schema_version",
        "verdict",
        "sealed_at",
        "source",
        "identity_go",
        "github_actions",
        "effects",
    }
    source_fields = {"repository", "ref", "main_sha", "run_id", "run_attempt"}
    identity_fields = {
        "schema_version",
        "repository",
        "workflow_path",
        "run_id",
        "run_attempt",
        "head_sha",
        "artifact_id",
        "artifact_name",
        "payload_sha256",
        "archive_sha256",
        "durable_store",
        "conditional_put_outcome",
        "durable_object_key",
        "durable_metadata",
        "durable_readback_sha256",
        "store_identity_sha256",
    }
    metadata_fields = {
        "schema",
        "sha256",
        "main_sha",
        "identity_run_id",
        "artifact_id",
        "archive_sha256",
        "store_identity_sha256",
    }
    github_fields = {
        "queued",
        "in_progress",
        "exact_main_dispatch_count",
        "authority_window_dispatch_count",
    }
    effect_fields = {
        "r2_puts",
        "r2_gets",
        "r2_objects_created",
        "r2_lists",
        "r2_deletes",
        "r2_overwrites",
        "automatic_retries",
        "neon_gets",
        "neon_mutations",
        "postgresql_connections",
        "sql_statements",
        "provider_calls",
        "purchases",
        "sensitive_values_exposed",
    }
    if not isinstance(value, dict) or set(value) != top_fields:
        raise ChronosProductionError("CHRONOS_IDENTITY_SEAL_V2_INVALID")
    report = dict(value)
    source = report.get("source")
    identity = report.get("identity_go")
    github = report.get("github_actions")
    effects = report.get("effects")
    if (
        not isinstance(source, dict)
        or set(source) != source_fields
        or not isinstance(identity, dict)
        or set(identity) != identity_fields
        or not isinstance(github, dict)
        or set(github) != github_fields
        or not isinstance(effects, dict)
        or set(effects) != effect_fields
    ):
        raise ChronosProductionError("CHRONOS_IDENTITY_SEAL_V2_INVALID")
    metadata = identity.get("durable_metadata")
    seal_run_id = source.get("run_id")
    artifact_id = identity.get("artifact_id")
    payload_sha = identity.get("payload_sha256")
    archive_sha = identity.get("archive_sha256")
    store_sha = identity.get("store_identity_sha256")
    hashes = (payload_sha, archive_sha, store_sha, identity.get("durable_readback_sha256"))
    expected_key = (
        "data-torrent-recovery-v2/control-plane/identity-go/"
        f"main_sha={expected_main_sha}/run_id={expected_identity_run_id}/"
        f"report-{payload_sha}.json"
    )
    expected_metadata = {
        "schema": "neon-branch-identity-go-v2",
        "sha256": payload_sha,
        "main_sha": expected_main_sha,
        "identity_run_id": expected_identity_run_id,
        "artifact_id": str(artifact_id),
        "archive_sha256": archive_sha,
        "store_identity_sha256": store_sha,
    }
    if (
        report.get("schema_version") != "durable-identity-seal-v2"
        or report.get("verdict") != "DURABLE_IDENTITY_SEAL_V2"
        or source
        != {
            "repository": EXPECTED_REPOSITORY,
            "ref": EXPECTED_REF,
            "main_sha": expected_main_sha,
            "run_id": seal_run_id,
            "run_attempt": "1",
        }
        or not isinstance(seal_run_id, str)
        or _RUN_ID.fullmatch(seal_run_id) is None
        or seal_run_id == "0"
        or identity.get("schema_version") != "github-artifact-attestation-v2"
        or identity.get("repository") != EXPECTED_REPOSITORY
        or identity.get("workflow_path") != ".github/workflows/chronos-neon-branch-identity-v2.yml"
        or identity.get("run_id") != expected_identity_run_id
        or identity.get("run_attempt") != "1"
        or identity.get("head_sha") != expected_main_sha
        or type(artifact_id) is not int
        or artifact_id < 1
        or identity.get("artifact_name") != f"neon-branch-identity-go-v2-{expected_identity_run_id}"
        or any(not isinstance(item, str) or _HEX_64.fullmatch(item) is None for item in hashes)
        or identity.get("durable_store") != "R2_IMMUTABLE"
        or identity.get("conditional_put_outcome") != "CREATED"
        or identity.get("durable_object_key") != expected_key
        or identity.get("durable_readback_sha256") != payload_sha
        or not _exact_integer_fields(github, github_fields)
        or not _exact_integer_fields(effects, effect_fields)
        or not isinstance(metadata, dict)
        or set(metadata) != metadata_fields
        or metadata != expected_metadata
        or github
        != {
            "queued": 0,
            "in_progress": 0,
            "exact_main_dispatch_count": 1,
            "authority_window_dispatch_count": 1,
        }
        or effects
        != {
            "r2_puts": 1,
            "r2_gets": 1,
            "r2_objects_created": 1,
            "r2_lists": 0,
            "r2_deletes": 0,
            "r2_overwrites": 0,
            "automatic_retries": 0,
            "neon_gets": 0,
            "neon_mutations": 0,
            "postgresql_connections": 0,
            "sql_statements": 0,
            "provider_calls": 0,
            "purchases": 0,
            "sensitive_values_exposed": 0,
        }
    ):
        raise ChronosProductionError("CHRONOS_IDENTITY_SEAL_V2_INVALID")
    _authority_timestamp(report.get("sealed_at"), field="identity_seal_v2_sealed_at")
    return report


def validate_runtime_bindings_v2(
    value: object,
    *,
    main_sha: str,
    preflight_run_id: str,
    preflight_artifact_hash: str,
    generation_nonce: str,
) -> dict[str, Any]:
    """Accept only the authenticated exact ordered four-write V2 receipt."""

    expected_sha = require_sha(main_sha, field="main_sha")
    expected_hash = require_hash(preflight_artifact_hash, field="preflight_hash")
    try:
        expected_generation_hash = generation_hash(generation_nonce)
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RUNTIME_BINDINGS_V2_INVALID") from None
    fields = {
        "schema_version",
        "verdict",
        "repository",
        "environment",
        "main_sha",
        "preflight_run_id",
        "preflight_hash",
        "preflight_controller_receipt_sha256",
        "secret_writes_attempted",
        "secret_writes_confirmed",
        "secret_names_in_order",
        "secret_value_readbacks",
        "automatic_retries",
        "global_hold_full_validations",
        "concurrent_run_inventory_validations",
        "github_api_gets_upper_bound",
        "github_api_gets_exact",
        "github_cli_version",
        "github_cli_sha256",
        "effect_admission_deadline_seconds",
        "stage_outer_timeout_seconds",
        "generation_hash",
        "installed_at",
        "secret_values_observed",
    }
    expected_names = [
        *(secret for _login, _group, secret in SCOPED_LOGINS),
        "CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
    ]
    integer_fields = {
        "secret_writes_attempted",
        "secret_writes_confirmed",
        "secret_value_readbacks",
        "automatic_retries",
        "global_hold_full_validations",
        "concurrent_run_inventory_validations",
        "github_api_gets_upper_bound",
        "effect_admission_deadline_seconds",
        "stage_outer_timeout_seconds",
    }
    if not isinstance(value, dict) or set(value) != fields | {"signature"}:
        raise ChronosProductionError("CHRONOS_RUNTIME_BINDINGS_V2_INVALID")
    signed_receipt = dict(value)
    try:
        receipt = verify_signed_document(signed_receipt, generation_nonce)
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_RUNTIME_BINDINGS_V2_INVALID") from None
    if set(receipt) != fields:
        raise ChronosProductionError("CHRONOS_RUNTIME_BINDINGS_V2_INVALID")
    if (
        receipt.get("schema_version") != "chronos-runtime-bindings-v2"
        or receipt.get("verdict") != "FOUR_RUNTIME_BINDINGS_INSTALLED_V2"
        or receipt.get("repository") != EXPECTED_REPOSITORY
        or receipt.get("environment") != EXPECTED_ENVIRONMENT
        or receipt.get("main_sha") != expected_sha
        or receipt.get("preflight_run_id") != preflight_run_id
        or receipt.get("preflight_hash") != expected_hash
        or not isinstance(receipt.get("preflight_controller_receipt_sha256"), str)
        or _HEX_64.fullmatch(
            cast(str, receipt["preflight_controller_receipt_sha256"])
        )
        is None
        or not _exact_integer_fields(receipt, integer_fields)
        or receipt.get("secret_writes_attempted") != 4
        or receipt.get("secret_writes_confirmed") != 4
        or receipt.get("secret_names_in_order") != expected_names
        or receipt.get("secret_value_readbacks") != 0
        or receipt.get("automatic_retries") != 0
        or receipt.get("global_hold_full_validations") != 2
        or receipt.get("concurrent_run_inventory_validations") != 4
        or receipt.get("github_api_gets_upper_bound") != 55
        or receipt.get("github_api_gets_exact") is not False
        or receipt.get("github_cli_version") != "2.96.0"
        or receipt.get("github_cli_sha256")
        != "cd79f16203f1fbe56937c4c96e2b6eadd10549418dcb241d91576ac77af0ac8b"
        or receipt.get("effect_admission_deadline_seconds") != 480
        or receipt.get("stage_outer_timeout_seconds") != 600
        or receipt.get("generation_hash") != expected_generation_hash
        or receipt.get("secret_values_observed") is not False
    ):
        raise ChronosProductionError("CHRONOS_RUNTIME_BINDINGS_V2_INVALID")
    _authority_timestamp(receipt.get("installed_at"), field="runtime_bindings_v2_installed_at")
    return signed_receipt


def validate_controlled_go_binding(
    value: object,
    *,
    main_sha: str,
) -> dict[str, Any]:
    """Validate the exact immutable controlled-wake release-chain binding."""

    expected_main_sha = require_sha(main_sha, field="main_sha")
    fields = {
        "schema_version",
        "workflow_path",
        "run_id",
        "run_attempt",
        "main_sha",
        "report_schema",
        "report_sha256",
        "endpoint_pre_wake_state",
        "compute_wake_events",
        "postgresql_connection_attempts",
        "production_sql_writes",
        "neon_mutations",
        "durable_store",
        "conditional_put_outcome",
        "durable_object_key",
        "durable_readback_sha256",
        "seal_workflow_path",
        "seal_run_id",
        "seal_run_attempt",
        "seal_receipt_sha256",
        "seal_r2_puts",
        "seal_r2_gets",
        "seal_r2_objects_created",
        "preflight_readback_sha256",
        "preflight_r2_gets",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ChronosProductionError("CHRONOS_CONTROLLED_GO_BINDING_INVALID")
    binding = dict(value)
    controlled_run_id = binding.get("run_id")
    seal_run_id = binding.get("seal_run_id")
    report_sha256 = binding.get("report_sha256")
    if (
        binding.get("schema_version") != "chronos-controlled-go-binding-v1"
        or binding.get("workflow_path")
        != ".github/workflows/chronos-neon-controlled-idle-wake-readonly-v1.yml"
        or not isinstance(controlled_run_id, str)
        or _RUN_ID.fullmatch(controlled_run_id) is None
        or binding.get("run_attempt") != "1"
        or binding.get("main_sha") != expected_main_sha
        or binding.get("report_schema") != "chronos-neon-controlled-idle-wake-readonly-v1"
        or not isinstance(report_sha256, str)
        or _HEX_64.fullmatch(report_sha256) is None
        or binding.get("endpoint_pre_wake_state") not in {"active", "idle"}
        or type(binding.get("compute_wake_events")) is not int
        or binding.get("compute_wake_events") != 1
        or type(binding.get("postgresql_connection_attempts")) is not int
        or binding.get("postgresql_connection_attempts") != 1
        or type(binding.get("production_sql_writes")) is not int
        or binding.get("production_sql_writes") != 0
        or type(binding.get("neon_mutations")) is not int
        or binding.get("neon_mutations") != 0
        or binding.get("durable_store") != "R2_IMMUTABLE"
        or binding.get("conditional_put_outcome") != "CREATED"
        or binding.get("durable_object_key")
        != (
            "data-torrent-ready-v1/control-plane/controlled-go/"
            f"main_sha={expected_main_sha}/run_id={controlled_run_id}/"
            f"report-{report_sha256}.json"
        )
        or binding.get("durable_readback_sha256") != report_sha256
        or binding.get("seal_workflow_path")
        != ".github/workflows/chronos-controlled-go-durable-seal-v1.yml"
        or not isinstance(seal_run_id, str)
        or _RUN_ID.fullmatch(seal_run_id) is None
        or binding.get("seal_run_attempt") != "1"
        or not isinstance(binding.get("seal_receipt_sha256"), str)
        or _HEX_64.fullmatch(str(binding.get("seal_receipt_sha256"))) is None
        or type(binding.get("seal_r2_puts")) is not int
        or binding.get("seal_r2_puts") != 1
        or type(binding.get("seal_r2_gets")) is not int
        or binding.get("seal_r2_gets") != 1
        or type(binding.get("seal_r2_objects_created")) is not int
        or binding.get("seal_r2_objects_created") != 1
        or binding.get("preflight_readback_sha256") != report_sha256
        or type(binding.get("preflight_r2_gets")) is not int
        or binding.get("preflight_r2_gets") != 1
    ):
        raise ChronosProductionError("CHRONOS_CONTROLLED_GO_BINDING_INVALID")
    return binding


def assert_exact_preflight_binding(
    document: dict[str, Any],
    *,
    main_sha: str,
    workflow_sha: str,
    project_id: str,
    production_branch_id: str,
    recovery_branch_id: str,
    current_revision: str = EXPECTED_BEFORE_REVISION,
) -> None:
    """Reject stale, replayed, or cross-project PREFLIGHT artifacts."""

    expected: dict[str, object] = {
        "main_sha": require_sha(main_sha, field="main_sha"),
        "workflow_sha": require_sha(workflow_sha, field="workflow_sha"),
        "project_id": project_id,
        "production_branch_id": production_branch_id,
        "current_revision": current_revision,
        "recovery_branch_id": recovery_branch_id,
    }
    for field, value in expected.items():
        if document.get(field) != value:
            raise ChronosProductionError(f"CHRONOS_PREFLIGHT_{field.upper()}_MISMATCH")
    supplied_hash = document.get("preflight_hash")
    if not isinstance(supplied_hash, str) or supplied_hash != preflight_hash(document):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_HASH_MISMATCH")
    if document.get("golden_gate") != "CHRONOS_MIGRATION_READY":
        raise ChronosProductionError("CHRONOS_MIGRATION_BLOCKED")


def assert_exact_preflight_target(
    document: Mapping[str, object],
    *,
    expected_target: DirectPostgresTarget,
) -> None:
    """Bind a signed PREFLIGHT artifact to the exact direct PostgreSQL target."""

    observed = {
        "database_host": document.get("database_host"),
        "database_port": document.get("database_port"),
        "database_name": document.get("database_name"),
        "sslmode": document.get("sslmode"),
        "channel_binding": document.get("channel_binding"),
    }
    expected = {
        "database_host": expected_target.host,
        "database_port": expected_target.port,
        "database_name": expected_target.database,
        "sslmode": expected_target.sslmode,
        "channel_binding": expected_target.channel_binding,
    }
    if observed != expected:
        raise ChronosProductionError("CHRONOS_PREFLIGHT_DATABASE_TARGET_MISMATCH")


__all__ = [
    "DATA_TORRENT_LIVE_V2_POSTGRESQL_CALL_GRAPH_CANONICAL_SHA256",
    "DATA_TORRENT_LIVE_V2_POSTGRESQL_CALL_GRAPH_SHA256",
    "DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_CANONICAL_SHA256",
    "DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_SHA256",
    "DATA_TORRENT_RECOVERY_V2_EXTERNAL_EFFECTS",
    "DATA_TORRENT_RECOVERY_V2_MANIFEST_CANONICAL_SHA256",
    "DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256",
    "DATA_TORRENT_RECOVERY_V2_MISSION_ID",
    "DATA_TORRENT_RECOVERY_V2_START_SHA",
    "DATA_TORRENT_CONTROLLED_EFFECT_CONTRACT_SHA256",
    "DATA_TORRENT_LATEST_EFFECT_ADMISSION_AT",
    "DATA_TORRENT_MAXIMUM_EFFECT_RUNTIME_SECONDS",
    "DATA_TORRENT_MISSION_ID",
    "DATA_TORRENT_MISSION_MANIFEST_SHA256",
    "DATA_TORRENT_ONE_SHOT_NOT_BEFORE",
    "DATA_TORRENT_OWNER_DIRECTIVE_SHA256",
    "EXPECTED_AFTER_REVISION",
    "EXPECTED_BEFORE_REVISION",
    "EXPECTED_BEFORE_REVISIONS",
    "EXPECTED_ENVIRONMENT",
    "EXPECTED_REF",
    "EXPECTED_REPOSITORY",
    "MIGRATION_TARGET",
    "SCOPED_LOGINS",
    "PRODUCTION_SAFETY_LOCKS",
    "ChronosProductionError",
    "DirectPostgresTarget",
    "assert_exact_preflight_binding",
    "assert_exact_preflight_target",
    "assert_production_safety_locks",
    "build_scoped_database_url",
    "build_generation_bound_password",
    "canonical_json_bytes",
    "connect_direct_postgres",
    "generation_hash",
    "preflight_hash",
    "require_hash",
    "require_generation_bound_password",
    "require_identifier",
    "require_sha",
    "sign_document",
    "validate_direct_postgres_url",
    "validate_data_torrent_authority",
    "validate_data_torrent_recovery_v2_authority",
    "validate_data_torrent_recovery_v2_council_release",
    "validate_data_torrent_recovery_v2_phase_one_council_closure",
    "validate_data_torrent_recovery_v2_terminal_council_closure",
    "data_torrent_recovery_v2_release_projection",
    "data_torrent_recovery_v2_reviewed_candidate_projection",
    "data_torrent_recovery_v2_postmerge_final_gate_contract",
    "validate_identity_seal_v2",
    "validate_neon_branch_identity_go_v2",
    "validate_runtime_bindings_v2",
    "validate_controlled_go_binding",
    "libpq_environment_variable_names",
    "require_libpq_environment_clean",
    "verify_signed_document",
]
