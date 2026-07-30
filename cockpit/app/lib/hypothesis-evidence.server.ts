import rawArtifactHashes from "../../../reports/hypothesis-evidence/artifact-hashes.json";
import rawReconciliation from "../../../reports/hypothesis-evidence/reconciliation.json";
import rawSourceProvenance from "../../../reports/hypothesis-evidence/source-provenance.json";
import rawTopTen from "../../../reports/hypothesis-evidence/top-10.json";

import type {
  PresentationProvenance,
  RankingEntryContract,
  RankingPageContract,
  RankingScope,
} from "./contracts/experience-v12";
import {
  createPaginationContract,
  type RankingListQuery,
  type RankingSort,
} from "./query-params";
import { hypothesisFamilies } from "./hypothesis-universe";

const MAX_RANKING_ITEMS = 10;
const PUBLIC_STATUS = "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING";
const OBSERVED_TIME_STATUS = "SOURCE_PRICE_CLASS_ONLY";
const HASH_64 = /^[0-9a-f]{64}$/u;
const REVISION_40 = /^[0-9a-f]{40}$/u;

const rankingDefinitions = {
  "drawdown-asc": {
    bucket: "by_lowest_drawdown",
    metric: "maximum_drawdown_units",
    ordering: ["MAXIMUM_DRAWDOWN_UNITS_ASC", "RULE_HASH_ASC"],
  },
  "hit-rate-desc": {
    bucket: "by_hit_rate",
    metric: "hit_rate",
    ordering: ["HIT_RATE_DESC", "RULE_HASH_ASC"],
  },
  "profit-desc": {
    bucket: "by_profit",
    metric: "profit_units",
    ordering: ["PROFIT_UNITS_DESC", "RULE_HASH_ASC"],
  },
  "roi-desc": {
    bucket: "by_roi",
    metric: "roi",
    ordering: ["ROI_DESC", "RULE_HASH_ASC"],
  },
  "support-desc": {
    bucket: "by_support",
    metric: "occurrences",
    ordering: ["OCCURRENCES_DESC", "RULE_HASH_ASC"],
  },
} as const satisfies Record<
  RankingSort,
  {
    bucket: string;
    metric: string;
    ordering: readonly string[];
  }
>;

export type HistoricalEvidenceSort = RankingSort;
type RankingBucketName =
  (typeof rankingDefinitions)[HistoricalEvidenceSort]["bucket"];

export type HistoricalEvidenceFilterOption = Readonly<{
  label: string;
  value: string;
}>;

export type HistoricalEvidenceMetrics = Readonly<{
  averageOdds: number;
  confidenceInterval: readonly [number, number];
  correctedFalsePositiveRisk: number;
  eligibleFolds: number;
  hitRate: number;
  longestLosingStreak: number;
  losses: number;
  maximumDrawdownUnits: number;
  medianOdds: number;
  occurrences: number;
  pValue: number;
  positiveFolds: number;
  profitUnits: number;
  roi: number;
  settledOccurrences: number;
  voids: number;
  wins: number;
}>;

export interface HistoricalEvidenceConditionArray {
  readonly [index: number]: HistoricalEvidenceConditionValue;
  readonly length: number;
}

export interface HistoricalEvidenceConditionObject {
  readonly [key: string]: HistoricalEvidenceConditionValue;
}

export type HistoricalEvidenceConditionValue =
  | boolean
  | number
  | string
  | null
  | HistoricalEvidenceConditionArray
  | HistoricalEvidenceConditionObject;

export type HistoricalEvidenceCondition = Readonly<{
  availableAt: string;
  feature: string;
  operator: string;
  source: string;
  value: HistoricalEvidenceConditionValue;
}>;

export type HistoricalEvidenceStatisticalCoverage = Readonly<{
  distinctSeasons: number;
  distinctTeams: number;
  grossReturnsUnits: number;
  statisticalGroups: number;
  totalStakedUnits: number;
}>;

export type HistoricalEvidenceRankingEntry = RankingEntryContract &
  Readonly<{
    evidenceScope: string;
    membershipSetHash: string;
    metrics: HistoricalEvidenceMetrics;
    ruleHash: string;
    selection: string;
  }>;

export type HistoricalEvidenceRankingPage = Omit<
  RankingPageContract,
  "category" | "items"
> &
  Readonly<{
    activeFilters: {
      competition: string | null;
      cutoff: string | null;
      family: string | null;
      market: string | null;
      origin: string | null;
    };
    boundedItemLimit: typeof MAX_RANKING_ITEMS;
    category: "historical_raw";
    filters: {
      competitions: readonly HistoricalEvidenceFilterOption[];
      cutoffs: readonly HistoricalEvidenceFilterOption[];
      families: readonly HistoricalEvidenceFilterOption[];
      markets: readonly HistoricalEvidenceFilterOption[];
      origins: readonly HistoricalEvidenceFilterOption[];
    };
    items: readonly HistoricalEvidenceRankingEntry[];
    reportWarning: string;
    selectionIsCompleteForRequestedTop: boolean;
    sort: HistoricalEvidenceSort;
    sourceRanking: RankingBucketName;
    sourceScope: string;
  }>;

