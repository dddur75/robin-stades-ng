import {
  DEFAULT_EXPERIENCE_PAGE_SIZE,
  isExperiencePageSize,
  type ExperiencePageSize,
} from "./contracts/experience-v12";
import type {
  HistoricalMatchDetail,
  HistoricalMembershipItem,
  HistoricalMembershipPage,
} from "./hypothesis-evidence-assets";
import {
  canonicalizeSearchParams,
  type SearchParamInput,
} from "./query-params";

const MAX_QUERY_PAGE = 10_000;
const MAX_FILTER_LENGTH = 120;
const HASH_64 = /^[0-9a-f]{64}$/u;
const HYPOTHESIS_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u;
const CANONICAL_MATCH_ID = /^[^/?#\u0000-\u001f]{1,512}$/u;
const DETAIL_REF = /^matches\/[0-9a-f]{64}\.json$/u;

export const HISTORICAL_MATCH_SORTS = [
  "date-asc",
  "date-desc",
  "odds-asc",
  "odds-desc",
  "profit-asc",
  "profit-desc",
  "outcome",
] as const;

export const HISTORICAL_MATCH_OUTCOMES = [
  "all",
  "won",
  "lost",
  "void",
] as const;

export const HISTORICAL_MATCH_SELECTIONS = [
  "all",
  "HOME",
  "DRAW",
  "AWAY",
] as const;

export const HISTORICAL_ODDS_BANDS = [
  "all",
  "under-1.60",
  "1.60-2.00",
  "2.00-2.50",
  "2.50-3.25",
  "over-3.25",
] as const;

export type HistoricalMatchSort =
  (typeof HISTORICAL_MATCH_SORTS)[number];
export type HistoricalMatchOutcome =
  (typeof HISTORICAL_MATCH_OUTCOMES)[number];
export type HistoricalMatchSelection =
  (typeof HISTORICAL_MATCH_SELECTIONS)[number];
export type HistoricalOddsBand =
  (typeof HISTORICAL_ODDS_BANDS)[number];

export type HistoricalMatchListQuery = Readonly<{
  fold: string | null;
  oddsBand: HistoricalOddsBand;
  outcome: HistoricalMatchOutcome;
  page: number;
  pageSize: ExperiencePageSize;
  season: string | null;
  selection: HistoricalMatchSelection;
  sort: HistoricalMatchSort;
  team: string;
}>;

export type HistoricalRuleCondition = Readonly<{
  availableAt: string | null;
  feature: string;
  operator: string;
  source: string | null;
  value: unknown;
}>;

export type HistoricalEligibilityReason = Readonly<{
  codes: readonly string[];
  conditionDefinitionsRef: string;
  eligibilityReason: string;
  perConditionEvaluationInSource: false;
  sourceColumns: readonly string[];
}>;

export type HistoricalFixture = Readonly<{
  awayTeam: Readonly<{ id: string; name: string }>;
  competition: string;
  competitionKey: string;
  finalScore: Readonly<{ away: number; home: number }>;
  finalStatus: string;
  homeTeam: Readonly<{ id: string; name: string }>;
  kickoffAt: string;
  kickoffTimestamp: number;
  matchDate: string;
  round: string | null;
  season: string;
}>;

export type HistoricalMembershipRow = Readonly<{
  canonicalMatchId: string;
  chronologicalFold: string;
  cumulativeProfitUnits: number;
  fixture: HistoricalFixture;
  grossReturnUnits: number;
  market: string;
  marketMargin: number;
  matchDetailRef: string;
  membershipHash: string;
  observedOdds: number;
  observedTimeStatus: string;
  occurrenceIndex: number;
  outcome: Exclude<HistoricalMatchOutcome, "all">;
  priceClass: string;
  profitUnits: number;
  reason: HistoricalEligibilityReason;
  selection: string;
  stakeUnits: number;
  statisticalGroup: string;
}>;

export type HistoricalMatchListRow = Readonly<{
  canonicalMatchId: string;
  chronologicalFold: string;
  cumulativeProfitUnits: number;
  fixture: HistoricalFixture;
  marketMargin: number;
  matchDetailRef: string;
  observedOdds: number;
  occurrenceIndex: number;
  outcome: Exclude<HistoricalMatchOutcome, "all">;
  profitUnits: number;
  selection: string;
}>;

export type HistoricalHypothesisRelation = Readonly<{
  hypothesisId: string;
  membership: Readonly<{
    market: string;
    marketMargin: number;
    membershipHash: string;
    observedOdds: number;
    outcome: Exclude<HistoricalMatchOutcome, "all">;
    profitUnits: number;
    selection: string;
  }>;
  membershipPageRefs: readonly Readonly<{
    itemIndex: number;
    page: number;
    pageSize: ExperiencePageSize;
    path: string;
  }>[];
  reason: HistoricalEligibilityReason;
  ruleHash: string;
  summaryRef: string;
}>;

export type NormalizedHistoricalMatchDetail = Readonly<{
  canonicalMatchId: string;
  fixture: HistoricalFixture;
  relations: readonly HistoricalHypothesisRelation[];
  source: Readonly<{
    datasetHash: string;
    observedTimeStatus: string;
    source: string;
    sourceRowHash: string;
  }>;
  totalHistoricalRules: number;
}>;

export class HistoricalEvidenceContractError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.name = "HistoricalEvidenceContractError";
    this.code = code;
  }
}

