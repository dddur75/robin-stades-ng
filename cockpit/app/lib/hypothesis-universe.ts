import rawUniverse from "../hypothesis-universe-data.json";

import type { HypothesisIntelligencePresentation } from "./presentation-model";

export type AvailabilityStatus = "READY" | "PARTIAL" | "DATA_GATE_BLOCKED";

export type HypothesisFamily = {
  availability_status: AvailabilityStatus;
  blocking_reason: string | null;
  display_name_fr: string;
  entities: string[];
  family: string;
  property_count: number;
};

export type HypothesisSummary = {
  campaign_hash: string;
  compute_deferred_candidates: number;
  data_gate_blocked_candidates: number;
  data_hash: string;
  executed_candidates: number;
  long_tail_candidates: number;
  materialized_candidates: number;
  ontology_hash: string;
  properties: number;
  property_families: number;
  prospectively_frozen_candidates: number;
  pruned_candidates: number;
  relations: number;
  schema_version: string;
  symbolic_templates: number;
  transformations: number;
  universe_id: string;
  verdict: string;
};

export type HypothesisTreeNode = {
  children_count: number;
  data_gates: string[];
  display_rule_fr: string;
  family: string;
  historical_metrics: Record<string, unknown> | null;
  materialization_disposition: string;
  node_id: string;
  parent_id: string | null;
  parent_ids: string[];
  payload_hash: string;
  prospective_metrics: Record<string, unknown> | null;
  rankings: Record<string, unknown> | null;
  status: string;
  subfamily: string;
  support: number | null;
  tags: string[];
  technical_rule: Record<string, unknown>;
};

export type RankingEntry = {
  competition?: string;
  family: string;
  historical_roi?: number;
  historical_support?: number;
  hypothesis_id: string;
  label_fr: string;
  q_value?: number;
  rank: number;
  status: string;
};

export type FamilyNodeStats = {
  blocked: number;
  deferred: number;
  executed: number;
  longTail: number;
  materialized: number;
  pruned: number;
};

export type HypothesisTagDefinition = {
  tag_id: string;
  label_fr: string;
  description_fr: string;
  family: string | null;
  parent_tag: string | null;
  icon: string;
  semantic_role:
    | "FAMILY"
    | "SUBFAMILY"
    | "SUBJECT"
    | "PROPERTY"
    | "VALUE"
    | "STATUS"
    | "ORIGIN"
    | "MARKET"
    | "CUTOFF";
};

export type ProspectiveFreezeContract = {
  contract_hash: string;
  contract_id: string;
  contract_version: string;
  eligibility_contract: string;
  frozen_at: string;
  generator_hash: string;
  hypothesis_id: string;
  hypothesis_version: string;
  price_contract_hash: string;
  primary_price: {
    cutoff_name: string;
    maximum_margin: number;
    maximum_odds: number;
    minimum_odds: number;
    selection: string;
  };
  promotion_locked: boolean;
  registry_hash: string;
  rule_hash: string;
  secondary_price: {
    cutoff_name: string;
    maximum_margin: number;
    maximum_odds: number;
    minimum_odds: number;
    selection: string;
  };
  source_code_revision: string;
  source_tree_hash: string;
};