export type HistoricalHypothesisEvidence = Readonly<{
  availability: {
    historical: true;
    prospective: false;
    prospectiveReason: "NOT_PRESENT_IN_HISTORICAL_EVIDENCE_REPORT";
  };
  competition: string;
  conditions: readonly HistoricalEvidenceCondition[];
  evidenceScope: string;
  family: string;
  hypothesisId: string;
  labelFr: string;
  market: string;
  metrics: HistoricalEvidenceMetrics;
  provenance: {
    datasetHash: string;
    generatedAt: string;
    historicalDataRevision: string;
    membershipSetHash: string;
    replayHash: string;
    reportSchemaVersion: string;
    ruleHash: string;
    sourceResultHash: string;
  };
  rankByRoi: number | null;
  schemaVersion: "historical-hypothesis-evidence-detail-v1.2";
  scientificStatus: typeof PUBLIC_STATUS;
  selection: string;
  statisticalCoverage: HistoricalEvidenceStatisticalCoverage;
  temporalEvidence: {
    exactIntradayTimestamp: false;
    observedTimeStatus: typeof OBSERVED_TIME_STATUS;
    pointInTimeClaim: false;
  };
  warningFr: string;
}>;

export type HistoricalEvidenceReportSummary = Readonly<{
  datasetHash: string;
  duplicateMemberships: number;
  fixtures: number;
  generatedAt: string;
  historicalDataRevision: string;
  memberships: number;
  reconciled: true;
  replayHash: string;
  rules: number;
  sourceResultHash: string;
  validatedLabelForbidden: true;
}>;

type RawEvidenceItem = {
  average_odds: number;
  competition: string;
  conditions: Array<{
    available_at: string;
    feature: string;
    operator: string;
    source: string;
    value: HistoricalEvidenceConditionValue;
  }>;
  confidence_interval: [number, number];
  distinct_seasons: number;
  distinct_teams: number;
  eligible_folds: number;
  evidence_scope: string;
  family: string;
  gross_returns_units: number;
  hit_rate: number;
  hypothesis_id: string;
  longest_losing_streak: number;
  losses: number;
  market: string;
  maximum_drawdown_units: number;
  median_odds: number;
  membership_set_hash: string;
  occurrences: number;
  p_value: number;
  positive_folds: number;
  profit_units: number;
  q_value: number;
  roi: number;
  rule_hash: string;
  selection: string;
  settled_occurrences: number;
  statistical_groups: number;
  status: typeof PUBLIC_STATUS;
  total_staked_units: number;
  voids: number;
  wins: number;
};

type RawRankingBucket = {
  available_count: number;
  complete: boolean;
  duplicate_membership_sets_removed: number;
  items: RawEvidenceItem[];
  ordering: string[];
  requested_limit: number;
};

type RawRankingScope = Record<RankingBucketName, RawRankingBucket>;

type ValidatedReports = {
  artifactHashes: {
    replayHash: string;
  };
  datasetHash: string;
  generatedAt: string;
  historicalDataRevision: string;
  observationTimeStatus: typeof OBSERVED_TIME_STATUS;
  pointInTimeClaim: false;
  reconciliation: {
    duplicateMemberships: number;
    fixtures: number;
    memberships: number;
    rules: number;
  };
  replayHash: string;
  reportWarning: string;
  scopes: {
    byCompetition: Record<string, RawRankingScope>;
    byFamily: Record<string, RawRankingScope>;
    global: RawRankingScope;
  };
  schemaVersion: string;
  sourceResultHash: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredRecord(
  value: unknown,
  label: string,
): Record<string, unknown> {
  if (!isRecord(value)) throw new Error(`HISTORICAL_EVIDENCE_RECORD_INVALID:${label}`);
  return value;
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`HISTORICAL_EVIDENCE_STRING_INVALID:${label}`);
  }
  return value;
}

function requiredHash(value: unknown, label: string): string {
  const candidate = requiredString(value, label);
  if (!HASH_64.test(candidate)) {
    throw new Error(`HISTORICAL_EVIDENCE_HASH_INVALID:${label}`);
  }
  return candidate;
}

function requiredRevision(value: unknown, label: string): string {
  const candidate = requiredString(value, label);
  if (!REVISION_40.test(candidate)) {
    throw new Error(`HISTORICAL_EVIDENCE_REVISION_INVALID:${label}`);
  }
  return candidate;
}

function requiredBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`HISTORICAL_EVIDENCE_BOOLEAN_INVALID:${label}`);
  }
  return value;
}

function requiredNumber(value: unknown, label: string): number {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value)
  ) {
    throw new Error(`HISTORICAL_EVIDENCE_NUMBER_INVALID:${label}`);
  }
  return value;
}