function firstValue(
  input: SearchParamInput,
  key: string,
): string | undefined {
  if (input instanceof URLSearchParams) {
    return input.get(key) ?? undefined;
  }
  const value = input[key];
  return typeof value === "string" ? value : value?.[0];
}

function cleanText(
  value: string | undefined,
  maximumLength = MAX_FILTER_LENGTH,
): string | null {
  if (!value) return null;
  const cleaned = value
    .replace(/\s+/gu, " ")
    .trim()
    .slice(0, maximumLength);
  return cleaned || null;
}

function parsePage(value: string | undefined): number {
  if (!value || !/^\d+$/u.test(value)) return 1;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1) return 1;
  return Math.min(parsed, MAX_QUERY_PAGE);
}

function enumValue<const Value extends string>(
  value: string | undefined,
  allowed: readonly Value[],
  fallback: Value,
): Value {
  return allowed.includes(value as Value) ? (value as Value) : fallback;
}

export function parseHistoricalMatchListQuery(
  input: SearchParamInput,
): HistoricalMatchListQuery {
  const parsedPageSize = Number(
    firstValue(input, "taille") ?? firstValue(input, "pageSize"),
  );
  return {
    fold: cleanText(firstValue(input, "periode")),
    oddsBand: enumValue(
      firstValue(input, "cotes"),
      HISTORICAL_ODDS_BANDS,
      "all",
    ),
    outcome: enumValue(
      firstValue(input, "resultat"),
      HISTORICAL_MATCH_OUTCOMES,
      "all",
    ),
    page: parsePage(firstValue(input, "page")),
    pageSize: isExperiencePageSize(parsedPageSize)
      ? parsedPageSize
      : DEFAULT_EXPERIENCE_PAGE_SIZE,
    season: cleanText(firstValue(input, "saison")),
    selection: enumValue(
      firstValue(input, "selection"),
      HISTORICAL_MATCH_SELECTIONS,
      "all",
    ),
    sort: enumValue(
      firstValue(input, "tri"),
      HISTORICAL_MATCH_SORTS,
      "date-asc",
    ),
    team: cleanText(firstValue(input, "equipe")) ?? "",
  };
}

