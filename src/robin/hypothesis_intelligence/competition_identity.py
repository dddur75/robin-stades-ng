"""Canonical competition identities used by historical and live hypotheses."""

from __future__ import annotations

import unicodedata
from dataclasses import asdict, dataclass

from robin.hypothesis_intelligence.contracts import canonical_sha256


def _normalise_alias(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(ascii_value.casefold().replace("-", " ").split())


@dataclass(frozen=True, slots=True)
class CompetitionIdentity:
    canonical_competition_key: str
    provider: str
    provider_competition_id: str
    display_name_fr: str
    display_name_en: str
    historical_aliases: tuple[str, ...]
    provider_aliases: tuple[str, ...]

    @property
    def identity_hash(self) -> str:
        return canonical_sha256(asdict(self))

    @property
    def aliases(self) -> tuple[str, ...]:
        return (
            self.canonical_competition_key,
            self.display_name_fr,
            self.display_name_en,
            *self.historical_aliases,
            *self.provider_aliases,
        )


COMPETITIONS: tuple[CompetitionIdentity, ...] = (
    CompetitionIdentity(
        canonical_competition_key="api-football:61",
        provider="API_FOOTBALL",
        provider_competition_id="61",
        display_name_fr="Ligue 1",
        display_name_en="Ligue 1",
        historical_aliases=("France Ligue 1", "F1"),
        provider_aliases=("Ligue 1",),
    ),
    CompetitionIdentity(
        canonical_competition_key="api-football:39",
        provider="API_FOOTBALL",
        provider_competition_id="39",
        display_name_fr="Premier League",
        display_name_en="Premier League",
        historical_aliases=("English Premier League", "E0"),
        provider_aliases=("Premier League",),
    ),
    CompetitionIdentity(
        canonical_competition_key="api-football:140",
        provider="API_FOOTBALL",
        provider_competition_id="140",
        display_name_fr="Liga",
        display_name_en="La Liga",
        historical_aliases=("La Liga", "Primera División", "SP1"),
        provider_aliases=("Liga", "LaLiga"),
    ),
    CompetitionIdentity(
        canonical_competition_key="api-football:78",
        provider="API_FOOTBALL",
        provider_competition_id="78",
        display_name_fr="Bundesliga",
        display_name_en="Bundesliga",
        historical_aliases=("Germany Bundesliga", "D1"),
        provider_aliases=("Bundesliga",),
    ),
    CompetitionIdentity(
        canonical_competition_key="api-football:135",
        provider="API_FOOTBALL",
        provider_competition_id="135",
        display_name_fr="Serie A",
        display_name_en="Serie A",
        historical_aliases=("Italy Serie A", "I1"),
        provider_aliases=("Serie A",),
    ),
)


def _build_alias_index() -> dict[str, CompetitionIdentity]:
    index: dict[str, CompetitionIdentity] = {}
    for competition in COMPETITIONS:
        for alias in competition.aliases:
            key = _normalise_alias(alias)
            existing = index.get(key)
            if existing is not None and existing != competition:
                raise ValueError(f"COMPETITION_ALIAS_COLLISION:{alias}")
            index[key] = competition
    return index


COMPETITION_ALIAS_INDEX = _build_alias_index()
COMPETITION_PROVIDER_INDEX = {
    (item.provider.casefold(), item.provider_competition_id): item for item in COMPETITIONS
}


def resolve_competition(value: str) -> CompetitionIdentity:
    try:
        return COMPETITION_ALIAS_INDEX[_normalise_alias(value)]
    except KeyError as error:
        raise ValueError(f"UNKNOWN_COMPETITION_IDENTITY:{value}") from error


def resolve_provider_competition(
    provider: str,
    provider_competition_id: str,
) -> CompetitionIdentity:
    try:
        return COMPETITION_PROVIDER_INDEX[(provider.casefold(), provider_competition_id)]
    except KeyError as error:
        raise ValueError(
            f"UNKNOWN_PROVIDER_COMPETITION_IDENTITY:{provider}:{provider_competition_id}"
        ) from error


def same_competition(left: str, right: str) -> bool:
    return (
        resolve_competition(left).canonical_competition_key
        == resolve_competition(right).canonical_competition_key
    )


def competition_catalog() -> list[dict[str, object]]:
    return [
        {
            **asdict(item),
            "identity_hash": item.identity_hash,
        }
        for item in COMPETITIONS
    ]


__all__ = [
    "COMPETITIONS",
    "COMPETITION_ALIAS_INDEX",
    "COMPETITION_PROVIDER_INDEX",
    "CompetitionIdentity",
    "competition_catalog",
    "resolve_competition",
    "resolve_provider_competition",
    "same_competition",
]