function requiredInteger(
  value: unknown,
  label: string,
  minimum = 0,
): number {
  const candidate = requiredNumber(value, label);
  if (!Number.isInteger(candidate) || candidate < minimum) {
    throw new Error(`HISTORICAL_EVIDENCE_INTEGER_INVALID:${label}`);
  }
  return candidate;
}

function requiredArray(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`HISTORICAL_EVIDENCE_ARRAY_INVALID:${label}`);
  }
  return value;
}

function requiredJsonValue(
  value: unknown,
  label: string,
): HistoricalEvidenceConditionValue {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean"
  ) {
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new Error(`HISTORICAL_EVIDENCE_JSON_NUMBER_INVALID:${label}`);
    }
    return value;
  }
  if (Array.isArray(value)) {
    if (value.length > 16) {
      throw new Error(`HISTORICAL_EVIDENCE_JSON_ARRAY_OVER_LIMIT:${label}`);
    }
    return value.map((item, index) =>
      requiredJsonValue(item, `${label}[${index}]`),
    );
  }
  if (isRecord(value)) {
    const entries = Object.entries(value);
    if (entries.length > 16) {
      throw new Error(`HISTORICAL_EVIDENCE_JSON_OBJECT_OVER_LIMIT:${label}`);
    }
    return Object.fromEntries(
      entries.map(([key, item]) => [
        key,
        requiredJsonValue(item, `${label}.${key}`),
      ]),
    );
  }
  throw new Error(`HISTORICAL_EVIDENCE_JSON_VALUE_INVALID:${label}`);
}

function parseConditions(
  value: unknown,
  label: string,
): RawEvidenceItem["conditions"] {
  const conditions = requiredArray(value, label);
  if (conditions.length > 16) {
    throw new Error(`HISTORICAL_EVIDENCE_CONDITIONS_OVER_LIMIT:${label}`);
  }
  return conditions.map((condition, index) => {
    const item = requiredRecord(condition, `${label}[${index}]`);
    return {
      available_at: requiredString(
        item.available_at,
        `${label}[${index}].available_at`,
      ),
      feature: requiredString(
        item.feature,
        `${label}[${index}].feature`,
      ),
      operator: requiredString(
        item.operator,
        `${label}[${index}].operator`,
      ),
      source: requiredString(
        item.source,
        `${label}[${index}].source`,
      ),
      value: requiredJsonValue(
        item.value,
        `${label}[${index}].value`,
      ),
    };
  });
}

function parseEvidenceItem(
  value: unknown,
  label: string,
  publicStatus: string,
): RawEvidenceItem {
  const item = requiredRecord(value, label);
  const confidence = requiredArray(
    item.confidence_interval,
    `${label}.confidence_interval`,
  );
  if (confidence.length !== 2) {
    throw new Error(`HISTORICAL_EVIDENCE_INTERVAL_INVALID:${label}`);
  }
  const status = requiredString(item.status, `${label}.status`);
  if (status !== publicStatus || status !== PUBLIC_STATUS) {
    throw new Error(`HISTORICAL_EVIDENCE_PUBLIC_STATUS_INVALID:${label}`);
  }
  const occurrences = requiredInteger(
    item.occurrences,
    `${label}.occurrences`,
  );
  const settledOccurrences = requiredInteger(
    item.settled_occurrences,
    `${label}.settled_occurrences`,
  );
  const wins = requiredInteger(item.wins, `${label}.wins`);
  const losses = requiredInteger(item.losses, `${label}.losses`);
  const voids = requiredInteger(item.voids, `${label}.voids`);
  const eligibleFolds = requiredInteger(
    item.eligible_folds,
    `${label}.eligible_folds`,
  );
  const positiveFolds = requiredInteger(
    item.positive_folds,
    `${label}.positive_folds`,
  );
  if (
    settledOccurrences > occurrences ||
    wins + losses + voids !== settledOccurrences ||
    positiveFolds > eligibleFolds
  ) {
    throw new Error(`HISTORICAL_EVIDENCE_COUNTS_INCONSISTENT:${label}`);
  }

  const pValue = requiredNumber(item.p_value, `${label}.p_value`);
  const qValue = requiredNumber(item.q_value, `${label}.q_value`);
  const hitRate = requiredNumber(item.hit_rate, `${label}.hit_rate`);
  if (
    pValue < 0 ||
    pValue > 1 ||
    qValue < 0 ||
    qValue > 1 ||
    hitRate < 0 ||
    hitRate > 1
  ) {
    throw new Error(`HISTORICAL_EVIDENCE_RATE_INVALID:${label}`);
  }

  return {
    average_odds: requiredNumber(item.average_odds, `${label}.average_odds`),
    competition: requiredString(item.competition, `${label}.competition`),
    conditions: parseConditions(item.conditions, `${label}.conditions`),
    confidence_interval: [
      requiredNumber(confidence[0], `${label}.confidence_interval[0]`),
      requiredNumber(confidence[1], `${label}.confidence_interval[1]`),
    ],
    distinct_seasons: requiredInteger(
      item.distinct_seasons,
      `${label}.distinct_seasons`,
    ),
    distinct_teams: requiredInteger(
      item.distinct_teams,
      `${label}.distinct_teams`,
    ),
    eligible_folds: eligibleFolds,
    evidence_scope: requiredString(
      item.evidence_scope,
      `${label}.evidence_scope`,
    ),
    family: requiredString(item.family, `${label}.family`),
    gross_returns_units: requiredNumber(
      item.gross_returns_units,
      `${label}.gross_returns_units`,
    ),
    hit_rate: hitRate,
    hypothesis_id: requiredString(
      item.hypothesis_id,
      `${label}.hypothesis_id`,
    ),
    longest_losing_streak: requiredInteger(
      item.longest_losing_streak,
      `${label}.longest_losing_streak`,
    ),
    losses,
    market: requiredString(item.market, `${label}.market`),
    maximum_drawdown_units: requiredNumber(
      item.maximum_drawdown_units,
      `${label}.maximum_drawdown_units`,
    ),
    median_odds: requiredNumber(item.median_odds, `${label}.median_odds`),
    membership_set_hash: requiredHash(
      item.membership_set_hash,
      `${label}.membership_set_hash`,
    ),
    occurrences,
    p_value: pValue,
    positive_folds: positiveFolds,
    profit_units: requiredNumber(item.profit_units, `${label}.profit_units`),
    q_value: qValue,
    roi: requiredNumber(item.roi, `${label}.roi`),
    rule_hash: requiredHash(item.rule_hash, `${label}.rule_hash`),
    selection: requiredString(item.selection, `${label}.selection`),
    settled_occurrences: settledOccurrences,
    statistical_groups: requiredInteger(
      item.statistical_groups,
      `${label}.statistical_groups`,
    ),
    status: PUBLIC_STATUS,
    total_staked_units: requiredNumber(
      item.total_staked_units,
      `${label}.total_staked_units`,
    ),
    voids,
    wins,
  };
}