export function serializeHistoricalMatchListQuery(
  query: HistoricalMatchListQuery,
): URLSearchParams {
  const params = new URLSearchParams();
  if (query.fold) params.set("periode", query.fold);
  if (query.oddsBand !== "all") params.set("cotes", query.oddsBand);
  if (query.outcome !== "all") params.set("resultat", query.outcome);
  if (query.page > 1) params.set("page", String(query.page));
  if (query.pageSize !== DEFAULT_EXPERIENCE_PAGE_SIZE) {
    params.set("taille", String(query.pageSize));
  }
  if (query.season) params.set("saison", query.season);
  if (query.selection !== "all") {
    params.set("selection", query.selection);
  }
  if (query.sort !== "date-asc") params.set("tri", query.sort);
  if (query.team) params.set("equipe", query.team);
  return canonicalizeSearchParams(params);
}

export function historicalMatchListNeedsFullScan(
  query: HistoricalMatchListQuery,
): boolean {
  return (
    query.fold !== null ||
    query.oddsBand !== "all" ||
    query.outcome !== "all" ||
    query.season !== null ||
    query.selection !== "all" ||
    query.sort !== "date-asc" ||
    query.team !== ""
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_RECORD_INVALID:${label}`,
    );
  }
  return value;
}

function stringValue(
  value: unknown,
  label: string,
  maximumLength = 512,
): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > maximumLength
  ) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_STRING_INVALID:${label}`,
    );
  }
  return value;
}

function displayScalar(
  value: unknown,
  label: string,
): string {
  if (typeof value === "string" && value.length > 0) return value;
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  throw new HistoricalEvidenceContractError(
    `HISTORICAL_EVIDENCE_DISPLAY_VALUE_INVALID:${label}`,
  );
}

function optionalDisplayScalar(
  value: unknown,
  label: string,
): string | null {
  return value == null ? null : displayScalar(value, label);
}

function finiteNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_NUMBER_INVALID:${label}`,
    );
  }
  return value;
}

function nonNegativeInteger(value: unknown, label: string): number {
  const parsed = finiteNumber(value, label);
  if (!Number.isInteger(parsed) || parsed < 0) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_INTEGER_INVALID:${label}`,
    );
  }
  return parsed;
}

function positiveInteger(value: unknown, label: string): number {
  const parsed = nonNegativeInteger(value, label);
  if (parsed < 1) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_POSITIVE_INTEGER_INVALID:${label}`,
    );
  }
  return parsed;
}

function booleanValue(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_BOOLEAN_INVALID:${label}`,
    );
  }
  return value;
}

function hashValue(value: unknown, label: string): string {
  const parsed = stringValue(value, label, 64);
  if (!HASH_64.test(parsed)) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_HASH_INVALID:${label}`,
    );
  }
  return parsed;
}

function hypothesisIdValue(value: unknown, label: string): string {
  const parsed = stringValue(value, label, 128);
  if (!HYPOTHESIS_ID.test(parsed)) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_HYPOTHESIS_ID_INVALID:${label}`,
    );
  }
  return parsed;
}

export function canonicalMatchIdValue(
  value: unknown,
  label = "canonical_match_id",
): string {
  const parsed = stringValue(value, label, 512);
  if (!CANONICAL_MATCH_ID.test(parsed)) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_MATCH_ID_INVALID:${label}`,
    );
  }
  return parsed;
}

function outcomeValue(
  membership: Record<string, unknown>,
  label: string,
): Exclude<HistoricalMatchOutcome, "all"> {
  const won = booleanValue(membership.won, `${label}.won`);
  const lost = booleanValue(membership.lost, `${label}.lost`);
  const voided = booleanValue(membership.void, `${label}.void`);
  if (Number(won) + Number(lost) + Number(voided) !== 1) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_OUTCOME_INVALID:${label}`,
    );
  }
  return won ? "won" : lost ? "lost" : "void";
}

function normalizeTeam(
  value: unknown,
  label: string,
): { id: string; name: string } {
  const team = record(value, label);
  return {
    id: displayScalar(team.id, `${label}.id`),
    name: stringValue(team.name, `${label}.name`),
  };
}

