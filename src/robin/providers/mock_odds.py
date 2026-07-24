"""Fournisseur synthétique de snapshots prospectifs pour tests et démonstration."""

from __future__ import annotations

from collections.abc import Iterable

from robin.domain.odds import OddsSnapshot


class MockOddsProvider:
    def __init__(self, snapshots: Iterable[OddsSnapshot]) -> None:
        self._snapshots = tuple(snapshots)

    def get_odds(self) -> tuple[OddsSnapshot, ...]:
        return self._snapshots