function compareEvidence(
  left: RawEvidenceItem,
  right: RawEvidenceItem,
  metric: keyof Pick<
    RawEvidenceItem,
    | "hit_rate"
    | "maximum_drawdown_units"
    | "occurrences"
    | "profit_units"
    | "roi"
  >,
  direction: "asc" | "desc",
) {
  const delta =
    direction === "asc"
      ? left[metric] - right[metric]
      : right[metric] - left[metric];
  return delta || left.rule_hash.localeCompare(right.rule_hash, "en");
}

function parseRankingBucket(
  value: unknown,
  label: string,
  sort: HistoricalEvidenceSort,
  publicStatus: string,
): RawRankingBucket {
  const bucket = requiredRecord(value, label);
  const requestedLimit = requiredInteger(
    bucket.requested_limit,
    `${label}.requested_limit`,
    1,
  );
  if (requestedLimit !== MAX_RANKING_ITEMS) {
    throw new Error(`HISTORICAL_EVIDENCE_LIMIT_INVALID:${label}`);
  }
  const items = requiredArray(bucket.items, `${label}.items`).map(
    (item, index) =>
      parseEvidenceItem(item, `${label}.items[${index}]`, publicStatus),
  );
  if (items.length > MAX_RANKING_ITEMS) {
    throw new Error(`HISTORICAL_EVIDENCE_ITEMS_OVER_LIMIT:${label}`);
  }
  const seenRules = new Set<string>();
  const seenMembershipSets = new Set<string>();
  for (const item of items) {
    if (
      seenRules.has(item.rule_hash) ||
      seenMembershipSets.has(item.membership_set_hash)
    ) {
      throw new Error(`HISTORICAL_EVIDENCE_RANKING_DUPLICATE:${label}`);
    }
    seenRules.add(item.rule_hash);
    seenMembershipSets.add(item.membership_set_hash);
  }
  const definition = rankingDefinitions[sort];
  const direction = sort === "drawdown-asc" ? "asc" : "desc";
  const ordered = [...items].sort((left, right) =>
    compareEvidence(left, right, definition.metric, direction),
  );
  if (ordered.some((item, index) => item.rule_hash !== items[index]?.rule_hash)) {
    throw new Error(`HISTORICAL_EVIDENCE_ORDER_INVALID:${label}`);
  }
  const ordering = requiredArray(
    bucket.ordering,
    `${label}.ordering`,
  ).map((item, index) =>
    requiredString(item, `${label}.ordering[${index}]`),
  );
  if (
    ordering.length !== definition.ordering.length ||
    ordering.some((item, index) => item !== definition.ordering[index])
  ) {
    throw new Error(`HISTORICAL_EVIDENCE_ORDER_CONTRACT_INVALID:${label}`);
  }
  return {
    available_count: requiredInteger(
      bucket.available_count,
      `${label}.available_count`,
    ),
    complete: requiredBoolean(bucket.complete, `${label}.complete`),
    duplicate_membership_sets_removed: requiredInteger(
      bucket.duplicate_membership_sets_removed,
      `${label}.duplicate_membership_sets_removed`,
    ),
    items,
    ordering,
    requested_limit: requestedLimit,
  };
}