export function normalizeHistoricalFixture(
  value: unknown,
  label: string,
): HistoricalFixture {
  const fixture = record(value, label);
  const kickoffAt = stringValue(
    fixture.kickoff_at,
    `${label}.kickoff_at`,
  );
  const kickoffTimestamp = Date.parse(kickoffAt);
  if (!Number.isFinite(kickoffTimestamp)) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_DATE_INVALID:${label}.kickoff_at`,
    );
  }
  const score = record(fixture.final_score, `${label}.final_score`);
  const home = nonNegativeInteger(score.home, `${label}.final_score.home`);
  const away = nonNegativeInteger(score.away, `${label}.final_score.away`);
  const matchDate =
    typeof fixture.match_date === "string" &&
    /^\d{4}-\d{2}-\d{2}$/u.test(fixture.match_date)
      ? fixture.match_date
      : new Date(kickoffTimestamp).toISOString().slice(0, 10);
  return {
    awayTeam: normalizeTeam(fixture.away_team, `${label}.away_team`),
    competition: stringValue(
      fixture.competition,
      `${label}.competition`,
    ),
    competitionKey: stringValue(
      fixture.competition_key,
      `${label}.competition_key`,
    ),
    finalScore: { away, home },
    finalStatus: stringValue(
      fixture.final_status,
      `${label}.final_status`,
    ),
    homeTeam: normalizeTeam(fixture.home_team, `${label}.home_team`),
    kickoffAt,
    kickoffTimestamp,
    matchDate,
    round: optionalDisplayScalar(fixture.round, `${label}.round`),
    season: displayScalar(fixture.season, `${label}.season`),
  };
}

function normalizeReason(
  value: unknown,
  label: string,
): HistoricalEligibilityReason {
  const reason = record(value, label);
  if (!Array.isArray(reason.eligibility_codes)) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_REASON_CODES_INVALID:${label}`,
    );
  }
  const codes = reason.eligibility_codes.map((code, index) =>
    stringValue(code, `${label}.eligibility_codes[${index}]`),
  );
  if (codes.length === 0 || codes.length > 32) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_REASON_CODES_BOUND_INVALID:${label}`,
    );
  }
  if (!Array.isArray(reason.source_columns)) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_SOURCE_COLUMNS_INVALID:${label}`,
    );
  }
  const sourceColumns = reason.source_columns.map((column, index) =>
    stringValue(column, `${label}.source_columns[${index}]`),
  );
  if (
    booleanValue(
      reason.per_condition_evaluation_in_source,
      `${label}.per_condition_evaluation_in_source`,
    ) !== false
  ) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_CONDITION_CLAIM_INVALID:${label}`,
    );
  }
  return {
    codes,
    conditionDefinitionsRef: stringValue(
      reason.condition_definitions_ref,
      `${label}.condition_definitions_ref`,
    ),
    eligibilityReason: stringValue(
      reason.eligibility_reason,
      `${label}.eligibility_reason`,
    ),
    perConditionEvaluationInSource: false,
    sourceColumns,
  };
}

export function normalizeRuleConditions(
  values: readonly unknown[],
  label = "conditions",
): HistoricalRuleCondition[] {
  if (values.length > 64) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_CONDITIONS_OVER_BOUND:${label}`,
    );
  }
  return values.map((value, index) => {
    const condition = record(value, `${label}[${index}]`);
    const feature = condition.feature ?? condition.property;
    return {
      availableAt:
        condition.available_at == null
          ? null
          : stringValue(
              condition.available_at,
              `${label}[${index}].available_at`,
            ),
      feature: stringValue(feature, `${label}[${index}].feature`),
      operator: stringValue(
        condition.operator,
        `${label}[${index}].operator`,
      ),
      source:
        condition.source == null
          ? null
          : stringValue(condition.source, `${label}[${index}].source`),
      value: condition.value,
    };
  });
}

