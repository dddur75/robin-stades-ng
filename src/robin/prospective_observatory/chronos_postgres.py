"""Committed PostgreSQL function client for Chronos production adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError

from robin.prospective_observatory.chronos_control_plane import (
    ChronosControlPlaneError,
)

_SAFE_DATABASE_ERROR_CODES = frozenset(
    {
        "CHRONOS_APPEND_INPUT_INVALID",
        "CHRONOS_APPEND_ONLY_MUTATION_FORBIDDEN",
        "CHRONOS_AUTHORITY_ALREADY_CONSUMED",
        "CHRONOS_AUTHORITY_EXECUTOR_REQUIRED",
        "CHRONOS_AUTHORITY_NOT_ACTIVE",
        "CHRONOS_AUTHORITY_NOT_FOUND",
        "CHRONOS_AUTHORITY_TTL_INVALID",
        "CHRONOS_CLAIM_INPUT_INVALID",
        "CHRONOS_CODE_REVISION_MISMATCH",
        "CHRONOS_CONTROL_PLANE_GENERATION_MISMATCH",
        "CHRONOS_DISPATCH_PERMIT_ALREADY_EXISTS",
        "CHRONOS_EFFECT_NOT_RESERVED",
        "CHRONOS_EFFECT_TRANSITION_FORBIDDEN",
        "CHRONOS_EXTERNAL_EFFECT_ACCOUNTING_INVALID",
        "CHRONOS_EXTERNAL_EFFECT_BUDGET_EXCEEDED",
        "CHRONOS_EXTERNAL_EFFECT_BUDGET_INVALID",
        "CHRONOS_EXTERNAL_EFFECT_EVENT_CONFLICT",
        "CHRONOS_EXTERNAL_EFFECT_INPUT_INVALID",
        "CHRONOS_EXTERNAL_EFFECT_PERMIT_CONFLICT",
        "CHRONOS_EXTERNAL_EFFECT_PERMIT_NOT_FOUND",
        "CHRONOS_EXTERNAL_EFFECT_TRANSITION_FORBIDDEN",
        "CHRONOS_EXTERNAL_EFFECTS_UNACCOUNTED",
        "CHRONOS_EVENT_AUTHORITY_MISMATCH",
        "CHRONOS_GENERATION_NONCE_INVALID",
        "CHRONOS_GITHUB_RUN_IDENTITY_INVALID",
        "CHRONOS_GITHUB_RUN_IDENTITY_MISMATCH",
        "CHRONOS_OPERATION_ID_MISMATCH",
        "CHRONOS_OPPORTUNITY_ID_COLLISION",
        "CHRONOS_OPPORTUNITY_ID_MISMATCH",
        "CHRONOS_OPPORTUNITY_INPUT_INVALID",
        "CHRONOS_OPPORTUNITY_NOT_FOUND",
        "CHRONOS_OPPORTUNITY_WINNER_REQUIRED",
        "CHRONOS_R2_GET_PERMIT_ALREADY_EXISTS",
        "CHRONOS_RUNTIME_WRITER_REQUIRED",
        "CHRONOS_SERVER_EPOCH_MISMATCH",
        "CHRONOS_TORRENT_ACCEPTANCE_FAILED",
        "CHRONOS_TORRENT_ARTIFACT_CONTRACT_INVALID",
        "CHRONOS_TORRENT_BATCH_CONFLICT",
        "CHRONOS_TORRENT_BATCH_INPUT_INVALID",
        "CHRONOS_TORRENT_DURABILITY_NOT_PROVEN",
    }
)


def _safe_database_error_code(error: DBAPIError) -> str:
    diagnostic = str(error.orig)
    for code in _SAFE_DATABASE_ERROR_CODES:
        if code in diagnostic:
            return code
    return "CHRONOS_POSTGRESQL_CALL_FAILED"


class SQLAlchemyPostgresFunctionClient:
    """Commit each function call before its result becomes an effect permit."""

    def __init__(self, engine: Engine) -> None:
        if engine.dialect.name != "postgresql":
            raise ChronosControlPlaneError("CHRONOS_POSTGRESQL_REQUIRED")
        # This client always transports the raw generation nonce. Even callers that
        # did not construct their engine through build_engine get redacted SQL logs.
        engine.hide_parameters = True
        self._engine = engine

    def fetch_one(
        self,
        statement: str,
        parameters: Sequence[object],
    ) -> Mapping[str, object]:
        try:
            with self._engine.begin() as connection:
                row = (
                    connection.exec_driver_sql(
                        statement,
                        tuple(parameters),
                    )
                    .mappings()
                    .one_or_none()
                )
                result = {} if row is None else dict(row)
        except DBAPIError as error:
            safe_error_code = _safe_database_error_code(error)
        else:
            # Exiting engine.begin commits before the durable permit is returned.
            return result
        # Raise outside the handler so even __context__ cannot retain the
        # statement/parameter-bearing DBAPIError and its raw generation nonce.
        raise ChronosControlPlaneError(safe_error_code) from None


__all__ = ["SQLAlchemyPostgresFunctionClient"]