function parseRankingScope(
  value: unknown,
  label: string,
  publicStatus: string,
): RawRankingScope {
  const scope = requiredRecord(value, label);
  const output = {} as RawRankingScope;
  for (const sort of Object.keys(
    rankingDefinitions,
  ) as HistoricalEvidenceSort[]) {
    const bucketName = rankingDefinitions[sort].bucket;
    output[bucketName] = parseRankingBucket(
      scope[bucketName],
      `${label}.${bucketName}`,
      sort,
      publicStatus,
    );
  }
  return output;
}

function parseScopeMap(
  value: unknown,
  label: string,
  publicStatus: string,
): Record<string, RawRankingScope> {
  const map = requiredRecord(value, label);
  return Object.fromEntries(
    Object.entries(map).map(([key, scope]) => [
      key,
      parseRankingScope(scope, `${label}.${key}`, publicStatus),
    ]),
  );
}

function validateReports(): ValidatedReports {
  const topTen = requiredRecord(rawTopTen, "top-10");
  const selection = requiredRecord(
    topTen.selection_contract,
    "top-10.selection_contract",
  );
  const publicStatus = requiredString(
    selection.public_status,
    "top-10.selection_contract.public_status",
  );
  if (
    publicStatus !== PUBLIC_STATUS ||
    selection.validated_label_forbidden !== true
  ) {
    throw new Error("HISTORICAL_EVIDENCE_SCIENTIFIC_GUARD_INVALID");
  }
  const datasetHash = requiredHash(topTen.dataset_hash, "top-10.dataset_hash");
  const sourceResultHash = requiredHash(
    topTen.source_result_hash,
    "top-10.source_result_hash",
  );

  const provenance = requiredRecord(rawSourceProvenance, "source-provenance");
  const logicalSource = requiredRecord(
    provenance.logical_campaign_source,
    "source-provenance.logical_campaign_source",
  );
  if (
    requiredHash(
      logicalSource.dataset_hash,
      "source-provenance.logical_campaign_source.dataset_hash",
    ) !== datasetHash
  ) {
    throw new Error("HISTORICAL_EVIDENCE_DATASET_RELATION_INVALID");
  }
  const priceTime = requiredRecord(
    provenance.price_time_contract,
    "source-provenance.price_time_contract",
  );
  if (
    priceTime.exact_intraday_timestamp !== false ||
    priceTime.point_in_time_claim !== false ||
    priceTime.observed_time_status !== OBSERVED_TIME_STATUS
  ) {
    throw new Error("HISTORICAL_EVIDENCE_TEMPORAL_CLAIM_INVALID");
  }

  const reconciliation = requiredRecord(
    rawReconciliation,
    "reconciliation",
  );
  const checks = requiredRecord(
    reconciliation.checks,
    "reconciliation.checks",
  );
  if (
    reconciliation.status !== "RECONCILED" ||
    reconciliation.dataset_hash !== datasetHash ||
    reconciliation.source_result_hash !== sourceResultHash ||
    checks.q_values_recomputed !== true ||
    checks.provider_calls !== 0 ||
    checks.database_writes !== 0 ||
    checks.r2_operations !== 0
  ) {
    throw new Error("HISTORICAL_EVIDENCE_RECONCILIATION_INVALID");
  }
  const duplicateMemberships = requiredInteger(
    checks.duplicate_rule_canonical_match,
    "reconciliation.checks.duplicate_rule_canonical_match",
  );
  if (duplicateMemberships !== 0) {
    throw new Error("HISTORICAL_EVIDENCE_DUPLICATES_PRESENT");
  }

  const artifactHashes = requiredRecord(rawArtifactHashes, "artifact-hashes");
  const replayHash = requiredHash(
    reconciliation.replay_hash,
    "reconciliation.replay_hash",
  );
  if (artifactHashes.replay_hash !== replayHash) {
    throw new Error("HISTORICAL_EVIDENCE_REPLAY_RELATION_INVALID");
  }

  return {
    artifactHashes: { replayHash },
    datasetHash,
    generatedAt: requiredString(
      reconciliation.generated_at,
      "reconciliation.generated_at",
    ),
    historicalDataRevision: requiredRevision(
      logicalSource.historical_data_revision,
      "source-provenance.logical_campaign_source.historical_data_revision",
    ),
    observationTimeStatus: OBSERVED_TIME_STATUS,
    pointInTimeClaim: false,
    reconciliation: {
      duplicateMemberships,
      fixtures: requiredInteger(
        checks.unique_fixtures,
        "reconciliation.checks.unique_fixtures",
      ),
      memberships: requiredInteger(
        checks.strict_memberships,
        "reconciliation.checks.strict_memberships",
      ),
      rules: requiredInteger(checks.rules, "reconciliation.checks.rules"),
    },
    replayHash,
    reportWarning:
      "Preuve historique exploratoire, rejetée après correction des tests multiples ; elle ne prédit pas une performance future.",
    scopes: {
      byCompetition: parseScopeMap(
        topTen.by_competition,
        "top-10.by_competition",
        publicStatus,
      ),
      byFamily: parseScopeMap(
        topTen.by_family,
        "top-10.by_family",
        publicStatus,
      ),
      global: parseRankingScope(
        topTen.global,
        "top-10.global",
        publicStatus,
      ),
    },
    schemaVersion: requiredString(
      topTen.schema_version,
      "top-10.schema_version",
    ),
    sourceResultHash,
  };
}