export function normalizeHistoricalMembershipItem(
  item: HistoricalMembershipItem,
  label: string,
): HistoricalMembershipRow {
  const membership = record(item.membership, `${label}.membership`);
  const canonicalMatchId = canonicalMatchIdValue(
    item.canonical_match_id,
    `${label}.canonical_match_id`,
  );
  const matchDetailRef = stringValue(
    item.match_detail_ref,
    `${label}.match_detail_ref`,
  );
  if (!DETAIL_REF.test(matchDetailRef)) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_DETAIL_REF_INVALID:${label}`,
    );
  }
  const observedOdds = finiteNumber(
    membership.observed_odds,
    `${label}.membership.observed_odds`,
  );
  const marketMargin = finiteNumber(
    membership.market_margin,
    `${label}.membership.market_margin`,
  );
  if (observedOdds <= 1 || marketMargin < 0 || marketMargin > 1) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_PRICE_INVALID:${label}`,
    );
  }
  const stakeUnits = finiteNumber(
    membership.stake_units,
    `${label}.membership.stake_units`,
  );
  const grossReturnUnits = finiteNumber(
    membership.gross_return_units,
    `${label}.membership.gross_return_units`,
  );
  if (stakeUnits < 0 || grossReturnUnits < 0) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_UNITS_INVALID:${label}`,
    );
  }
  return {
    canonicalMatchId,
    chronologicalFold: stringValue(
      membership.chronological_fold,
      `${label}.membership.chronological_fold`,
    ),
    cumulativeProfitUnits: finiteNumber(
      membership.cumulative_profit_units,
      `${label}.membership.cumulative_profit_units`,
    ),
    fixture: normalizeHistoricalFixture(item.fixture, `${label}.fixture`),
    grossReturnUnits,
    market: stringValue(
      membership.market,
      `${label}.membership.market`,
    ),
    marketMargin,
    matchDetailRef,
    membershipHash: hashValue(
      membership.membership_hash,
      `${label}.membership.membership_hash`,
    ),
    observedOdds,
    observedTimeStatus: stringValue(
      membership.observed_time_status,
      `${label}.membership.observed_time_status`,
    ),
    occurrenceIndex: positiveInteger(
      membership.occurrence_index,
      `${label}.membership.occurrence_index`,
    ),
    outcome: outcomeValue(membership, `${label}.membership`),
    priceClass: stringValue(
      membership.price_class,
      `${label}.membership.price_class`,
    ),
    profitUnits: finiteNumber(
      membership.profit_units,
      `${label}.membership.profit_units`,
    ),
    reason: normalizeReason(item.reason, `${label}.reason`),
    selection: stringValue(
      membership.selection,
      `${label}.membership.selection`,
    ),
    stakeUnits,
    statisticalGroup: stringValue(
      membership.statistical_group,
      `${label}.membership.statistical_group`,
    ),
  };
}

export function normalizeHistoricalMembershipPage(
  page: HistoricalMembershipPage,
): {
  conditions: HistoricalRuleCondition[];
  rows: HistoricalMembershipRow[];
} {
  const expectedOrdering = [
    "OCCURRENCE_INDEX_ASC",
    "CANONICAL_MATCH_ID_ASC",
  ];
  if (
    page.ordering.length !== expectedOrdering.length ||
    page.ordering.some(
      (value, index) => value !== expectedOrdering[index],
    )
  ) {
    throw new HistoricalEvidenceContractError(
      "HISTORICAL_EVIDENCE_ORDERING_INVALID",
    );
  }
  const startIndex = (page.page - 1) * page.page_size + 1;
  const rows = page.items.map((item, index) =>
    normalizeHistoricalMembershipItem(
      item,
      `membership_page.items[${index}]`,
    ),
  );
  rows.forEach((row, index) => {
    if (row.occurrenceIndex !== startIndex + index) {
      throw new HistoricalEvidenceContractError(
        "HISTORICAL_EVIDENCE_OCCURRENCE_ORDER_INVALID",
      );
    }
  });
  return {
    conditions: normalizeRuleConditions(page.condition_definitions),
    rows,
  };
}

function normalizeMembershipPageRef(
  value: unknown,
  hypothesisId: string,
  label: string,
): HistoricalHypothesisRelation["membershipPageRefs"][number] {
  const pageRef = record(value, label);
  const pageSize = finiteNumber(pageRef.page_size, `${label}.page_size`);
  if (!isExperiencePageSize(pageSize)) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_PAGE_SIZE_INVALID:${label}`,
    );
  }
  const page = positiveInteger(pageRef.page, `${label}.page`);
  const itemIndex = nonNegativeInteger(
    pageRef.item_index,
    `${label}.item_index`,
  );
  if (itemIndex >= pageSize) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_ITEM_INDEX_INVALID:${label}`,
    );
  }
  const path = stringValue(pageRef.path, `${label}.path`);
  const expected =
    `hypotheses/${hypothesisId}/memberships/${pageSize}/` +
    `page-${String(page).padStart(4, "0")}.json`;
  if (path !== expected) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_PAGE_REF_INVALID:${label}`,
    );
  }
  return { itemIndex, page, pageSize, path };
}

