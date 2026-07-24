"""Vocabulaires contrôlés du jalon 1."""

from enum import StrEnum


class QualityStatus(StrEnum):
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    MISSING = "MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SUSPECT_ZERO = "SUSPECT_ZERO"
    CORRECTED = "CORRECTED"
    CONFLICTING = "CONFLICTING"


class EntityType(StrEnum):
    COMPETITION = "competition"
    SEASON = "season"
    TEAM = "team"
    PLAYER = "player"
    REFEREE = "referee"
    FIXTURE = "fixture"
    BOOKMAKER = "bookmaker"
    MARKET = "market"
    SELECTION = "selection"
    ODDS_SNAPSHOT = "odds_snapshot"
    PREDICTION = "prediction"
    STRATEGY = "strategy"
    MODEL_VERSION = "model_version"


class MappingStatus(StrEnum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ReviewStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class FixtureStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    IN_PLAY = "IN_PLAY"
    FINISHED = "FINISHED"
    CORRECTED = "CORRECTED"


class MarketType(StrEnum):
    ONE_X_TWO = "1X2"
    DOUBLE_CHANCE = "DOUBLE_CHANCE"
    TOTAL_GOALS = "TOTAL_GOALS"
    BOTH_TEAMS_TO_SCORE = "BOTH_TEAMS_TO_SCORE"


class MarketScope(StrEnum):
    MATCH = "MATCH"
    TEAM = "TEAM"


class Selection(StrEnum):
    HOME = "HOME"
    DRAW = "DRAW"
    AWAY = "AWAY"
    HOME_OR_DRAW = "HOME_OR_DRAW"
    HOME_OR_AWAY = "HOME_OR_AWAY"
    DRAW_OR_AWAY = "DRAW_OR_AWAY"
    OVER = "OVER"
    UNDER = "UNDER"
    YES = "YES"
    NO = "NO"


class SettlementOutcome(StrEnum):
    WON = "WON"
    LOST = "LOST"
    PUSH = "PUSH"
    VOID = "VOID"
    UNSETTLED = "UNSETTLED"


class QuotePhase(StrEnum):
    OPENING = "OPENING"
    INTERMEDIATE = "INTERMEDIATE"
    CLOSING = "CLOSING"