function deepFreeze<T>(value: T): T {
  if (typeof value !== "object" || value === null || Object.isFrozen(value)) {
    return value;
  }
  Object.freeze(value);
  for (const child of Object.values(value)) deepFreeze(child);
  return value;
}

const reports = validateReports();

const competitionAliases = new Map<string, string>([
  ["LIGA", "La Liga"],
  ...Object.keys(reports.scopes.byCompetition).map(
    (competition) =>
      [competition.toLocaleUpperCase("fr-FR"), competition] as const,
  ),
]);

function resolveCompetition(value: string | null): string | null {
  if (!value) return null;
  return competitionAliases.get(value.toLocaleUpperCase("fr-FR")) ?? null;
}

function selectionLabel(selection: string): string {
  const labels: Record<string, string> = {
    AWAY: "Victoire à l’extérieur",
    DRAW: "Match nul",
    HOME: "Victoire à domicile",
  };
  return labels[selection] ?? "Sélection documentée";
}

function marketLabel(market: string): string {
  const labels: Record<string, string> = {
    "1X2_AWAY": "Résultat du match · victoire à l’extérieur",
    "1X2_DRAW": "Résultat du match · match nul",
    "1X2_HOME": "Résultat du match · victoire à domicile",
  };
  return labels[market] ?? "Marché documenté";
}

function competitionLabel(competition: string): string {
  return competition === "La Liga" ? "Liga" : competition;
}

function evidenceLabel(item: RawEvidenceItem): string {
  const competition =
    item.competition === "ALL_AVAILABLE"
      ? "tous les championnats disponibles"
      : item.competition;
  return `${selectionLabel(item.selection)} en ${competition}`;
}

function toMetrics(item: RawEvidenceItem): HistoricalEvidenceMetrics {
  return deepFreeze({
    averageOdds: item.average_odds,
    confidenceInterval: [
      item.confidence_interval[0],
      item.confidence_interval[1],
    ] as const,
    correctedFalsePositiveRisk: item.q_value,
    eligibleFolds: item.eligible_folds,
    hitRate: item.hit_rate,
    longestLosingStreak: item.longest_losing_streak,
    losses: item.losses,
    maximumDrawdownUnits: item.maximum_drawdown_units,
    medianOdds: item.median_odds,
    occurrences: item.occurrences,
    pValue: item.p_value,
    positiveFolds: item.positive_folds,
    profitUnits: item.profit_units,
    roi: item.roi,
    settledOccurrences: item.settled_occurrences,
    voids: item.voids,
    wins: item.wins,
  });
}

function toConditions(
  item: RawEvidenceItem,
): readonly HistoricalEvidenceCondition[] {
  return deepFreeze(
    item.conditions.map((condition) => ({
      availableAt: condition.available_at,
      feature: condition.feature,
      operator: condition.operator,
      source: condition.source,
      value: condition.value,
    })),
  );
}

function toStatisticalCoverage(
  item: RawEvidenceItem,
): HistoricalEvidenceStatisticalCoverage {
  return deepFreeze({
    distinctSeasons: item.distinct_seasons,
    distinctTeams: item.distinct_teams,
    grossReturnsUnits: item.gross_returns_units,
    statisticalGroups: item.statistical_groups,
    totalStakedUnits: item.total_staked_units,
  });
}

const presentationProvenance: PresentationProvenance = deepFreeze({
  generatedAt: reports.generatedAt,
  sourceContracts: [
    reports.schemaVersion,
    "j10-hypothesis-evidence-reconciliation-v1",
    "j10-hypothesis-evidence-source-provenance-v1",
  ],
  sourceHashes: [
    reports.datasetHash,
    reports.sourceResultHash,
    reports.replayHash,
  ],
  sourceRevision: reports.historicalDataRevision,
});

function toRankingEntry(
  item: RawEvidenceItem,
  rank: number,
): HistoricalEvidenceRankingEntry {
  const competition =
    item.competition === "ALL_AVAILABLE" ? null : item.competition;
  const metrics = toMetrics(item);
  return deepFreeze({
    category: "historical_raw",
    competition,
    cutoff: null,
    evidence: {
      confidenceInterval: metrics.confidenceInterval,
      correctedFalsePositiveRisk:
        metrics.correctedFalsePositiveRisk,
      maximumDrawdown: metrics.maximumDrawdownUnits,
      phase: "historical",
      profitUnits: metrics.profitUnits,
      roi: metrics.roi,
      stability: null,
      support: metrics.occurrences,
    },
    evidenceScope: item.evidence_scope,
    family: item.family,
    hypothesisId: item.hypothesis_id,
    labelFr: evidenceLabel(item),
    market: item.market,
    membershipSetHash: item.membership_set_hash,
    metrics,
    origin: item.evidence_scope,
    rank,
    ruleHash: item.rule_hash,
    scientificStatus: item.status,
    selection: item.selection,
    tieBreakKey: item.rule_hash,
  });
}

