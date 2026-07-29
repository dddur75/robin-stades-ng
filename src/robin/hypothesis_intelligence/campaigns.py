"""Separated universal hypothesis campaigns and multiplicity families."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from robin.hypothesis_intelligence.contracts import canonical_sha256
from robin.hypothesis_intelligence.universal_engines import DiscoveryBudget


@dataclass(frozen=True, slots=True)
class CampaignDefinition:
    campaign_id: str
    universe_id: str
    property_families: tuple[str, ...]
    sources: tuple[str, ...]
    targets: tuple[str, ...]
    markets: tuple[str, ...]
    budget: DiscoveryBudget
    multiplicity_family: str
    replay_policy: str
    revision: str
    data_gate: str

    @property
    def campaign_hash(self) -> str:
        return canonical_sha256(asdict(self))


DEFAULT_BUDGET = DiscoveryBudget()

CAMPAIGNS: tuple[CampaignDefinition, ...] = (
    CampaignDefinition(
        "J10_MARKET_SLICE_V1",
        "FOOTBALL_PROPERTY_UNIVERSE_V1",
        ("MARKET", "MATCH_COMPETITION"),
        ("FOOTBALL_DATA",),
        ("MATCH_RESULT", "GOALS_TOTAL"),
        ("1X2", "OVER_UNDER_2_5"),
        DEFAULT_BUDGET,
        "J10_MARKET_SLICE_V1",
        "CACHE_ONLY_IDENTICAL_HASH",
        "1.0.0",
        "HISTORICAL_RESEARCH_ONLY",
    ),
    CampaignDefinition(
        "UNIVERSAL_TEAM_FEATURES_V1",
        "FOOTBALL_PROPERTY_UNIVERSE_V1",
        ("STRENGTH_FORM", "CALENDAR_FATIGUE", "MATCH_COMPETITION"),
        ("ROBIN_DEEP_FOOTBALL",),
        ("MATCH_RESULT", "RESIDUAL_PERFORMANCE"),
        ("1X2",),
        DEFAULT_BUDGET,
        "UNIVERSAL_TEAM_FEATURES_V1",
        "CACHE_ONLY_IDENTICAL_HASH",
        "1.0.0",
        "PARTIAL_SOURCE_OBSERVED_AT",
    ),
    CampaignDefinition(
        "FORMATION_GRAPH_V1",
        "FOOTBALL_PROPERTY_UNIVERSE_V1",
        ("FORMATION_STRUCTURE", "ROLE_TACTICS", "CHEMISTRY_NETWORKS"),
        ("API_FOOTBALL_LINEUP",),
        ("MATCH_RESULT", "TEAM_GOALS"),
        ("1X2", "GOALS_TOTAL"),
        DEFAULT_BUDGET,
        "FORMATION_GRAPH_V1",
        "CHECKPOINTED_CANONICAL_QUEUE",
        "1.0.0",
        "DATA_GATE_BLOCKED",
    ),
    CampaignDefinition(
        "PLAYER_ROLE_GRAPH_V1",
        "FOOTBALL_PROPERTY_UNIVERSE_V1",
        ("PLAYER", "FOOTEDNESS_LATERALITY", "ROLE_TACTICS"),
        ("API_FOOTBALL_PLAYER", "TRACKING_NOT_CONFIGURED"),
        ("EVENT_COUNT", "PLAYER_AVAILABILITY"),
        ("PLAYER_PROPS_IF_PRICED",),
        DEFAULT_BUDGET,
        "PLAYER_ROLE_GRAPH_V1",
        "CHECKPOINTED_CANONICAL_QUEUE",
        "1.0.0",
        "DATA_GATE_BLOCKED",
    ),
    CampaignDefinition(
        "WEATHER_TACTICS_V1",
        "FOOTBALL_PROPERTY_UNIVERSE_V1",
        ("WEATHER", "STADIUM_PITCH", "ROLE_TACTICS"),
        ("FREE_ARCHIVED_FORECAST_NOT_CONFIGURED",),
        ("MATCH_RESULT", "EVENT_COUNT"),
        ("NO_MARKET_REQUIRED",),
        DEFAULT_BUDGET,
        "WEATHER_TACTICS_V1",
        "CHECKPOINTED_CANONICAL_QUEUE",
        "1.0.0",
        "DATA_GATE_BLOCKED",
    ),
    CampaignDefinition(
        "TRAVEL_FATIGUE_V1",
        "FOOTBALL_PROPERTY_UNIVERSE_V1",
        ("TRAVEL_LOGISTICS", "CALENDAR_FATIGUE", "PLAYER"),
        ("ROBIN_SCHEDULE", "ROUTE_SOURCE_NOT_CONFIGURED"),
        ("RESIDUAL_PERFORMANCE", "PLAYER_AVAILABILITY"),
        ("NO_MARKET_REQUIRED",),
        DEFAULT_BUDGET,
        "TRAVEL_FATIGUE_V1",
        "CHECKPOINTED_CANONICAL_QUEUE",
        "1.0.0",
        "DATA_GATE_BLOCKED",
    ),
    CampaignDefinition(
        "DISCIPLINE_REFEREE_V1",
        "FOOTBALL_PROPERTY_UNIVERSE_V1",
        ("DISCIPLINE_REFEREE", "MATCH_COMPETITION"),
        ("OFFICIAL_REPORT_NOT_CONFIGURED",),
        ("EVENT_COUNT", "MATCH_RESULT"),
        ("CARDS_IF_PRICED", "1X2"),
        DEFAULT_BUDGET,
        "DISCIPLINE_REFEREE_V1",
        "CHECKPOINTED_CANONICAL_QUEUE",
        "1.0.0",
        "DATA_GATE_BLOCKED",
    ),
    CampaignDefinition(
        "ATTACK_DEFENSE_V1",
        "FOOTBALL_PROPERTY_UNIVERSE_V1",
        ("ATTACK", "DEFENCE", "POSSESSION_PRESSING", "GOALKEEPER"),
        ("ROBIN_DEEP_FOOTBALL", "EVENT_SOURCE_NOT_CONFIGURED"),
        ("MATCH_RESULT", "TEAM_GOALS", "GOALS_TOTAL"),
        ("1X2", "OVER_UNDER_2_5"),
        DEFAULT_BUDGET,
        "ATTACK_DEFENSE_V1",
        "CACHE_ONLY_IDENTICAL_HASH",
        "1.0.0",
        "PARTIAL_GOALS_ONLY",
    ),
    CampaignDefinition(
        "LONG_TAIL_FOOTBALL_TREE_V1",
        "FOOTBALL_PROPERTY_UNIVERSE_V1",
        tuple(),
        ("ALL_VERSIONED_SOURCES",),
        (
            "MATCH_RESULT",
            "TEAM_GOALS",
            "EVENT_COUNT",
            "PLAYER_AVAILABILITY",
            "NO_MARKET_TARGET",
        ),
        ("OPTIONAL_MARKET",),
        DiscoveryBudget(
            maximum_materialized_nodes=10_000,
            maximum_evaluated_nodes=2_000,
            maximum_depth=12,
        ),
        "LONG_TAIL_FOOTBALL_TREE_V1",
        "CHECKPOINTED_CANONICAL_QUEUE",
        "1.0.0",
        "MIXED_DATA_GATES",
    ),
)


def campaign_catalog() -> list[dict[str, object]]:
    return [
        {
            **asdict(campaign),
            "campaign_hash": campaign.campaign_hash,
        }
        for campaign in CAMPAIGNS
    ]


__all__ = [
    "CAMPAIGNS",
    "DEFAULT_BUDGET",
    "CampaignDefinition",
    "campaign_catalog",
]
