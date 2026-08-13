"""Explicit legacy de-vig adapters backed by the scientific truth kernel."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from robin.market_math import DevigInputError, devig_probabilities


def devig_proportionnel(cotes: Iterable[float | None]) -> np.ndarray:
    """Replay the explicit proportional complete-market protocol."""

    result = devig_probabilities(cotes, method="PROPORTIONAL")
    return np.asarray(result.fair_probabilities, dtype=float)


def devig_shin(
    cotes: Iterable[float | None],
    iterations: int = 100,
) -> np.ndarray:
    """Replay the frozen 100-iteration legacy Vague 1 Shin protocol."""

    if iterations != 100:
        raise ValueError("LEGACY_SHIN_ITERATION_VERSION_UNSUPPORTED")
    result = devig_probabilities(cotes, method="SHIN")
    return np.asarray(result.fair_probabilities, dtype=float)


def probas_justes(
    cotes: Iterable[float | None],
    *,
    methode: str,
) -> np.ndarray | None:
    """Compatibility adapter with no method fallback.

    The legacy surface historically returned ``None`` for an invalid market.
    Preserve that public shape while the central kernel keeps one explicit
    exception contract for scientific callers.
    """

    try:
        result = devig_probabilities(cotes, method=methode)
    except DevigInputError:
        return None
    return np.asarray(result.fair_probabilities, dtype=float)