function rankingScope(
  query: RankingListQuery,
): {
  bucketScope: RawRankingScope | null;
  nativeFilter: "competition" | "family" | "global";
  scope: RankingScope;
  sourceScope: string;
} {
  if (query.competition) {
    const competition = resolveCompetition(query.competition);
    return {
      bucketScope: competition
        ? reports.scopes.byCompetition[competition] ?? null
        : null,
      nativeFilter: "competition",
      scope: {
        competition: competition ?? query.competition,
        kind: "competition",
      },
      sourceScope: competition
        ? `by_competition.${competition}`
        : "by_competition.UNKNOWN",
    };
  }
  if (query.family) {
    return {
      bucketScope: reports.scopes.byFamily[query.family] ?? null,
      nativeFilter: "family",
      scope: { family: query.family, kind: "family" },
      sourceScope: `by_family.${query.family}`,
    };
  }
  if (query.market) {
    return {
      bucketScope: reports.scopes.global,
      nativeFilter: "global",
      scope: { kind: "market", market: query.market },
      sourceScope: "global.filtered_by_market",
    };
  }
  if (query.origin) {
    return {
      bucketScope: reports.scopes.global,
      nativeFilter: "global",
      scope: { kind: "origin", origin: query.origin },
      sourceScope: "global.filtered_by_origin",
    };
  }
  if (query.cutoff) {
    return {
      bucketScope: reports.scopes.global,
      nativeFilter: "global",
      scope: { cutoff: query.cutoff, kind: "cutoff" },
      sourceScope: "global.filtered_by_temporal_availability",
    };
  }
  return {
    bucketScope: reports.scopes.global,
    nativeFilter: "global",
    scope: { kind: "global" },
    sourceScope: "global",
  };
}

function filterItems(
  items: readonly RawEvidenceItem[],
  query: RankingListQuery,
  nativeFilter: "competition" | "family" | "global",
): RawEvidenceItem[] {
  const resolvedCompetition = resolveCompetition(query.competition);
  const originMatches =
    query.origin == null || query.origin === "DISCOVERY_EXPOSED";
  const cutoffMatches =
    query.cutoff == null || query.cutoff === OBSERVED_TIME_STATUS;
  if (!originMatches || !cutoffMatches) return [];
  return items.filter(
    (item) =>
      (nativeFilter === "competition" ||
        resolvedCompetition == null ||
        item.competition === resolvedCompetition) &&
      (nativeFilter === "family" ||
        query.family == null ||
        item.family === query.family) &&
      (query.market == null || item.market === query.market),
  );
}

function filterOptions(): HistoricalEvidenceRankingPage["filters"] {
  const globalItems = Object.values(reports.scopes.global).flatMap(
    (bucket) => bucket.items,
  );
  const markets = [...new Set(globalItems.map((item) => item.market))].sort();
  return deepFreeze({
    competitions: Object.keys(reports.scopes.byCompetition)
      .filter((competition) => competition !== "ALL_AVAILABLE")
      .map((competition) => ({
        label: competitionLabel(competition),
        value: competitionLabel(competition),
      })),
    cutoffs: [
      {
        label: "Heure exacte non prouvée",
        value: OBSERVED_TIME_STATUS,
      },
    ],
    families: hypothesisFamilies
      .map((family) => ({
        label: family.display_name_fr,
        value: family.family,
      }))
      .sort((left, right) => left.label.localeCompare(right.label, "fr")),
    markets: markets.map((market) => ({
      label: marketLabel(market),
      value: market,
    })),
    origins: [
      {
        label: "Découverte historique de Robin",
        value: "DISCOVERY_EXPOSED",
      },
    ],
  });
}

const filters = filterOptions();