type UniverseContracts = {
  "campaign-catalog": {
    campaigns: unknown[];
    schema_version: string;
  };
  "competition-identity-catalog": {
    items: Array<{
      canonical_competition_key: string;
      display_name_fr: string;
      historical_aliases: string[];
      provider_competition_id: string;
    }>;
    schema_version: string;
  };
  "hypothesis-facets": {
    campaigns: number;
    cutoffs: string[];
    families: Record<string, number>;
    markets: string[];
    origins: Record<string, string>;
    schema_version: string;
    sources: string[];
    statuses: Record<string, number>;
    tree_depths: number[];
  };
  "hypothesis-family-catalog": {
    catalog_hash: string;
    items: HypothesisFamily[];
    schema_version: string;
  };
  "hypothesis-family-tree-index": {
    families: Record<
      string,
      {
        label_fr: string;
        root_node_ids: string[];
      }
    >;
    schema_version: string;
  };
  "hypothesis-global-rankings": {
    longue_traine_a_surveiller: HypothesisTreeNode[];
    meilleures_observations_prospectives: RankingEntry[];
    meilleures_priorites_exploratoires: RankingEntry[];
    meilleurs_signaux_historiques_bruts: RankingEntry[];
    schema_version: string;
    strategies_validees: RankingEntry[];
    warning_fr: string;
  };
  "hypothesis-glossary-fr": Record<string, string>;
  "hypothesis-live-activity": {
    hypothesis_observations: number;
    last_activity: string | null;
    prospective_settlements: number;
    real_bets: number;
    real_predictions: number;
    real_training_runs: number;
    schema_version: string;
  };
  "hypothesis-rankings-by-competition": {
    competitions: Record<
      string,
      {
        meilleurs_signaux_historiques_bruts: RankingEntry[];
        strategies_validees: RankingEntry[];
      }
    >;
    schema_version: string;
  };
  "hypothesis-rankings-by-family": {
    families: Record<
      string,
      {
        label_fr: string;
        meilleurs_signaux_historiques_bruts: RankingEntry[];
        strategies_validees: RankingEntry[];
      }
    >;
    schema_version: string;
  };
  "hypothesis-status-funnel": {
    counts: Record<string, number>;
    schema_version: string;
    scientific_rejections: number;
    validated_strategies: number;
  };
  "hypothesis-tags-catalog": {
    families: Array<{ id: string; label_fr: string }>;
    origins: Record<string, string>;
    public_language: string;
    schema_version: string;
    subfamilies: string[];
  };
  "hypothesis-tree-root-index": {
    detail_pages_storage: string;
    node_count: number;
    page_size: number;
    replay_hash: string;
    roots: HypothesisTreeNode[];
    schema_version: string;
    tree_id: string;
  };
  "hypothesis-universe-summary": HypothesisSummary;
  "manifest": Record<string, unknown>;
  "prospective-freeze-provenance-v2": {
    contracts: ProspectiveFreezeContract[];
    frozen_at: string;
    generator_hash: string;
    registry_hash: string;
    schema_version: string;
    source_code_revision: string;
    source_tree_hash: string;
    status: string;
  };
  "security-locks": {
    DEMO_MODE_ENABLED: boolean;
    NO_BET_DEFAULT: boolean;
    P3_P4_PAUSED: boolean;
    PRODUCTION_LOCKED: boolean;
    PROMOTION_LOCKED: boolean;
    REAL_BETS: boolean;
    SOCIAL_PUBLISHING_ENABLED: boolean;
    STORAGE_PAUSED: boolean;
    odds_api_credits: number;
    paid_weather_calls: number;
    provider_calls: number;
  };
};