function normalizeRelation(
  value: unknown,
  label: string,
): HistoricalHypothesisRelation {
  const relation = record(value, label);
  const hypothesisId = hypothesisIdValue(
    relation.hypothesis_id,
    `${label}.hypothesis_id`,
  );
  const membership = record(
    relation.membership,
    `${label}.membership`,
  );
  const observedOdds = finiteNumber(
    membership.observed_odds,
    `${label}.membership.observed_odds`,
  );
  const marketMargin = finiteNumber(
    membership.market_margin,
    `${label}.membership.market_margin`,
  );
  if (observedOdds <= 1 || marketMargin < 0 || marketMargin > 1) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_RELATION_PRICE_INVALID:${label}`,
    );
  }
  if (!Array.isArray(relation.membership_page_refs)) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_PAGE_REFS_INVALID:${label}`,
    );
  }
  const membershipPageRefs = relation.membership_page_refs.map(
    (pageRef, index) =>
      normalizeMembershipPageRef(
        pageRef,
        hypothesisId,
        `${label}.membership_page_refs[${index}]`,
      ),
  );
  if (
    membershipPageRefs.length !== 2 ||
    !membershipPageRefs.some((item) => item.pageSize === 25) ||
    !membershipPageRefs.some((item) => item.pageSize === 50)
  ) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_PAGE_REFS_BOUND_INVALID:${label}`,
    );
  }
  const summaryRef = stringValue(
    relation.summary_ref,
    `${label}.summary_ref`,
  );
  if (summaryRef !== `hypotheses/${hypothesisId}/summary.json`) {
    throw new HistoricalEvidenceContractError(
      `HISTORICAL_EVIDENCE_SUMMARY_REF_INVALID:${label}`,
    );
  }
  return {
    hypothesisId,
    membership: {
      market: stringValue(
        membership.market,
        `${label}.membership.market`,
      ),
      marketMargin,
      membershipHash: hashValue(
        membership.membership_hash,
        `${label}.membership.membership_hash`,
      ),
      observedOdds,
      outcome: outcomeValue(membership, `${label}.membership`),
      profitUnits: finiteNumber(
        membership.profit_units,
        `${label}.membership.profit_units`,
      ),
      selection: stringValue(
        membership.selection,
        `${label}.membership.selection`,
      ),
    },
    membershipPageRefs,
    reason: normalizeReason(relation.reason, `${label}.reason`),
    ruleHash: hashValue(relation.rule_hash, `${label}.rule_hash`),
    summaryRef,
  };
}

export function normalizeHistoricalMatchDetail(
  detail: HistoricalMatchDetail,
): NormalizedHistoricalMatchDetail {
  const canonicalMatchId = canonicalMatchIdValue(
    detail.canonical_match_id,
  );
  const source = record(detail.source_reference, "source_reference");
  const relations = detail.top_ten_hypotheses.map((relation, index) =>
    normalizeRelation(relation, `top_ten_hypotheses[${index}]`),
  );
  const totalHistoricalRules = positiveInteger(
    detail.total_historical_rules,
    "total_historical_rules",
  );
  const seen = new Set<string>();
  for (const relation of relations) {
    if (seen.has(relation.hypothesisId)) {
      throw new HistoricalEvidenceContractError(
        "HISTORICAL_EVIDENCE_RELATION_DUPLICATE",
      );
    }
    seen.add(relation.hypothesisId);
  }
  if (relations.length === 0) {
    throw new HistoricalEvidenceContractError(
      "HISTORICAL_EVIDENCE_RELATIONS_EMPTY",
    );
  }
  if (totalHistoricalRules < relations.length) {
    throw new HistoricalEvidenceContractError(
      "HISTORICAL_EVIDENCE_RULE_COUNT_INVALID",
    );
  }
  return {
    canonicalMatchId,
    fixture: normalizeHistoricalFixture(detail.fixture, "fixture"),
    relations,
    source: {
      datasetHash: hashValue(source.dataset_hash, "source.dataset_hash"),
      observedTimeStatus: stringValue(
        source.observed_time_status,
        "source.observed_time_status",
      ),
      source: stringValue(source.source, "source.source"),
      sourceRowHash: hashValue(
        source.source_row_hash,
        "source.source_row_hash",
      ),
    },
    totalHistoricalRules,
  };
}

function normalizedSearch(value: string): string {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLocaleLowerCase("fr-FR");
}

export function historicalFoldLabel(value: string): string {
  const season = /^SEASON:(.+)$/iu.exec(value.trim());
  if (season?.[1]) return `Saison ${season[1].trim()}`;
  const localizedSeason = /^SAISON\s*:?\s*(.+)$/iu.exec(value.trim());
  if (localizedSeason?.[1]) {
    return `Saison ${localizedSeason[1].trim()}`;
  }
  return "Période chronologique documentée";
}

function historicalFoldComparisonKey(value: string): string {
  const season = /^(?:SEASON:|SAISON\s*:?\s*)(.+)$/iu.exec(
    value.trim(),
  );
  return season?.[1]
    ? `season:${normalizedSearch(season[1].trim())}`
    : normalizedSearch(value);
}

function matchesOddsBand(
  odds: number,
  band: HistoricalOddsBand,
): boolean {
  if (band === "all") return true;
  if (band === "under-1.60") return odds < 1.6;
  if (band === "1.60-2.00") return odds >= 1.6 && odds < 2;
  if (band === "2.00-2.50") return odds >= 2 && odds < 2.5;
  if (band === "2.50-3.25") return odds >= 2.5 && odds <= 3.25;
  return odds > 3.25;
}

function compareRows(
  left: HistoricalMatchListRow,
  right: HistoricalMatchListRow,
  query: HistoricalMatchListQuery,
): number {
  let comparison = 0;
  switch (query.sort) {
    case "date-asc":
      comparison = left.fixture.kickoffTimestamp - right.fixture.kickoffTimestamp;
      break;
    case "date-desc":
      comparison = right.fixture.kickoffTimestamp - left.fixture.kickoffTimestamp;
      break;
    case "odds-asc":
      comparison = left.observedOdds - right.observedOdds;
      break;
    case "odds-desc":
      comparison = right.observedOdds - left.observedOdds;
      break;
    case "profit-asc":
      comparison = left.profitUnits - right.profitUnits;
      break;
    case "profit-desc":
      comparison = right.profitUnits - left.profitUnits;
      break;
    case "outcome": {
      const order = { lost: 2, void: 1, won: 0 } as const;
      comparison = order[left.outcome] - order[right.outcome];
      break;
    }
  }
  return (
    comparison ||
    left.fixture.kickoffTimestamp - right.fixture.kickoffTimestamp ||
    left.canonicalMatchId.localeCompare(right.canonicalMatchId, "en")
  );
}

export function filterAndSortHistoricalMemberships(
  rows: readonly HistoricalMatchListRow[],
  query: HistoricalMatchListQuery,
): HistoricalMatchListRow[] {
  const team = normalizedSearch(query.team);
  return rows
    .filter((row) => {
      const fixture = row.fixture;
      return (
        (query.season === null ||
          normalizedSearch(fixture.season) ===
            normalizedSearch(query.season)) &&
        (team === "" ||
          normalizedSearch(fixture.homeTeam.name).includes(team) ||
          normalizedSearch(fixture.awayTeam.name).includes(team) ||
          normalizedSearch(fixture.homeTeam.id) === team ||
          normalizedSearch(fixture.awayTeam.id) === team) &&
        (query.outcome === "all" || row.outcome === query.outcome) &&
        (query.selection === "all" ||
          row.selection === query.selection) &&
        matchesOddsBand(row.observedOdds, query.oddsBand) &&
        (query.fold === null ||
          historicalFoldComparisonKey(row.chronologicalFold) ===
            historicalFoldComparisonKey(query.fold))
      );
    })
    .sort((left, right) => compareRows(left, right, query));
}

export function historicalMembershipToListRow(
  row: HistoricalMembershipRow,
): HistoricalMatchListRow {
  return {
    canonicalMatchId: row.canonicalMatchId,
    chronologicalFold: row.chronologicalFold,
    cumulativeProfitUnits: row.cumulativeProfitUnits,
    fixture: row.fixture,
    marketMargin: row.marketMargin,
    matchDetailRef: row.matchDetailRef,
    observedOdds: row.observedOdds,
    occurrenceIndex: row.occurrenceIndex,
    outcome: row.outcome,
    profitUnits: row.profitUnits,
    selection: row.selection,
  };
}

export function historicalMatchListPath(
  hypothesisId: string,
  query?: HistoricalMatchListQuery,
): string {
  const validId = hypothesisIdValue(hypothesisId, "hypothesis_id");
  const pathname = `/hypotheses/${validId}/matchs`;
  if (!query) return pathname;
  const search = serializeHistoricalMatchListQuery(query).toString();
  return search ? `${pathname}?${search}` : pathname;
}

export function historicalMatchDetailPath(
  canonicalMatchId: string,
  context?: Readonly<{
    hypothesisId?: string | null;
    returnTo?: string | null;
  }>,
): string {
  const validMatchId = canonicalMatchIdValue(canonicalMatchId);
  const params = new URLSearchParams();
  if (context?.hypothesisId) {
    params.set(
      "hypothese",
      hypothesisIdValue(context.hypothesisId, "hypothesis_id"),
    );
  }
  if (context?.returnTo) params.set("retour", context.returnTo);
  const query = canonicalizeSearchParams(params).toString();
  const pathname = `/matchs/historique/${encodeURIComponent(validMatchId)}`;
  return query ? `${pathname}?${query}` : pathname;
}

export function parseHistoricalMatchContext(
  input: SearchParamInput,
): Readonly<{
  hypothesisId: string | null;
  returnTo: string | null;
}> {
  const rawHypothesis = cleanText(
    firstValue(input, "hypothese"),
    128,
  );
  const hypothesisId =
    rawHypothesis !== null && HYPOTHESIS_ID.test(rawHypothesis)
      ? rawHypothesis
      : null;
  const rawReturn = firstValue(input, "retour");
  const returnTo =
    typeof rawReturn === "string" && rawReturn.length <= 1_500
      ? rawReturn
      : null;
  return { hypothesisId, returnTo };
}

export function safeHistoricalReturnPath(
  candidate: string | null,
  hypothesisId: string,
): string {
  const fallback = historicalMatchListPath(hypothesisId);
  if (!candidate) return fallback;
  try {
    const parsed = new URL(candidate, "https://robin.invalid");
    if (
      parsed.origin !== "https://robin.invalid" ||
      parsed.hash !== "" ||
      parsed.pathname !== fallback
    ) {
      return fallback;
    }
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return fallback;
  }
}
