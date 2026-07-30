"""Versioned symbolic football property universe.

The catalogue is deliberately declarative: unavailable properties remain
representable and fail closed at their data gate instead of disappearing from
the scientific universe.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum

from robin.hypothesis_intelligence.contracts import canonical_sha256

PROPERTY_UNIVERSE_ID = "FOOTBALL_PROPERTY_UNIVERSE_V1"
PROPERTY_UNIVERSE_VERSION = "1.0.0"


class PropertyDataType(StrEnum):
    BOOLEAN = "BOOLEAN"
    INTEGER = "INTEGER"
    QUANTITY = "QUANTITY"
    RATE = "RATE"
    PROBABILITY = "PROBABILITY"
    ENUM = "ENUM"
    CATEGORICAL_SET = "CATEGORICAL_SET"
    ENTITY_REF = "ENTITY_REF"
    TIMESTAMP = "TIMESTAMP"
    INTERVAL = "INTERVAL"
    GEO_POINT = "GEO_POINT"
    VECTOR = "VECTOR"
    DISTRIBUTION = "DISTRIBUTION"
    EVENT_SERIES = "EVENT_SERIES"
    TEXT_EVIDENCE = "TEXT_EVIDENCE"
    GRAPH_NODE_REF = "GRAPH_NODE_REF"
    GRAPH_EDGE_REF = "GRAPH_EDGE_REF"
    HYPEREDGE_REF = "HYPEREDGE_REF"


class AvailabilityStatus(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    DATA_GATE_BLOCKED = "DATA_GATE_BLOCKED"


class PropertyRole(StrEnum):
    PREDICTOR = "PREDICTOR"
    TARGET = "TARGET"
    IDENTITY = "IDENTITY"
    PROVENANCE = "PROVENANCE"


class SemanticRole(StrEnum):
    """Public semantic role, kept outside the frozen scientific payload."""

    FOOTBALL_PREDICTOR = "FOOTBALL_PREDICTOR"
    FOOTBALL_CONTEXT = "FOOTBALL_CONTEXT"
    FOOTBALL_RELATION = "FOOTBALL_RELATION"
    TARGET = "TARGET"
    MARKET_PROPERTY = "MARKET_PROPERTY"
    IDENTIFIER = "IDENTIFIER"
    DATA_QUALITY_METADATA = "DATA_QUALITY_METADATA"
    AVAILABILITY_METADATA = "AVAILABILITY_METADATA"
    PROVENANCE_METADATA = "PROVENANCE_METADATA"
    NEGATIVE_CONTROL = "NEGATIVE_CONTROL"


PUBLIC_HYPOTHESIS_SEMANTIC_ROLES = frozenset(
    {
        SemanticRole.FOOTBALL_PREDICTOR,
        SemanticRole.FOOTBALL_CONTEXT,
        SemanticRole.FOOTBALL_RELATION,
        SemanticRole.MARKET_PROPERTY,
    }
)


@dataclass(frozen=True, slots=True)
class PropertyDefinition:
    property_id: str
    display_name_fr: str
    display_name_en: str
    description_fr: str
    family: str
    subfamily: str
    tags: tuple[str, ...]
    subtags: tuple[str, ...]
    entity: str
    data_type: PropertyDataType
    unit: str
    source: str
    source_field: str
    raw_or_derived: str
    derivation_contract: str
    availability_time: str
    valid_cutoffs: tuple[str, ...]
    temporal_gate: str
    quality_gate: str
    missingness_policy: str
    allowed_operators: tuple[str, ...]
    allowed_relations: tuple[str, ...]
    allowed_targets: tuple[str, ...]
    version: str
    role: PropertyRole
    availability_status: AvailabilityStatus
    blocking_reason: str | None
    observation_type: str
    physical_dimension: str
    source_schema_hash: str
    event_time_field: str
    published_at_field: str
    provider_updated_at_field: str
    observed_at_field: str
    ingested_at_field: str
    valid_from_field: str
    valid_to_field: str

    @property
    def property_hash(self) -> str:
        payload = asdict(self)
        payload["data_type"] = self.data_type.value
        payload["role"] = self.role.value
        payload["availability_status"] = self.availability_status.value
        return canonical_sha256(payload)

    @property
    def semantic_role(self) -> SemanticRole:
        """Classification used by public surfaces without changing legacy hashes."""

        return semantic_role_for_property(self)


@dataclass(frozen=True, slots=True)
class FamilySeed:
    family: str
    display_fr: str
    entity: str
    source: str
    availability: AvailabilityStatus
    blocking_reason: str | None
    properties: tuple[tuple[str, str], ...]


def _pairs(value: str) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for item in value.split("|"):
        identifier, display_fr = item.split(":", maxsplit=1)
        pairs.append((identifier, display_fr))
    return tuple(pairs)


FAMILY_SEEDS: tuple[FamilySeed, ...] = (
    FamilySeed(
        "MATCH_COMPETITION",
        "Match et compétition",
        "MATCH",
        "API_FOOTBALL_FIXTURE",
        AvailabilityStatus.PARTIAL,
        "HISTORICAL_POINT_IN_TIME_COVERAGE_PARTIAL",
        _pairs(
            "competition:compétition|season:saison|phase:phase|matchday:journée|"
            "round:tour|venue_role:domicile ou extérieur|neutral_ground:terrain neutre|"
            "tie_leg:manche aller ou retour|aggregate_score:score cumulé|"
            "standings_stake:enjeu du classement|relegation_stake:enjeu de relégation|"
            "title_stake:enjeu du titre|qualification_stake:enjeu de qualification|"
            "derby:derby|rivalry:rivalité|knockout:élimination directe|"
            "first_matchday:première journée|last_matchday:dernière journée|"
            "post_break_restart:reprise après trêve|local_kickoff_time:heure locale|"
            "weekday:jour de la semaine|month:mois|season_period:période de saison|"
            "behind_closed_doors:huis clos|stadium_change:changement de stade|"
            "kickoff_change:changement d’horaire|simultaneous_match_dependency:"
            "dépendance à un autre match"
        ),
    ),
    FamilySeed(
        "STADIUM_PITCH",
        "Stade et terrain",
        "VENUE_VERSION",
        "API_FOOTBALL_VENUE_OR_OPEN_DATA",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "NO_VERSIONED_HISTORICAL_PITCH_SOURCE",
        _pairs(
            "stadium:stade|pitch_length:longueur du terrain|pitch_width:largeur du terrain|"
            "altitude:altitude|latitude:latitude|longitude:longitude|"
            "coordinates:coordonnées géographiques|surface:surface|"
            "grass_type:type de pelouse|pitch_state:état du terrain|drainage:drainage|"
            "roof_state:état du toit|pitch_orientation:orientation|"
            "wind_exposure:exposition au vent|stadium_familiarity:familiarité avec le stade|"
            "temporary_venue:terrain temporaire|crowd_size:affluence|"
            "acoustic_pressure:pression acoustique|ball_specification:caractéristiques du ballon|"
            "footwear_surface_fit:adéquation chaussures-surface"
        ),
    ),
    FamilySeed(
        "WEATHER",
        "Météo",
        "WEATHER_OBSERVATION",
        "FREE_ARCHIVED_FORECAST_NOT_CONFIGURED",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "NO_FREE_LICENSED_POINT_IN_TIME_WEATHER_ARCHIVE",
        _pairs(
            "temperature:température|feels_like:température ressentie|humidity:humidité|"
            "dew_point:point de rosée|wet_bulb:température humide|rain_rate:pluie|"
            "rain_accumulation:cumul de pluie|snow:neige|frost:gel|wind_speed:vent|"
            "wind_gust:rafales|wind_direction:direction du vent|"
            "crosswind_component:vent par rapport à l’axe du terrain|thunderstorm:orage|"
            "visibility:visibilité|fog:brouillard|cloud_cover:couverture nuageuse|"
            "pressure:pression|solar_radiation:rayonnement solaire|air_quality:qualité de l’air|"
            "departure_arrival_climate_delta:différence climatique départ-arrivée|"
            "forecast_at_cutoff:prévision au cutoff|actual_weather:météo réelle|"
            "forecast_error:écart prévision-réalité|roof_open:toit ouvert"
        ),
    ),
    FamilySeed(
        "TRAVEL_LOGISTICS",
        "Déplacements et logistique",
        "TRAVEL_LEG",
        "DERIVED_SCHEDULE_AND_UNCONFIGURED_ROUTE_SOURCE",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "REAL_TRAVEL_ITINERARY_AND_ARRIVAL_TIMES_UNAVAILABLE",
        _pairs(
            "travel_distance:distance|travel_duration:durée|timezone_delta:écart de fuseau|"
            "altitude_delta:écart d’altitude|climate_delta:écart climatique|"
            "arrival_time:heure d’arrivée|nights_on_site:nuits sur place|"
            "same_day_travel:déplacement le jour du match|travel_delay:retard|"
            "return_from_europe:retour européen|international_return:retour de sélection|"
            "cumulative_kilometres:kilomètres cumulés|consecutive_away_matches:"
            "déplacements consécutifs|venue_sequence:séquence domicile-extérieur|"
            "post_travel_recovery:récupération après voyage|circadian_offset:décalage circadien"
        ),
    ),
    FamilySeed(
        "CALENDAR_FATIGUE",
        "Calendrier et fatigue",
        "TEAM_FIXTURE",
        "ROBIN_DEEP_FOOTBALL",
        AvailabilityStatus.PARTIAL,
        "REST_DAYS_READY_OTHER_LOAD_FIELDS_BLOCKED",
        _pairs(
            "rest_days:jours de repos|matches_5d:matchs sur 5 jours|matches_7d:matchs sur 7 jours|"
            "matches_10d:matchs sur 10 jours|matches_14d:matchs sur 14 jours|"
            "matches_21d:matchs sur 21 jours|matches_30d:matchs sur 30 jours|"
            "recent_extra_time:prolongation récente|recent_penalty_shootout:tirs au but récents|"
            "individual_load:charge individuelle|collective_load:charge collective|"
            "recent_minutes:minutes récentes|rest_differential:différentiel de repos|"
            "next_match_importance:importance du prochain match|congestion:congestion|"
            "restart_phase:reprise|rotation:rotation"
        ),
    ),
    FamilySeed(
        "STRENGTH_FORM",
        "Force et forme",
        "TEAM_FIXTURE",
        "ROBIN_DEEP_FOOTBALL",
        AvailabilityStatus.PARTIAL,
        "SOURCE_OBSERVED_AT_NOT_PROVEN_ROW_BY_ROW",
        _pairs(
            "elo:Elo|ranking:classement|points:points|goals:buts|xg:xG|xga:xGA|"
            "xg_difference:différence xG|form:forme|weighted_form:forme pondérée|"
            "opponent_adjusted_form:forme ajustée à l’adversaire|streak:série|"
            "volatility:volatilité|regime_change:changement de régime|"
            "home_away_performance:performance domicile-extérieur|"
            "favourite_outsider_performance:performance favori-outsider|"
            "after_result_performance:performance après victoire, nul ou défaite"
        ),
    ),
    FamilySeed(
        "ATTACK",
        "Attaque",
        "TEAM_FIXTURE",
        "HISTORICAL_MATCH_RESULTS_AND_EVENT_SOURCE",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "EVENT_LEVEL_ATTACK_HISTORY_NOT_POINT_IN_TIME",
        _pairs(
            "shots:tirs|shots_on_target:tirs cadrés|blocked_shots:tirs bloqués|"
            "shots_inside_box:tirs dans la surface|shots_outside_box:tirs hors surface|"
            "big_chances:grosses occasions|xg_per_shot:xG par tir|goals_scored:buts marqués|"
            "finishing_efficiency:efficacité|crosses:centres|cutbacks:centres en retrait|"
            "key_passes:passes clés|through_balls:passes en profondeur|transitions:transitions|"
            "settled_attack:attaque placée|corners_for:corners obtenus|"
            "free_kicks_for:coups francs obtenus|player_dependency:dépendance à un joueur|"
            "left_production:production côté gauche|right_production:production côté droit|"
            "central_production:production dans l’axe"
        ),
    ),
    FamilySeed(
        "DEFENCE",
        "Défense",
        "TEAM_FIXTURE",
        "HISTORICAL_MATCH_RESULTS_AND_EVENT_SOURCE",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "EVENT_LEVEL_DEFENCE_HISTORY_NOT_POINT_IN_TIME",
        _pairs(
            "goals_conceded:buts encaissés|xga:xGA|shots_conceded:tirs concédés|"
            "shots_on_target_conceded:tirs cadrés concédés|"
            "big_chances_conceded:grosses occasions concédées|errors:erreurs|"
            "dangerous_turnovers:pertes dangereuses|aerial_defence:défense aérienne|"
            "transition_defence:défense de transition|set_piece_defence:défense sur coups de pied arrêtés|"
            "left_vulnerability:vulnérabilité gauche|right_vulnerability:vulnérabilité droite|"
            "central_vulnerability:vulnérabilité axiale|high_line:ligne haute|"
            "defensive_block:bloc défensif|tackles:tacles|interceptions:interceptions|duels:duels|"
            "rest_defence:équilibre défensif résiduel"
        ),
    ),
    FamilySeed(
        "POSSESSION_PRESSING",
        "Possession, relance et pressing",
        "TEAM_FIXTURE",
        "EVENT_OR_TRACKING_SOURCE_NOT_CONFIGURED",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "EVENT_AND_TRACKING_COVERAGE_UNAVAILABLE",
        _pairs(
            "possession:possession|passes:passes|progressive_passes:passes progressives|"
            "pressure_exits:sorties de pression|losses_under_pressure:pertes sous pression|"
            "short_build_up:relances courtes|long_build_up:relances longues|pressing:pressing|"
            "counter_pressing:contre-pressing|high_recoveries:récupérations hautes|ppda:PPDA|"
            "field_tilt:inclinaison du terrain|circulation_speed:vitesse de circulation|"
            "width:largeur|directness:jeu direct|pressing_trigger:déclencheur de pressing|"
            "pressing_trap:piège de pressing|third_man:troisième homme|half_space_use:"
            "occupation des demi-espaces"
        ),
    ),
    FamilySeed(
        "SET_PIECES",
        "Coups de pied arrêtés",
        "SET_PIECE_ROUTINE",
        "EVENT_OR_TRACKING_SOURCE_NOT_CONFIGURED",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "SET_PIECE_ROUTINES_AND_TRAJECTORIES_UNAVAILABLE",
        _pairs(
            "corners_for:corners pour|corners_against:corners contre|corner_xg:xG sur corner|"
            "free_kicks:coups francs|penalties:pénaltys|available_takers:tireurs disponibles|"
            "team_height:taille collective|aerial_defence:défense aérienne|"
            "goalkeeper_aerial:gardien aérien|taker_absence:absence d’un tireur|"
            "weather_interaction:interaction vent-pluie|routine_type:type de routine|"
            "delivery_trajectory:trajectoire|target_zone:zone visée|marking_scheme:"
            "marquage zonal ou individuel"
        ),
    ),
    FamilySeed(
        "PLAYER",
        "Joueurs",
        "PLAYER_FIXTURE",
        "API_FOOTBALL_PLAYER",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "PLAYER_HISTORY_NOT_POINT_IN_TIME_ACROSS_FIVE_LEAGUES",
        _pairs(
            "identity:identité|position:poste|role:rôle|age:âge|height:taille|experience:expérience|"
            "preferred_foot:pied préféré sourcé|side:côté|minutes:minutes|starts:titularisations|"
            "substitute_appearances:entrées en jeu|goals:buts|assists:passes décisives|shots:tirs|"
            "xg:xG|xa:xA|duels:duels|interceptions:interceptions|tackles:tacles|fouls:fautes|"
            "cards:cartons|errors:erreurs|form:forme|load:charge|"
            "partner_performance:performance avec partenaires|profile_matchup:"
            "performance contre profils|speed:vitesse|acceleration:accélération|"
            "endurance:endurance|jump: détente|press_resistance:résistance au pressing|"
            "versatility:polyvalence|out_of_position:joueur hors poste"
        ),
    ),
    FamilySeed(
        "FOOTEDNESS_LATERALITY",
        "Pieds, côtés et latéralité",
        "PLAYER_ROLE_ASSIGNMENT",
        "SOURCED_PLAYER_PROFILE",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "SOURCED_FOOTEDNESS_COVERAGE_ZERO",
        _pairs(
            "wing_side:côté de l’ailier|dominant_foot:pied dominant|natural_inverted_foot:"
            "pied naturel ou faux pied|centre_back_foot_pair:pieds du duo central|"
            "fullback_foot_fit:pied du latéral|front_three_foot_distribution:"
            "distribution des pieds du trio offensif|wing_fullback_lane:couloir ailier-latéral|"
            "direct_defender_foot:pied du défenseur direct|offensive_asymmetry:asymétrie offensive|"
            "defensive_asymmetry:asymétrie défensive|bilaterality:bilatéralité"
        ),
    ),
    FamilySeed(
        "LINEUP_CONTINUITY",
        "Compositions et continuité",
        "LINEUP_UNIT",
        "API_FOOTBALL_LINEUP",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "HISTORICAL_LINEUPS_OBSERVED_POST_MATCH",
        _pairs(
            "official_xi:onze officiel|bench:banc|usual_starters:titulaires habituels|"
            "changes:changements|changes_by_line:changements par ligne|continuity:continuité|"
            "common_minutes:minutes communes|centre_back_pair:duo central|"
            "midfield_triangle:triangle du milieu|forward_line:ligne offensive|"
            "out_of_position_players:joueurs hors poste|average_age:âge moyen|"
            "bench_depth:profondeur du banc|natural_replacements:remplaçants naturels|"
            "forced_rotation:rotation forcée|voluntary_rotation:rotation volontaire"
        ),
    ),
    FamilySeed(
        "ABSENCE_RETURN",
        "Absences et retours",
        "PLAYER_AVAILABILITY",
        "API_FOOTBALL_INJURY_AND_OFFICIAL_INFORMATION",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "ABSENCE_PUBLICATION_TIME_NOT_PROVEN",
        _pairs(
            "injured:blessé|suspended:suspendu|ill:malade|doubtful:incertain|returning:retour|"
            "matches_since_return:matchs depuis le retour|goalkeeper_absent:gardien absent|"
            "centre_backs_absent:centraux absents|top_scorer_absent:meilleur buteur absent|"
            "creator_absent:créateur absent|missing_minutes_share:part des minutes absente|"
            "missing_goals_share:part des buts absente|missing_xg_share:part du xG absente|"
            "natural_replacement_available:remplaçant naturel disponible|"
            "line_absence_count:cumul d’absences par ligne|return_to_training:"
            "retour à l’entraînement|medical_clearance:autorisation médicale|"
            "minutes_restriction:restriction de minutes|relapse_risk:risque de rechute"
        ),
    ),
    FamilySeed(
        "DISCIPLINE_REFEREE",
        "Discipline et arbitrage",
        "OFFICIAL_ASSIGNMENT",
        "API_FOOTBALL_OR_OFFICIAL_REPORT",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "REFEREE_ASSIGNMENT_AND_DISCIPLINE_CUTOFF_NOT_PROVEN",
        _pairs(
            "yellow_cards:cartons jaunes|red_cards:cartons rouges|recent_cards:cartons récents|"
            "fouls:fautes|cards_per_foul:cartons par faute|suspension_threat:"
            "joueur sous menace de suspension|threatened_players:nombre de joueurs menacés|"
            "threatened_centre_backs:centraux menacés|return_from_suspension:"
            "retour de suspension|competition_rules:règles disciplinaires de la compétition|"
            "referee:arbitre|referee_cards:cartons de l’arbitre|referee_reds:rouges de l’arbitre|"
            "referee_penalties:pénaltys de l’arbitre|style_interaction:"
            "interaction arbitre-équipe-style|var:VAR|derby_stake:interaction derby-enjeu|"
            "assistant_referees:arbitres assistants|var_official:arbitre VAR"
        ),
    ),
    FamilySeed(
        "FORMATION_STRUCTURE",
        "Formations et structures",
        "TACTICAL_STATE",
        "API_FOOTBALL_LINEUP_OR_TRACKING",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "FORMATION_OBSERVATION_NOT_POINT_IN_TIME",
        _pairs(
            "formation:formation|home_away_matchup:confrontation formation domicile-extérieur|"
            "usual_formation:formation habituelle|rare_formation:formation rare|"
            "first_use:premier usage|formation_change:changement de formation|"
            "formation_continuity:continuité de formation|in_possession_shape:"
            "structure avec ballon|out_of_possession_shape:structure sans ballon|"
            "build_up_shape:structure de relance|pressing_shape:structure de pressing|"
            "formation_weather_matchup:interaction formation-météo|"
            "formation_fatigue_matchup:interaction formation-fatigue|"
            "formation_market_matchup:interaction formation-marché"
        ),
    ),
    FamilySeed(
        "ROLE_TACTICS",
        "Rôles et tactiques",
        "PLAYER_ROLE_ASSIGNMENT",
        "EVENT_OR_TRACKING_SOURCE_NOT_CONFIGURED",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "ROLE_ASSIGNMENTS_AND_DYNAMIC_TACTICS_UNAVAILABLE",
        _pairs(
            "false_nine:faux neuf|target_player:pivot|inverted_winger:ailier inversé|"
            "wide_winger:ailier de débordement|wingback:piston|inverted_fullback:"
            "latéral intérieur|playmaker:meneur|holding_midfielder:sentinelle|"
            "double_pivot:double pivot|ball_playing_defender:central relanceur|"
            "stopper:stoppeur|sweeper_keeper:gardien-libéro|high_line:ligne haute|"
            "low_block:bloc bas|pressing:pressing|transition:transition|direct_play:jeu direct|"
            "possession_style:possession|width:largeur|side_overload:surcharge d’un côté|"
            "marking_scheme:schéma de marquage|cover_shadow:ombre de couverture|"
            "overlap:chevauchement|underlap:sous-chevauchement|rotation:permutation"
        ),
    ),
    FamilySeed(
        "COACH",
        "Entraîneur et staff",
        "COACH_TENURE",
        "API_FOOTBALL_COACH_AND_MATCH_EVENTS",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "COACH_DECISION_HISTORY_INCOMPLETE",
        _pairs(
            "identity:identité|tenure:ancienneté|first_match:première rencontre|"
            "recent_change:changement récent|formations:formations utilisées|rotation:rotation|"
            "substitutions:substitutions|style:style|experience:expérience|"
            "style_opposition:opposition de styles|after_loss_response:réponse après défaite|"
            "congestion_response:réponse en congestion|half_time_adjustment:"
            "ajustement à la mi-temps|game_state_management:gestion de l’état du score|"
            "staff_continuity:continuité du staff|opponent_familiarity:familiarité avec l’adversaire"
        ),
    ),
    FamilySeed(
        "GOALKEEPER",
        "Gardien",
        "PLAYER_FIXTURE",
        "API_FOOTBALL_PLAYER_OR_EVENT_SOURCE",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "GOALKEEPER_ADVANCED_HISTORY_UNAVAILABLE",
        _pairs(
            "starter_status:statut titulaire-remplaçant|experience:expérience|saves:arrêts|"
            "save_rate:taux d’arrêts|aerial_claims:sorties aériennes|distribution:jeu au pied|"
            "errors:erreurs|penalties:pénaltys arrêtés|defence_continuity:"
            "continuité avec la défense|weather_cross_interaction:interaction vent-pluie-centres|"
            "post_shot_xg:PSxG|sweeper_actions:actions de gardien-libéro"
        ),
    ),
    FamilySeed(
        "BENCH_SUBSTITUTIONS",
        "Banc et substitutions",
        "BENCH_UNIT",
        "API_FOOTBALL_LINEUP_AND_EVENTS",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "BENCH_POINT_IN_TIME_AND_ROLE_HISTORY_UNAVAILABLE",
        _pairs(
            "depth:profondeur|relative_quality:qualité relative|profiles:profils disponibles|"
            "natural_replacements:remplaçants naturels|historical_impact:impact historique|"
            "attacking_options:solutions offensives|defensive_options:solutions défensives|"
            "speed:vitesse|experience:expérience|early_substitutions:substitutions précoces|"
            "late_substitutions:substitutions tardives|first_attacking_sub_minute:"
            "minute du premier changement offensif"
        ),
    ),
    FamilySeed(
        "CHEMISTRY_NETWORKS",
        "Réseaux et complémentarités",
        "TACTICAL_UNIT",
        "EVENT_OR_TRACKING_SOURCE_NOT_CONFIGURED",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "PASS_NETWORK_AND_POINT_IN_TIME_COHESION_UNAVAILABLE",
        _pairs(
            "common_minutes:minutes communes|co_starts:co-titularisations|pass_network:"
            "réseau de passes|centrality:centralité|dependency:dépendance|attacking_pair:"
            "duo offensif|centre_back_pair:duo central|midfield_triangle:triangle du milieu|"
            "wing_fullback_lane:couloir ailier-latéral|goalkeeper_defence:"
            "gardien-charnière|network_break:rupture de réseau|network_entropy:entropie du réseau|"
            "replacement_cost:coût de remplacement"
        ),
    ),
    FamilySeed(
        "INFORMATION_NEWS",
        "Information et actualité",
        "CLAIM",
        "OFFICIAL_PUBLICATION_NOT_CONFIGURED",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "NO_VERSIONED_CLAIM_AND_RETRACTION_PIPELINE",
        _pairs(
            "statement:communiqué|press_conference:conférence de presse|"
            "announced_injury:blessure annoncée|announced_lineup:composition annoncée|"
            "declaration:déclaration|transfer:transfert|excluded_player:joueur écarté|"
            "travel_incident:incident de voyage|venue_change:changement de stade|"
            "referee_change:changement d’arbitre|kickoff_change:changement d’horaire|"
            "source:source|reliability:fiabilité|published_at:date de publication|"
            "information_age:âge de l’information au cutoff|retraction:rétractation|"
            "correction:correction"
        ),
    ),
    FamilySeed(
        "MARKET",
        "Marché",
        "MARKET_SNAPSHOT",
        "FOOTBALL_DATA_AND_THE_ODDS_API",
        AvailabilityStatus.PARTIAL,
        "HISTORICAL_PRICES_HAVE_NO_EXACT_INTRADAY_TIMESTAMP",
        _pairs(
            "market_1x2:marché 1X2|asian_handicap:handicap|double_chance:double chance|"
            "goals_total:total de buts|btts:les deux équipes marquent|team_goals:buts équipe|"
            "half_time:mi-temps|correct_score:scores exacts|corners:corners|cards:cartons|"
            "fouls:fautes|shots:tirs|shots_on_target:tirs cadrés|player_props:marchés joueurs|"
            "goalkeeper_saves:arrêts du gardien|odds_decimal:cote décimale|"
            "market_margin:marge de marché|bookmaker_dispersion:dispersion bookmakers|"
            "line_movement:mouvement de ligne|liquidity:liquidité|limits:limites|"
            "settlement_rule:règle de règlement"
        ),
    ),
    FamilySeed(
        "TRAINING_LOAD",
        "Entraînement et charge",
        "TRAINING_SESSION",
        "PRIVATE_CLUB_DATA_NOT_AVAILABLE",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "PRIVATE_HEALTH_AND_TRAINING_DATA_UNAVAILABLE",
        _pairs(
            "microcycle_day:jour du microcycle|external_load:charge externe|"
            "high_intensity_distance:distance à haute intensité|sprints:sprints|"
            "accelerations:accélérations|internal_load:charge interne|rpe:RPE|"
            "heart_rate:fréquence cardiaque|acute_chronic_load:charge aiguë-chronique|"
            "sleep:sommeil|perceived_fatigue:fatigue perçue|soreness:courbatures|"
            "thermal_stress:stress thermique|recovery:récupération"
        ),
    ),
    FamilySeed(
        "MEDICAL",
        "Santé et réathlétisation",
        "MEDICAL_EPISODE",
        "OFFICIAL_INJURY_REPORT_OR_PRIVATE_MEDICAL_DATA",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "POINT_IN_TIME_AND_GOVERNED_MEDICAL_DATA_UNAVAILABLE",
        _pairs(
            "injury_episode:épisode de blessure|injury_mechanism:mécanisme de blessure|"
            "body_area:zone corporelle|severity:gravité|illness_episode:épisode de maladie|"
            "concussion_protocol:protocole commotion|individual_training:"
            "entraînement individuel|partial_training:reprise partielle|"
            "full_training:reprise collective|medical_clearance:autorisation médicale|"
            "minutes_restriction:restriction de minutes|relapse_history:historique de récidive|"
            "privacy_basis:base de gouvernance et consentement"
        ),
    ),
    FamilySeed(
        "EVENT_GAME_STATE",
        "État du match et événements",
        "EVENT",
        "API_FOOTBALL_EVENTS",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "TARGET_MATCH_EVENTS_ARE_POST_CUTOFF",
        _pairs(
            "score_state:état du score|minute:minute|possession_chain:chaîne de possession|"
            "action_sequence:séquence d’actions|numerical_state:état numérique|"
            "time_remaining:temps restant|goal_event:but|card_event:carton|"
            "substitution_event:remplacement|var_event:événement VAR|"
            "formation_spell:période de formation|player_spell:période de joueur"
        ),
    ),
    FamilySeed(
        "ORGANISATION_SQUAD",
        "Organisation et effectif",
        "REGISTRATION",
        "OFFICIAL_REGISTRATION_OR_TRANSFER_SOURCE",
        AvailabilityStatus.DATA_GATE_BLOCKED,
        "POINT_IN_TIME_REGISTRATION_HISTORY_UNAVAILABLE",
        _pairs(
            "registration:inscription|squad_membership:appartenance à l’effectif|"
            "transfer:transfert|loan:prêt|contract_status:statut contractuel|"
            "academy_player:joueur du centre de formation|squad_churn:renouvellement d’effectif|"
            "call_up:convocation en sélection|financial_pressure:pression financière|"
            "contract_incentive:incitation contractuelle"
        ),
    ),
    FamilySeed(
        "DATA_QUALITY",
        "Qualité et provenance",
        "OBSERVATION",
        "ALL_VERSIONED_SOURCES",
        AvailabilityStatus.READY,
        None,
        _pairs(
            "source:source|source_schema_hash:hash du schéma source|observed_at:"
            "instant d’observation|published_at:instant de publication|"
            "provider_updated_at:instant de mise à jour fournisseur|ingested_at:"
            "instant d’ingestion|valid_from:début de validité|valid_to:fin de validité|"
            "missingness:valeur manquante|identity_confidence:confiance d’identité|"
            "coverage_bias:biais de couverture|schema_change:changement de schéma|"
            "provenance_hash:hash de provenance"
        ),
    ),
)


_BOOLEAN_HINTS = {
    "derby",
    "rivalry",
    "knockout",
    "neutral_ground",
    "behind_closed_doors",
    "roof_open",
    "same_day_travel",
    "injured",
    "suspended",
    "ill",
    "doubtful",
}
_IDENTITY_HINTS = {
    "identity",
    "competition",
    "stadium",
    "referee",
    "source",
    "formation",
    "market_1x2",
}
_TIME_HINTS = {
    "arrival_time",
    "published_at",
    "observed_at",
    "provider_updated_at",
    "ingested_at",
    "valid_from",
    "valid_to",
    "local_kickoff_time",
}


def _data_type(identifier: str) -> PropertyDataType:
    if identifier in _BOOLEAN_HINTS or identifier.startswith(("first_", "last_", "recent_")):
        return PropertyDataType.BOOLEAN
    if identifier in _IDENTITY_HINTS or identifier.endswith(("_status", "_type", "_role")):
        return PropertyDataType.ENUM
    if identifier in _TIME_HINTS or identifier.endswith("_at"):
        return PropertyDataType.TIMESTAMP
    if identifier == "coordinates":
        return PropertyDataType.GEO_POINT
    if identifier in {
        "statement",
        "press_conference",
        "declaration",
        "correction",
        "retraction",
    }:
        return PropertyDataType.TEXT_EVIDENCE
    if identifier in {
        "official_xi",
        "bench",
        "available_takers",
        "profiles",
    }:
        return PropertyDataType.CATEGORICAL_SET
    if identifier in {
        "front_three_foot_distribution",
        "finishing_efficiency",
    }:
        return PropertyDataType.DISTRIBUTION
    if identifier in {"wind_direction", "crosswind_component"}:
        return PropertyDataType.VECTOR
    if identifier.endswith(("_episode", "_tenure", "_spell")):
        return PropertyDataType.INTERVAL
    if any(
        token in identifier
        for token in ("rate", "share", "probability", "efficiency", "missingness")
    ):
        return PropertyDataType.RATE
    if any(token in identifier for token in ("sequence", "streak", "events", "chain", "spell")):
        return PropertyDataType.EVENT_SERIES
    if any(token in identifier for token in ("network", "pair", "triangle", "matchup")):
        return PropertyDataType.GRAPH_NODE_REF
    return PropertyDataType.QUANTITY


def _operators(data_type: PropertyDataType) -> tuple[str, ...]:
    if data_type is PropertyDataType.BOOLEAN:
        return ("EQ", "NE")
    if data_type in {
        PropertyDataType.ENUM,
        PropertyDataType.ENTITY_REF,
        PropertyDataType.GRAPH_NODE_REF,
    }:
        return ("EQ", "NE", "IN", "NOT_IN", "COUNT", "GRAPH_PATTERN")
    if data_type is PropertyDataType.EVENT_SERIES:
        return ("COUNT", "RATE", "SEQUENCE", "TREND", "INTERACTION")
    return (
        "EQ",
        "NE",
        "GT",
        "GE",
        "LT",
        "LE",
        "BETWEEN",
        "DIFFERENCE",
        "RATIO",
        "TREND",
        "INTERACTION",
    )


def _role(family: str, identifier: str) -> PropertyRole:
    if family == "DATA_QUALITY":
        return PropertyRole.PROVENANCE
    if identifier in _IDENTITY_HINTS:
        return PropertyRole.IDENTITY
    if family == "EVENT_GAME_STATE" and identifier.endswith("_event"):
        return PropertyRole.TARGET
    return PropertyRole.PREDICTOR


_DATA_QUALITY_FIELDS = frozenset(
    {
        "missing",
        "missingness",
        "value_missing",
        "source_missing",
        "coverage_missing",
        "gate_missing",
        "identity_confidence",
        "coverage_bias",
        "schema_change",
    }
)
_AVAILABILITY_FIELDS = frozenset(
    {
        "observed_at",
        "published_at",
        "provider_updated_at",
        "ingested_at",
        "valid_from",
        "valid_to",
    }
)
_PROVENANCE_FIELDS = frozenset({"source", "source_schema_hash", "provenance_hash"})
_IDENTIFIER_FIELDS = frozenset({"identity", "competition", "stadium", "referee"})
_CONTEXT_FAMILIES = frozenset(
    {
        "MATCH_COMPETITION",
        "STADIUM_PITCH",
        "WEATHER",
        "TRAVEL_LOGISTICS",
        "CALENDAR_FATIGUE",
        "LINEUP_CONTINUITY",
        "ABSENCE_RETURN",
        "DISCIPLINE_REFEREE",
        "FORMATION_STRUCTURE",
        "COACH",
        "INFORMATION_NEWS",
        "TRAINING_LOAD",
        "MEDICAL",
        "ORGANISATION_SQUAD",
    }
)
_RELATION_FAMILIES = frozenset({"CHEMISTRY_NETWORKS"})


def semantic_role_for_property(definition: PropertyDefinition) -> SemanticRole:
    """Return a total, fail-closed semantic classification for a property."""

    identifier = definition.source_field.casefold()
    if definition.family == "DATA_QUALITY":
        if identifier in _DATA_QUALITY_FIELDS or "missing" in identifier:
            return SemanticRole.DATA_QUALITY_METADATA
        if identifier in _AVAILABILITY_FIELDS:
            return SemanticRole.AVAILABILITY_METADATA
        if identifier in _PROVENANCE_FIELDS:
            return SemanticRole.PROVENANCE_METADATA
        return SemanticRole.DATA_QUALITY_METADATA
    if definition.family == "MARKET":
        return SemanticRole.MARKET_PROPERTY
    if definition.family == "EVENT_GAME_STATE":
        return SemanticRole.TARGET
    if identifier in _IDENTIFIER_FIELDS:
        return SemanticRole.IDENTIFIER
    if (
        definition.family in _RELATION_FAMILIES
        or definition.data_type
        in {
            PropertyDataType.GRAPH_NODE_REF,
            PropertyDataType.GRAPH_EDGE_REF,
            PropertyDataType.HYPEREDGE_REF,
        }
    ):
        return SemanticRole.FOOTBALL_RELATION
    if definition.family in _CONTEXT_FAMILIES:
        return SemanticRole.FOOTBALL_CONTEXT
    return SemanticRole.FOOTBALL_PREDICTOR


def build_property_universe() -> tuple[PropertyDefinition, ...]:
    definitions: list[PropertyDefinition] = []
    for seed in FAMILY_SEEDS:
        for identifier, display_fr in seed.properties:
            data_type = _data_type(identifier)
            definition = PropertyDefinition(
                property_id=f"football:{seed.family.casefold()}:{identifier}",
                display_name_fr=display_fr,
                display_name_en=identifier.replace("_", " ").title(),
                description_fr=(
                    f"Propriété football « {display_fr} », versionnée et évaluée "
                    "uniquement avec les informations admissibles au cutoff."
                ),
                family=seed.family,
                subfamily=identifier.split("_", maxsplit=1)[0].upper(),
                tags=(seed.display_fr, seed.family),
                subtags=tuple(identifier.upper().split("_")),
                entity=seed.entity,
                data_type=data_type,
                unit="SOURCE_DEFINED_OR_DIMENSIONLESS",
                source=seed.source,
                source_field=identifier,
                raw_or_derived="RAW_OR_VERSIONED_DERIVED",
                derivation_contract="TRAIN_ONLY_WHEN_LEARNED;AS_OF_CUTOFF",
                availability_time="OBSERVED_AT_OR_DERIVED_AS_OF_CUTOFF",
                valid_cutoffs=("H-24", "H-2", "NEAR_KICKOFF", "POST_LINEUP"),
                temporal_gate="STRICTLY_BEFORE_TARGET_KICKOFF",
                quality_gate=seed.availability.value,
                missingness_policy="MISSING_NOT_ZERO",
                allowed_operators=_operators(data_type),
                allowed_relations=(
                    "APPLIES_TO",
                    "OBSERVED_FOR",
                    "DERIVED_FROM",
                    "INTERACTS_WITH",
                ),
                allowed_targets=(
                    "MATCH_RESULT",
                    "TEAM_GOALS",
                    "GOALS_TOTAL",
                    "EVENT_COUNT",
                    "RESIDUAL_PERFORMANCE",
                    "PLAYER_AVAILABILITY",
                    "NO_MARKET_TARGET",
                ),
                version=PROPERTY_UNIVERSE_VERSION,
                role=_role(seed.family, identifier),
                availability_status=seed.availability,
                blocking_reason=seed.blocking_reason,
                observation_type="RAW_OR_VERSIONED_DERIVED_OBSERVATION",
                physical_dimension="SOURCE_DEFINED_OR_DIMENSIONLESS",
                source_schema_hash=canonical_sha256(
                    {
                        "source": seed.source,
                        "catalogue": PROPERTY_UNIVERSE_ID,
                        "version": PROPERTY_UNIVERSE_VERSION,
                    }
                ),
                event_time_field="event_time_if_applicable",
                published_at_field="published_at_if_applicable",
                provider_updated_at_field="provider_updated_at_if_available",
                observed_at_field="observed_at_required_for_execution",
                ingested_at_field="ingested_at",
                valid_from_field="valid_from_if_applicable",
                valid_to_field="valid_to_if_applicable",
            )
            definitions.append(definition)
    identifiers = [item.property_id for item in definitions]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("FOOTBALL_PROPERTY_ID_COLLISION")
    return tuple(sorted(definitions, key=lambda item: item.property_id))


PROPERTY_UNIVERSE = build_property_universe()
PROPERTY_BY_ID = {item.property_id: item for item in PROPERTY_UNIVERSE}


TRANSFORMATION_CATALOG: tuple[str, ...] = (
    "RAW",
    "SUM",
    "MEAN",
    "MEDIAN",
    "MIN",
    "MAX",
    "VARIANCE",
    "STANDARD_DEVIATION",
    "COEFFICIENT_OF_VARIATION",
    "QUANTILE",
    "PERCENTILE",
    "Z_SCORE",
    "RANK",
    "DIFFERENCE",
    "RATIO",
    "INTERACTION",
    "OPPONENT_DIFFERENCE",
    "OPPONENT_ADJUSTED",
    "ROLLING_MEAN",
    "ROLLING_SUM",
    "TREND",
    "EWMA",
    "ACCELERATION",
    "VOLATILITY",
    "STREAK",
    "REGIME_CHANGE",
    "SEQUENCE",
    "FREQUENCY",
    "PER_90",
    "CONCENTRATION",
    "ENTROPY",
    "TIME_SINCE",
    "EVENTS_SINCE",
    "MISSINGNESS",
)
MATCH_WINDOWS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20)
DAY_WINDOWS: tuple[int, ...] = (5, 7, 10, 14, 21, 30, 60, 90)


RELATION_CATALOG: tuple[str, ...] = (
    "PLAYS_FOR",
    "FACES",
    "STARTS",
    "REPLACES",
    "ABSENT_FROM",
    "SUSPENDED_FROM",
    "UNDER_SUSPENSION_THREAT",
    "OFFICIATES",
    "TAKES_PLACE_AT",
    "TRAVELS_TO",
    "PLAYS_WITH",
    "DEFENDS_AGAINST",
    "DIRECTLY_OPPOSES",
    "OCCUPIES_ZONE",
    "ADJACENT_TO",
    "HAS_PRICE",
    "OBSERVED_AT",
    "REGISTERED_FOR",
    "SELECTED_IN",
    "ON_BENCH_FOR",
    "ASSIGNED_ROLE",
    "CHANGES_ROLE_TO",
    "PLAYS_OUT_OF_POSITION",
    "PASSES_TO",
    "COMBINES_WITH",
    "COVERS",
    "MARKS",
    "PRESSES",
    "OVERLAPS",
    "UNDERLAPS",
    "ROTATES_WITH",
    "TAKES_SET_PIECE",
    "COACH_SELECTS",
    "MEDICALLY_CLEARED_FOR",
    "TRAVELS_ON",
    "ARRIVES_AT",
    "FORECASTS_WEATHER_FOR",
    "OBSERVES_WEATHER_AT",
    "QUOTES",
    "SUPERSEDES",
    "DERIVED_FROM",
    "PUBLISHED_BY",
    "CONFOUNDS",
    "MEDIATES",
)


SOURCE_FIELD_INVENTORY: tuple[dict[str, str], ...] = (
    *(
        {
            "source": "ROBIN_DEEP_FOOTBALL",
            "source_field": field,
            "classification": "PROPERTY",
            "property_id": property_id,
            "reason": "VERSIONED_DERIVED_FEATURE",
        }
        for field, property_id in (
            ("elo_difference", "football:strength_form:elo"),
            ("home_form_5", "football:strength_form:form"),
            ("away_form_5", "football:strength_form:form"),
            ("home_form_10", "football:strength_form:form"),
            ("away_form_10", "football:strength_form:form"),
            ("home_goals_for_5", "football:attack:goals_scored"),
            ("away_goals_for_5", "football:attack:goals_scored"),
            ("home_goals_against_5", "football:defence:goals_conceded"),
            ("away_goals_against_5", "football:defence:goals_conceded"),
            ("home_rest_days", "football:calendar_fatigue:rest_days"),
            ("away_rest_days", "football:calendar_fatigue:rest_days"),
        )
    ),
    *(
        {
            "source": "FOOTBALL_DATA",
            "source_field": field,
            "classification": "PROPERTY",
            "property_id": property_id,
            "reason": "HISTORICAL_SOURCE_FIELD_CLASSIFIED",
        }
        for field, property_id in (
            ("Div", "football:match_competition:competition"),
            ("Date", "football:data_quality:published_at"),
            ("Time", "football:match_competition:local_kickoff_time"),
            ("HomeTeam", "football:match_competition:venue_role"),
            ("AwayTeam", "football:match_competition:venue_role"),
            ("FTHG", "football:attack:goals_scored"),
            ("FTAG", "football:attack:goals_scored"),
            ("FTR", "football:event_game_state:score_state"),
            ("HS", "football:attack:shots"),
            ("AS", "football:attack:shots"),
            ("HST", "football:attack:shots_on_target"),
            ("AST", "football:attack:shots_on_target"),
            ("HF", "football:discipline_referee:fouls"),
            ("AF", "football:discipline_referee:fouls"),
            ("HC", "football:set_pieces:corners_for"),
            ("AC", "football:set_pieces:corners_for"),
            ("HY", "football:discipline_referee:yellow_cards"),
            ("AY", "football:discipline_referee:yellow_cards"),
            ("HR", "football:discipline_referee:red_cards"),
            ("AR", "football:discipline_referee:red_cards"),
            ("B365H", "football:market:odds_decimal"),
            ("B365D", "football:market:odds_decimal"),
            ("B365A", "football:market:odds_decimal"),
            ("B365>2.5", "football:market:odds_decimal"),
            ("B365<2.5", "football:market:odds_decimal"),
        )
    ),
    *(
        {
            "source": "API_FOOTBALL",
            "source_field": field,
            "classification": "PROPERTY",
            "property_id": property_id,
            "reason": reason,
        }
        for field, property_id, reason in (
            (
                "fixture.id",
                "football:data_quality:provenance_hash",
                "PROVIDER_IDENTITY_FIELD",
            ),
            (
                "fixture.date",
                "football:match_competition:local_kickoff_time",
                "FIXTURE_PUBLICATION_FIELD",
            ),
            (
                "fixture.venue.id",
                "football:stadium_pitch:stadium",
                "VENUE_FIELD_COVERAGE_PARTIAL",
            ),
            (
                "league.id",
                "football:match_competition:competition",
                "CANONICAL_PROVIDER_COMPETITION_ID",
            ),
            (
                "league.season",
                "football:match_competition:season",
                "FIXTURE_PUBLICATION_FIELD",
            ),
            (
                "league.round",
                "football:match_competition:round",
                "FIXTURE_PUBLICATION_FIELD",
            ),
            (
                "teams.home.id",
                "football:match_competition:venue_role",
                "TEAM_IDENTITY_FIELD",
            ),
            (
                "teams.away.id",
                "football:match_competition:venue_role",
                "TEAM_IDENTITY_FIELD",
            ),
            (
                "lineups.formation",
                "football:formation_structure:formation",
                "BLOCKED_BY_TEMPORALITY",
            ),
            (
                "lineups.startXI.player.id",
                "football:lineup_continuity:official_xi",
                "BLOCKED_BY_TEMPORALITY",
            ),
            (
                "players.statistics.games.position",
                "football:player:position",
                "BLOCKED_BY_TEMPORALITY",
            ),
            (
                "injuries.player.id",
                "football:absence_return:injured",
                "BLOCKED_BY_TEMPORALITY",
            ),
        )
    ),
)


def source_field_audit() -> dict[str, object]:
    unclassified = [
        item for item in SOURCE_FIELD_INVENTORY if item["property_id"] not in PROPERTY_BY_ID
    ]
    classified = len(SOURCE_FIELD_INVENTORY) - len(unclassified)
    return {
        "schema_version": "football-source-field-audit-v1",
        "inventory_scope": (
            "VERSIONED_FIELDS_EXPLICITLY_CONSUMED_BY_ROBIN_V1_AND_V2; "
            "OPAQUE_RAW_PROVIDER_PAYLOADS_ARE_NOT_CLAIMED_COMPLETE"
        ),
        "inventory_hash": canonical_sha256(SOURCE_FIELD_INVENTORY),
        "source_fields": len(SOURCE_FIELD_INVENTORY),
        "classified_source_fields": classified,
        "blocked_source_fields": sum(
            "BLOCKED" in item["reason"] for item in SOURCE_FIELD_INVENTORY
        ),
        "unclassified_source_fields": len(unclassified),
        "unclassified": unclassified,
        "items": list(SOURCE_FIELD_INVENTORY),
    }


def property_universe_hash() -> str:
    return canonical_sha256(
        [
            {
                **asdict(item),
                "data_type": item.data_type.value,
                "role": item.role.value,
                "availability_status": item.availability_status.value,
                "property_hash": item.property_hash,
            }
            for item in PROPERTY_UNIVERSE
        ]
    )


__all__ = [
    "AvailabilityStatus",
    "DAY_WINDOWS",
    "FAMILY_SEEDS",
    "MATCH_WINDOWS",
    "PROPERTY_BY_ID",
    "PROPERTY_UNIVERSE",
    "PROPERTY_UNIVERSE_ID",
    "PROPERTY_UNIVERSE_VERSION",
    "PUBLIC_HYPOTHESIS_SEMANTIC_ROLES",
    "PropertyDataType",
    "PropertyDefinition",
    "PropertyRole",
    "RELATION_CATALOG",
    "SOURCE_FIELD_INVENTORY",
    "SemanticRole",
    "TRANSFORMATION_CATALOG",
    "build_property_universe",
    "property_universe_hash",
    "semantic_role_for_property",
    "source_field_audit",
]