type UniverseData = {
  contracts: UniverseContracts;
  derivedTreeIndex: {
    childrenByParent: Record<string, string[]>;
    familyNodeStats: Record<string, FamilyNodeStats>;
    nodeLocator: Record<string, number>;
  };
  generatedNodePages: Array<{
    bytes: number;
    page: number;
    records: number;
    sha256: string | null;
    sourceSha256: string | null;
    source: "artifact" | "root-index-fallback";
    url: string;
  }>;
  presentation: {
    hypothesisIntelligence: HypothesisIntelligencePresentation;
    sourceContracts: string[];
  };
  schemaVersion: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function assertUniverseData(value: unknown): asserts value is UniverseData {
  if (!isRecord(value) || !isRecord(value.contracts)) {
    throw new Error("HYPOTHESIS_UNIVERSE_CONTRACTS_MISSING");
  }

  const requiredContracts: Array<keyof UniverseContracts> = [
    "campaign-catalog",
    "competition-identity-catalog",
    "hypothesis-facets",
    "hypothesis-family-catalog",
    "hypothesis-family-tree-index",
    "hypothesis-global-rankings",
    "hypothesis-glossary-fr",
    "hypothesis-live-activity",
    "hypothesis-rankings-by-competition",
    "hypothesis-rankings-by-family",
    "hypothesis-status-funnel",
    "hypothesis-tags-catalog",
    "hypothesis-tree-root-index",
    "hypothesis-universe-summary",
    "manifest",
    "prospective-freeze-provenance-v2",
    "security-locks",
  ];
  for (const contractName of requiredContracts) {
    if (!isRecord(value.contracts[contractName])) {
      throw new Error(`HYPOTHESIS_CONTRACT_INVALID:${contractName}`);
    }
  }

  const familyCatalog = value.contracts["hypothesis-family-catalog"];
  const treeIndex = value.contracts["hypothesis-tree-root-index"];
  const security = value.contracts["security-locks"];
  if (
    !isRecord(familyCatalog) ||
    !isRecord(treeIndex) ||
    !isRecord(security) ||
    !Array.isArray(familyCatalog.items) ||
    !Array.isArray(treeIndex.roots) ||
    typeof treeIndex.node_count !== "number" ||
    !Array.isArray(value.generatedNodePages) ||
    !isRecord(value.derivedTreeIndex)
  ) {
    throw new Error("HYPOTHESIS_UNIVERSE_SHAPE_INVALID");
  }
  const booleanLocks = [
    "DEMO_MODE_ENABLED",
    "NO_BET_DEFAULT",
    "P3_P4_PAUSED",
    "PRODUCTION_LOCKED",
    "PROMOTION_LOCKED",
    "REAL_BETS",
    "SOCIAL_PUBLISHING_ENABLED",
    "STORAGE_PAUSED",
  ];
  if (booleanLocks.some((lock) => typeof security[lock] !== "boolean")) {
    throw new Error("HYPOTHESIS_SECURITY_LOCKS_INVALID");
  }
}

const candidateUniverse: unknown = rawUniverse;
assertUniverseData(candidateUniverse);
const data = candidateUniverse;

export const hypothesisContracts = data.contracts;
export const hypothesisSummary =
  data.contracts["hypothesis-universe-summary"];
export const hypothesisFamilies =
  data.contracts["hypothesis-family-catalog"].items;
export const hypothesisTags = data.contracts["hypothesis-tags-catalog"];
export const hypothesisFacets = data.contracts["hypothesis-facets"];
export const hypothesisGlossary =
  data.contracts["hypothesis-glossary-fr"];
export const hypothesisTree =
  data.contracts["hypothesis-tree-root-index"];
export const hypothesisFamilyTrees =
  data.contracts["hypothesis-family-tree-index"].families;
export const hypothesisRankings =
  data.contracts["hypothesis-global-rankings"];
export const hypothesisRankingsByCompetition =
  data.contracts["hypothesis-rankings-by-competition"].competitions;
export const hypothesisRankingsByFamily =
  data.contracts["hypothesis-rankings-by-family"].families;
export const hypothesisFunnel =
  data.contracts["hypothesis-status-funnel"];
export const hypothesisActivity =
  data.contracts["hypothesis-live-activity"];
export const hypothesisSecurity = data.contracts["security-locks"];
export const hypothesisProspectiveFreeze =
  data.contracts["prospective-freeze-provenance-v2"];
export const hypothesisIntelligence =
  data.presentation.hypothesisIntelligence;
export const hypothesisNodePages = data.generatedNodePages;
export const hypothesisNodeLocator = data.derivedTreeIndex.nodeLocator;
export const hypothesisChildrenByParent =
  data.derivedTreeIndex.childrenByParent;
export const hypothesisFamilyNodeStats =
  data.derivedTreeIndex.familyNodeStats;

export const generatedHypothesisRules = Object.values(
  hypothesisFunnel.counts,
).reduce((sum, count) => sum + count, 0);

export const hypothesisCompetitions =
  data.contracts["competition-identity-catalog"].items;

const familyCopy: Partial<Record<string, string>> = {
  ABSENCE_RETURN:
    "Robin distingue les absences réellement connues avant le match des informations publiées trop tard.",
  CALENDAR_FATIGUE:
    "Robin mesure le repos, l’enchaînement des rencontres et les contraintes de calendrier connues avant le coup d’envoi.",
  DATA_QUALITY:
    "Robin contrôle la fraîcheur, la provenance et les valeurs manquantes avant d’autoriser un calcul.",
  FORMATION_STRUCTURE:
    "Robin compare les structures tactiques des deux équipes, leur usage habituel et les joueurs réellement disponibles.",
  GOALKEEPER:
    "Robin étudie le rôle du gardien, sa disponibilité et la continuité au poste sans déduire une absence non prouvée.",
  MARKET:
    "Robin observe les prix et la marge du marché à des heures limites précises, sans transformer un signal en conseil de mise.",
  WEATHER:
    "Robin relie les conditions météo connues à l’heure limite aux propriétés du jeu, sans inventer une observation manquante.",
};

const familyIcons: Partial<Record<string, string>> = {
  ABSENCE_RETURN: "✚",
  ATTACK: "↗",
  CALENDAR_FATIGUE: "◷",
  DATA_QUALITY: "✓",
  DEFENCE: "⌂",
  DISCIPLINE_REFEREE: "▯",
  FOOTEDNESS_LATERALITY: "↔",
  FORMATION_STRUCTURE: "◇",
  GOALKEEPER: "▣",
  INFORMATION_NEWS: "i",
  MARKET: "≈",
  MATCH_COMPETITION: "●",
  PLAYER: "♙",
  POSSESSION_PRESSING: "⟳",
  STADIUM_PITCH: "▤",
  TRAVEL_LOGISTICS: "→",
  WEATHER: "☁",
};

const blockingReasonCopy: Record<string, string> = {
  ABSENCE_PUBLICATION_TIME_NOT_PROVEN:
    "L’heure de publication des absences n’est pas prouvée de façon suffisante.",
  FORMATION_OBSERVATION_NOT_POINT_IN_TIME:
    "Les formations historiques disponibles ne prouvent pas encore ce qui était connu avant le match.",
  HISTORICAL_LINEUPS_OBSERVED_POST_MATCH:
    "Les compositions historiques sont observées après la rencontre et ne peuvent pas être utilisées rétroactivement.",
  NO_FREE_LICENSED_POINT_IN_TIME_WEATHER_ARCHIVE:
    "Aucune archive météo libre et licenciée ne prouve encore l’information disponible à l’heure limite.",
  NO_VERSIONED_HISTORICAL_PITCH_SOURCE:
    "Aucune source historique versionnée du terrain n’est actuellement admissible.",
  SOURCED_FOOTEDNESS_COVERAGE_ZERO:
    "La latéralité des joueurs n’est pas encore couverte par une source admissible.",
};

const subfamilyCopy: Record<string, string> = {
  CONSECUTIVE: "Déplacements consécutifs",
  CROSSWIND: "Vent traversier",
  ELO: "Force relative des équipes",
  FORM: "Forme récente",
  FORMATION: "Structures tactiques",
  GOALS: "Buts marqués ou concédés",
  MARKET: "Prix et marge du marché",
  MISSINGNESS: "Données manquantes",
  PREFERRED: "Préférence latérale",
  REST: "Temps de repos",
  SUSPENSION: "Risque de suspension",
};

const propertyCopy: Record<string, string> = {
  "football:attack:goals_scored": "Buts marqués",
  "football:calendar_fatigue:rest_days": "Jours de repos",
  "football:data_quality:missingness": "Données manquantes",
  "football:defence:goals_conceded": "Buts concédés",
  "football:discipline_referee:suspension_threat":
    "Menace de suspension",
  "football:formation_structure:formation": "Formation tactique",
  "football:market:market_margin": "Marge du marché",
  "football:player:preferred_foot": "Pied préféré",
  "football:strength_form:elo": "Force relative",
  "football:strength_form:form": "Forme récente",
  "football:travel_logistics:consecutive_away_matches":
    "Déplacements consécutifs",
  "football:weather:crosswind_component": "Vent traversier",
};

export function familySlug(familyId: string) {
  return familyId.toLocaleLowerCase("fr-FR").replaceAll("_", "-");
}

export function familyIdFromSlug(slug: string) {
  return slug.toLocaleUpperCase("fr-FR").replaceAll("-", "_");
}

export function findFamily(value: string) {
  const familyId = hypothesisFamilies.some((family) => family.family === value)
    ? value
    : familyIdFromSlug(value);
  return hypothesisFamilies.find((family) => family.family === familyId);
}

export function familyDescription(family: HypothesisFamily) {
  return (
    familyCopy[family.family] ??
    `Robin organise les variables liées à ${family.display_name_fr.toLocaleLowerCase("fr-FR")} et vérifie leur disponibilité temporelle avant tout test.`
  );
}

export function familyIcon(familyId: string) {
  return familyIcons[familyId] ?? "○";
}

export function familyDisplayName(familyId: string) {
  return (
    hypothesisFamilies.find((family) => family.family === familyId)
      ?.display_name_fr ?? "Famille non documentée"
  );
}

export function subfamilyDisplayName(subfamilyId: string) {
  return subfamilyCopy[subfamilyId] ?? "Sous-famille non documentée";
}

export function propertyDisplayName(propertyId: string) {
  return propertyCopy[propertyId] ?? "Condition documentée dans la règle";
}

export function familyBlockingReason(family: HypothesisFamily) {
  if (!family.blocking_reason) {
    return "Les données nécessaires sont disponibles dans le périmètre actuel.";
  }
  return (
    blockingReasonCopy[family.blocking_reason] ??
    "Cette famille existe dans l’univers, mais les données nécessaires ne sont pas encore disponibles avec une preuve temporelle suffisante."
  );
}

export function familyStats(familyId: string): FamilyNodeStats {
  const stats = hypothesisFamilyNodeStats[familyId];
  if (!stats) {
    throw new Error(`HYPOTHESIS_FAMILY_STATS_MISSING:${familyId}`);
  }
  return stats;
}

export function familyRootNodes(familyId: string) {
  const rootIds = new Set(
    hypothesisFamilyTrees[familyId]?.root_node_ids ?? [],
  );
  return hypothesisTree.roots.filter((node) => rootIds.has(node.node_id));
}

export function scientificStatusLabel(status: string) {
  const labels: Record<string, string> = {
    COMPUTE_DEFERRED: "Calcul différé",
    DATA_GATE_BLOCKED: "Bloquée par les données",
    EXECUTED: "Testée dans le pilote",
    EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING:
      "Exploratoire, non validée après correction",
    LONG_TAIL_WATCHLIST: "Longue traîne",
    NON_VALIDÉ_APRÈS_CORRECTION: "Non validée après correction",
    NOT_TESTED: "Non testée",
    PARTIAL: "Données partielles",
    PROSPECTIVE_FROZEN: "En observation prospective",
    PRODUCTION_LOCKED: "Production verrouillée",
    PROMOTION_LOCKED: "Promotion verrouillée",
    PRUNED: "Branche élaguée",
    READY: "Données disponibles",
    VALIDATED: "Validée",
  };
  return labels[status] ?? status.replaceAll("_", " ").toLocaleLowerCase("fr-FR");
}

export function hypothesisById(hypothesisId: string) {
  const machine = hypothesisIntelligence.machineDiscoveries.find(
    (hypothesis) => hypothesis.id === hypothesisId,
  );
  if (machine) return { kind: "machine" as const, hypothesis: machine };
  const owner = hypothesisIntelligence.ownerHypotheses.find(
    (hypothesis) => hypothesis.id === hypothesisId,
  );
  if (owner) return { kind: "owner" as const, hypothesis: owner };
  return null;
}

export function prospectiveContractByHypothesisId(hypothesisId: string) {
  return hypothesisProspectiveFreeze.contracts.find(
    (contract) => contract.hypothesis_id === hypothesisId,
  );
}

export function competitionRankings(competition: string) {
  const direct = hypothesisRankingsByCompetition[competition];
  if (direct) return direct;
  const alias = hypothesisCompetitions.find(
    (item) => item.display_name_fr === competition,
  );
  if (!alias) {
    return {
      meilleurs_signaux_historiques_bruts: [],
      strategies_validees: [],
    };
  }
  return (
    alias.historical_aliases
      .map((candidate) => hypothesisRankingsByCompetition[candidate])
      .find(Boolean) ?? {
      meilleurs_signaux_historiques_bruts: [],
      strategies_validees: [],
    }
  );
}

export function compactNodeId(nodeId: string) {
  return nodeId.replace("hypothesis-node-", "").slice(0, 10);
}

export function cutoffDisplayName(cutoff: string) {
  const labels: Record<string, string> = {
    "H-24": "24 h avant le coup d’envoi",
    "H-2": "2 h avant le coup d’envoi",
    NEAR_KICKOFF: "Proche du coup d’envoi",
    POST_LINEUP: "Après publication des compositions",
  };
  return labels[cutoff] ?? "Heure limite documentée dans le contrat";
}

export function marketDisplayName(market: string) {
  const labels: Record<string, string> = {
    "1X2": "Résultat du match",
    CARDS_IF_PRICED: "Cartons si un prix est disponible",
    GOALS_TOTAL: "Nombre total de buts",
    NO_MARKET_REQUIRED: "Aucun marché requis",
    OPTIONAL_MARKET: "Marché facultatif",
    OVER_UNDER_2_5: "Plus ou moins de 2,5 buts",
    PLAYER_PROPS_IF_PRICED: "Performance joueur si un prix est disponible",
  };
  return labels[market] ?? "Marché documenté dans le contrat";
}

const rootFamiliesBySubfamily = new Map<string, Set<string>>();
for (const root of hypothesisTree.roots) {
  const families =
    rootFamiliesBySubfamily.get(root.subfamily) ?? new Set<string>();
  families.add(root.family);
  rootFamiliesBySubfamily.set(root.subfamily, families);
}

type RootPredicate = {
  binding?: unknown;
  property_id?: unknown;
  value?: unknown;
};

function publicTechnicalValue(value: unknown) {
  if (typeof value === "boolean") return value ? "Oui" : "Non";
  if (typeof value === "number") {
    return new Intl.NumberFormat("fr-FR", {
      maximumFractionDigits: 2,
    }).format(value);
  }
  if (typeof value === "string") {
    return value
      .replaceAll("_", " ")
      .toLocaleLowerCase("fr-FR")
      .replace(/^./, (letter) => letter.toLocaleUpperCase("fr-FR"));
  }
  return "Valeur contractuelle";
}

function tagValueId(value: unknown) {
  return encodeURIComponent(JSON.stringify(value));
}

const familyTags: HypothesisTagDefinition[] = hypothesisTags.families.map(
  (family) => ({
    tag_id: `family:${family.id}`,
    label_fr: family.label_fr,
    description_fr:
      findFamily(family.id) == null
        ? "Famille déclarée dans le catalogue contractuel."
        : familyDescription(findFamily(family.id)!),
    family: family.id,
    parent_tag: null,
    icon: familyIcon(family.id),
    semantic_role: "FAMILY",
  }),
);
const subfamilyTags: HypothesisTagDefinition[] =
  hypothesisTags.subfamilies.map((subfamily, index) => {
    const families = Array.from(
      rootFamiliesBySubfamily.get(subfamily) ?? [],
    );
    const family = families.length === 1 ? families[0] : null;
    return {
      tag_id: `subfamily:${subfamily}`,
      label_fr:
        subfamilyCopy[subfamily] ?? `Axe contractuel ${index + 1}`,
      description_fr:
        "Sous-famille déclarée par le registre. Sa présence ne prouve ni disponibilité ni résultat.",
      family,
      parent_tag: family == null ? null : `family:${family}`,
      icon: "◇",
      semantic_role: "SUBFAMILY",
    };
  });
const hierarchicalRuleTags: HypothesisTagDefinition[] =
  hypothesisTree.roots.flatMap((root) => {
    const rule = root.technical_rule as {
      entity_scope?: unknown;
      predicates?: unknown;
    };
    const subject =
      typeof rule.entity_scope === "string"
        ? rule.entity_scope
        : "FOOTBALL_CONTEXT";
    const subjectId = `subject:${root.node_id}:${subject}`;
    const tags: HypothesisTagDefinition[] = [
      {
        tag_id: subjectId,
        label_fr: publicTechnicalValue(subject),
        description_fr: "Sujet visé par la règle contractuelle.",
        family: root.family,
        parent_tag: `subfamily:${root.subfamily}`,
        icon: "◎",
        semantic_role: "SUBJECT",
      },
    ];
    const predicates = Array.isArray(rule.predicates)
      ? (rule.predicates as RootPredicate[])
      : [];
    let statusParent = subjectId;
    for (const predicate of predicates) {
      if (typeof predicate.property_id !== "string") continue;
      const propertyId =
        `property:${root.node_id}:${predicate.property_id}`;
      const valueId =
        `value:${root.node_id}:${predicate.property_id}:${tagValueId(predicate.value)}`;
      statusParent = valueId;
      tags.push(
        {
          tag_id: propertyId,
          label_fr: propertyDisplayName(predicate.property_id),
          description_fr: "Propriété football du contrat.",
          family: root.family,
          parent_tag: subjectId,
          icon: "◇",
          semantic_role: "PROPERTY",
        },
        {
          tag_id: valueId,
          label_fr: publicTechnicalValue(predicate.value),
          description_fr: "Valeur comparée, sans résultat implicite.",
          family: root.family,
          parent_tag: propertyId,
          icon: "◆",
          semantic_role: "VALUE",
        },
      );
    }
    tags.push({
      tag_id: `node-status:${root.node_id}:${root.materialization_disposition}`,
      label_fr: scientificStatusLabel(root.materialization_disposition),
      description_fr: "État matériel publié par le contrat.",
      family: root.family,
      parent_tag: statusParent,
      icon: "●",
      semantic_role: "STATUS",
    });
    return tags;
  });
const originTags: HypothesisTagDefinition[] = Object.entries(
  hypothesisTags.origins,
).map(([origin, label]) => ({
  tag_id: `origin:${origin}`,
  label_fr: label,
  description_fr: "Origine déclarée de l’idée de recherche.",
  family: null,
  parent_tag: null,
  icon: "◎",
  semantic_role: "ORIGIN",
}));
const cutoffTags: HypothesisTagDefinition[] = hypothesisFacets.cutoffs.map(
  (cutoff) => ({
    tag_id: `cutoff:${cutoff}`,
    label_fr: cutoffDisplayName(cutoff),
    description_fr:
      "Moment au-delà duquel une information n’est plus admissible avant la rencontre.",
    family: null,
    parent_tag: null,
    icon: "◷",
    semantic_role: "CUTOFF",
  }),
);
const marketTags: HypothesisTagDefinition[] = hypothesisFacets.markets.map(
  (market) => ({
    tag_id: `market:${market}`,
    label_fr: marketDisplayName(market),
    description_fr: "Marché déclaré par le contrat scientifique.",
    family: "MARKET",
    parent_tag: "family:MARKET",
    icon: "◇",
    semantic_role: "MARKET",
  }),
);
const documentedStatuses = new Set<string>([
  ...Object.keys(hypothesisFacets.statuses),
  ...hypothesisTree.roots.flatMap((root) => [
    root.status,
    root.materialization_disposition,
    ...root.data_gates,
  ]),
  ...hypothesisRankings.meilleurs_signaux_historiques_bruts.map(
    (entry) => entry.status,
  ),
  ...hypothesisRankings.meilleures_priorites_exploratoires.map(
    (entry) => entry.status,
  ),
  ...hypothesisRankings.meilleures_observations_prospectives.map(
    (entry) => entry.status,
  ),
  ...hypothesisRankings.strategies_validees.map((entry) => entry.status),
  ...hypothesisIntelligence.machineDiscoveries.flatMap((entry) => [
    entry.status,
    entry.prospectiveStatus,
  ]),
  ...hypothesisIntelligence.ownerHypotheses.map((entry) => entry.status),
  "VALIDATED",
]);
const statusTags: HypothesisTagDefinition[] = [...documentedStatuses].map(
  (status) => ({
  tag_id: `status:${status}`,
  label_fr: scientificStatusLabel(status),
  description_fr:
    "État scientifique publié par le contrat, distinct d’une promesse de performance.",
  family: null,
  parent_tag: null,
  icon: "●",
  semantic_role: "STATUS",
  }),
);

export const hypothesisTagCatalog: HypothesisTagDefinition[] = [
  ...familyTags,
  ...subfamilyTags,
  ...hierarchicalRuleTags,
  ...originTags,
  ...cutoffTags,
  ...marketTags,
  ...statusTags,
];

const hypothesisTagsById = new Map(
  hypothesisTagCatalog.map((tag) => [tag.tag_id, tag]),
);

export function hypothesisTag(tagId: string) {
  return hypothesisTagsById.get(tagId);
}
