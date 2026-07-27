"""Bounded campaign registry and fail-closed gate routing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass

from robin.deep_football.contracts import DataGateStatus


@dataclass(frozen=True, slots=True)
class CampaignDefinition:
    campaign_id: str
    title: str
    required_gates: tuple[str, ...]
    provider_calls_allowed: int = 0
    odds_api_credits_allowed: int = 0
    cache_only: bool = True


CAMPAIGNS = (
    CampaignDefinition("11A", "Team and Calendar Deep Baseline", ("TEAM_GATE",)),
    CampaignDefinition(
        "11B",
        "Player Availability",
        ("PLAYER_GATE", "PLAYER_FORM_GATE", "ABSENCE_GATE"),
    ),
    CampaignDefinition(
        "11C",
        "Lineup Continuity",
        ("LINEUP_GATE", "STARTER_BASELINE_GATE"),
    ),
    CampaignDefinition(
        "11D",
        "Formation Matchups",
        ("LINEUP_GATE", "FORMATION_GATE"),
    ),
    CampaignDefinition("11E", "Owner Anchored Hypotheses", ()),
    CampaignDefinition(
        "11F",
        "Cross-League Transfer",
        ("TEAM_GATE", "MARKET_GATE"),
    ),
    CampaignDefinition(
        "11G",
        "Integrated Matchup Arena",
        (
            "TEAM_GATE",
            "PLAYER_GATE",
            "ABSENCE_GATE",
            "LINEUP_GATE",
            "FORMATION_GATE",
            "MARKET_GATE",
        ),
    ),
)


def campaign_manifest(
    gate_statuses: Mapping[str, DataGateStatus | str],
) -> list[dict[str, object]]:
    manifests: list[dict[str, object]] = []
    for campaign in CAMPAIGNS:
        blocked = [
            gate
            for gate in campaign.required_gates
            if str(gate_statuses.get(gate, "")) != DataGateStatus.READY.value
        ]
        manifests.append(
            {
                **asdict(campaign),
                "status": "DATA_GATE_BLOCKED" if blocked else "ELIGIBLE",
                "blocking_gates": blocked,
                "production_status": "PRODUCTION_LOCKED",
                "real_bets": False,
                "no_bet_default": True,
                "social_publishing_enabled": False,
                "demo_mode_enabled": False,
            }
        )
    return manifests
