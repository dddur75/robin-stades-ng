"""Frozen, mechanically derived PostgreSQL call graph for Recovery V2 LIVE."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from robin.chronos_production import (
    DATA_TORRENT_LIVE_V2_POSTGRESQL_CALL_GRAPH_CANONICAL_SHA256,
    DATA_TORRENT_LIVE_V2_POSTGRESQL_CALL_GRAPH_SHA256,
)

CALL_GRAPH_RELATIVE_PATH = "configs/execution/data-torrent-live-v2-postgresql-call-graph.json"
CALL_GRAPH_SCHEMA = "robin-data-torrent-live-postgresql-call-graph-v2"

_DIRECT_READS = (
    ("scoped_role_identity_and_acl", 3, 1),
    ("database_revision", 1, 1),
    ("terminal_source_audit", 1, 1),
    ("terminal_batch_readback", 1, 1),
)
_FUNCTION_READS = (
    ("raw_r2_effect_state", 1, 2),
    ("normalized_r2_effect_state", 1, 2),
)
_FUNCTION_READ_FALLBACKS = (
    ("raw_r2_transition_forbidden_readback", 1, 1),
    ("normalized_r2_transition_forbidden_readback", 1, 1),
)
_MUTATING_FUNCTIONS = (
    ("initial_claim_authority", 1, 1),
    ("logical_opportunity_claim", 1, 1),
    ("official_effect_reserve_dispatch_reconcile", 5, 3),
    ("odds_effect_reserve_dispatch_reconcile", 5, 3),
    ("raw_r2_authority_claim_dispatch_confirm", 1, 4),
    ("normalized_r2_authority_claim_dispatch_confirm", 1, 4),
    ("terminal_batch_record", 1, 1),
)


def _components(values: tuple[tuple[str, int, int], ...]) -> list[dict[str, Any]]:
    return [
        {
            "boundary": boundary,
            "cardinality": cardinality,
            "connections_per_item": connections,
            "connections": cardinality * connections,
        }
        for boundary, cardinality, connections in values
    ]


def _total(values: tuple[tuple[str, int, int], ...]) -> int:
    return sum(cardinality * connections for _name, cardinality, connections in values)


LIVE_POSTGRESQL_DIRECT_READS_V2 = _total(_DIRECT_READS)
LIVE_POSTGRESQL_FUNCTION_READS_NOMINAL_V2 = _total(_FUNCTION_READS)
LIVE_POSTGRESQL_FUNCTION_READS_FALLBACK_MAXIMUM_V2 = _total(_FUNCTION_READ_FALLBACKS)
LIVE_POSTGRESQL_MUTATING_FUNCTIONS_V2 = _total(_MUTATING_FUNCTIONS)
LIVE_POSTGRESQL_CONNECTION_ATTEMPTS_NOMINAL_V2 = (
    LIVE_POSTGRESQL_DIRECT_READS_V2
    + LIVE_POSTGRESQL_FUNCTION_READS_NOMINAL_V2
    + LIVE_POSTGRESQL_MUTATING_FUNCTIONS_V2
)
LIVE_POSTGRESQL_CONNECTION_ATTEMPTS_UPPER_BOUND_V2 = (
    LIVE_POSTGRESQL_CONNECTION_ATTEMPTS_NOMINAL_V2
    + LIVE_POSTGRESQL_FUNCTION_READS_FALLBACK_MAXIMUM_V2
)


def build_live_postgresql_call_graph_v2() -> dict[str, Any]:
    """Build the only authorized successful LIVE PostgreSQL call graph."""

    return {
        "schema_version": CALL_GRAPH_SCHEMA,
        "mission_id": "data-torrent-recovery-v2",
        "workflow_path": ".github/workflows/data-torrent-live-v2.yml",
        "successful_path": {
            "direct_read_connections": _components(_DIRECT_READS),
            "function_read_connections": _components(_FUNCTION_READS),
            "function_read_transition_fallback_connections": _components(_FUNCTION_READ_FALLBACKS),
            "mutating_function_connections": _components(_MUTATING_FUNCTIONS),
        },
        "derived": {
            "direct_read_connections": LIVE_POSTGRESQL_DIRECT_READS_V2,
            "function_read_connections_nominal": (LIVE_POSTGRESQL_FUNCTION_READS_NOMINAL_V2),
            "function_read_transition_fallback_connections_maximum": (
                LIVE_POSTGRESQL_FUNCTION_READS_FALLBACK_MAXIMUM_V2
            ),
            "mutating_function_connections": (LIVE_POSTGRESQL_MUTATING_FUNCTIONS_V2),
            "postgresql_connection_attempts_nominal": (
                LIVE_POSTGRESQL_CONNECTION_ATTEMPTS_NOMINAL_V2
            ),
            "postgresql_connection_attempts_maximum": (
                LIVE_POSTGRESQL_CONNECTION_ATTEMPTS_UPPER_BOUND_V2
            ),
            "first_refused_attempt": (LIVE_POSTGRESQL_CONNECTION_ATTEMPTS_UPPER_BOUND_V2 + 1),
            "automatic_retries": 0,
        },
    }


def render_live_postgresql_call_graph_v2() -> bytes:
    return (
        json.dumps(
            build_live_postgresql_call_graph_v2(),
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def validate_live_postgresql_call_graph_v2(repository_root: Path) -> dict[str, Any]:
    path = repository_root / CALL_GRAPH_RELATIVE_PATH
    try:
        if path.is_symlink():
            raise OSError
        payload = path.read_bytes()
        document = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("DATA_TORRENT_LIVE_POSTGRESQL_CALL_GRAPH_INVALID") from None
    expected = build_live_postgresql_call_graph_v2()
    canonical = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if (
        document != expected
        or payload != render_live_postgresql_call_graph_v2()
        or hashlib.sha256(payload).hexdigest() != DATA_TORRENT_LIVE_V2_POSTGRESQL_CALL_GRAPH_SHA256
        or hashlib.sha256(canonical).hexdigest()
        != DATA_TORRENT_LIVE_V2_POSTGRESQL_CALL_GRAPH_CANONICAL_SHA256
    ):
        raise ValueError("DATA_TORRENT_LIVE_POSTGRESQL_CALL_GRAPH_INVALID")
    return expected


__all__ = [
    "CALL_GRAPH_RELATIVE_PATH",
    "LIVE_POSTGRESQL_CONNECTION_ATTEMPTS_NOMINAL_V2",
    "LIVE_POSTGRESQL_CONNECTION_ATTEMPTS_UPPER_BOUND_V2",
    "LIVE_POSTGRESQL_DIRECT_READS_V2",
    "LIVE_POSTGRESQL_FUNCTION_READS_FALLBACK_MAXIMUM_V2",
    "LIVE_POSTGRESQL_FUNCTION_READS_NOMINAL_V2",
    "LIVE_POSTGRESQL_MUTATING_FUNCTIONS_V2",
    "build_live_postgresql_call_graph_v2",
    "render_live_postgresql_call_graph_v2",
    "validate_live_postgresql_call_graph_v2",
]