export function getHistoricalEvidenceRankingPage(
  query: RankingListQuery,
): HistoricalEvidenceRankingPage {
  const sort = query.sort;
  const bucketName = rankingDefinitions[sort].bucket;
  const resolvedScope = rankingScope(query);
  const bucket = resolvedScope.bucketScope?.[bucketName] ?? null;
  const filtered = bucket
    ? filterItems(bucket.items, query, resolvedScope.nativeFilter)
    : [];
  const postFiltered =
    query.market != null ||
    query.origin != null ||
    query.cutoff != null ||
    (query.family != null && resolvedScope.nativeFilter !== "family") ||
    (query.competition != null &&
      resolvedScope.nativeFilter !== "competition");
  const items = filtered
    .slice(0, MAX_RANKING_ITEMS)
    .map((item, index) => toRankingEntry(item, index + 1));
  const pagination = createPaginationContract(
    query.page,
    query.pageSize,
    items.length,
  );
  const start = (pagination.page - 1) * pagination.pageSize;
  const pageItems = items.slice(start, start + pagination.pageSize);

  return deepFreeze({
    activeFilters: {
      competition: query.competition,
      cutoff: query.cutoff,
      family: query.family,
      market: query.market,
      origin: query.origin,
    },
    availableCount: postFiltered
      ? filtered.length
      : (bucket?.available_count ?? 0),
    boundedItemLimit: MAX_RANKING_ITEMS,
    category: "historical_raw",
    complete: bucket == null ? false : bucket.complete && !postFiltered,
    filters,
    items: pageItems,
    pagination,
    provenance: presentationProvenance,
    reportWarning: reports.reportWarning,
    requestedTop: MAX_RANKING_ITEMS,
    schemaVersion: "ranking-page-v1.2",
    selectionIsCompleteForRequestedTop:
      bucket == null ? false : bucket.complete && !postFiltered,
    sort,
    sourceRanking: bucketName,
    sourceScope: resolvedScope.sourceScope,
    scope: resolvedScope.scope,
  });
}

function allEvidenceItems(): RawEvidenceItem[] {
  const items: RawEvidenceItem[] = [];
  for (const scope of [
    reports.scopes.global,
    ...Object.values(reports.scopes.byCompetition),
    ...Object.values(reports.scopes.byFamily),
  ]) {
    for (const bucket of Object.values(scope)) items.push(...bucket.items);
  }
  return items;
}

const rawEvidenceById = new Map<string, RawEvidenceItem>();
for (const item of allEvidenceItems()) {
  const existing = rawEvidenceById.get(item.hypothesis_id);
  if (
    existing &&
    (existing.rule_hash !== item.rule_hash ||
      existing.membership_set_hash !== item.membership_set_hash ||
      existing.status !== item.status ||
      JSON.stringify(existing.conditions) !==
        JSON.stringify(item.conditions) ||
      existing.statistical_groups !== item.statistical_groups ||
      existing.distinct_seasons !== item.distinct_seasons ||
      existing.distinct_teams !== item.distinct_teams)
  ) {
    throw new Error(
      `HISTORICAL_EVIDENCE_HYPOTHESIS_AMBIGUOUS:${item.hypothesis_id}`,
    );
  }
  rawEvidenceById.set(item.hypothesis_id, item);
}

const roiRanks = new Map(
  reports.scopes.global.by_roi.items.map(
    (item, index) => [item.hypothesis_id, index + 1] as const,
  ),
);

export function getHistoricalHypothesisEvidence(
  hypothesisId: string,
): HistoricalHypothesisEvidence | null {
  const item = rawEvidenceById.get(hypothesisId);
  if (!item) return null;
  return deepFreeze({
    availability: {
      historical: true,
      prospective: false,
      prospectiveReason: "NOT_PRESENT_IN_HISTORICAL_EVIDENCE_REPORT",
    },
    competition: item.competition,
    conditions: toConditions(item),
    evidenceScope: item.evidence_scope,
    family: item.family,
    hypothesisId: item.hypothesis_id,
    labelFr: evidenceLabel(item),
    market: item.market,
    metrics: toMetrics(item),
    provenance: {
      datasetHash: reports.datasetHash,
      generatedAt: reports.generatedAt,
      historicalDataRevision: reports.historicalDataRevision,
      membershipSetHash: item.membership_set_hash,
      replayHash: reports.replayHash,
      reportSchemaVersion: reports.schemaVersion,
      ruleHash: item.rule_hash,
      sourceResultHash: reports.sourceResultHash,
    },
    rankByRoi: roiRanks.get(item.hypothesis_id) ?? null,
    schemaVersion: "historical-hypothesis-evidence-detail-v1.2",
    scientificStatus: PUBLIC_STATUS,
    selection: item.selection,
    statisticalCoverage: toStatisticalCoverage(item),
    temporalEvidence: {
      exactIntradayTimestamp: false,
      observedTimeStatus: OBSERVED_TIME_STATUS,
      pointInTimeClaim: false,
    },
    warningFr: reports.reportWarning,
  });
}

export function getHistoricalEvidenceReportSummary(): HistoricalEvidenceReportSummary {
  return deepFreeze({
    datasetHash: reports.datasetHash,
    duplicateMemberships: reports.reconciliation.duplicateMemberships,
    fixtures: reports.reconciliation.fixtures,
    generatedAt: reports.generatedAt,
    historicalDataRevision: reports.historicalDataRevision,
    memberships: reports.reconciliation.memberships,
    reconciled: true,
    replayHash: reports.replayHash,
    rules: reports.reconciliation.rules,
    sourceResultHash: reports.sourceResultHash,
    validatedLabelForbidden: true,
  });
}

export const HISTORICAL_EVIDENCE_ITEM_LIMIT = MAX_RANKING_ITEMS;
