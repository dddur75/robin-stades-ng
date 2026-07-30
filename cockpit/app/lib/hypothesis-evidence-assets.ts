const ASSET_BASE = "/data/hypothesis-evidence";
const HYPOTHESIS_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const MATCH_DETAIL_REF_PATTERN = /^matches\/[0-9a-f]{64}\.json$/;
const MAX_PAGE = 10_000;
const MAX_PUBLISHED_HYPOTHESES = 32;
const MAX_QUERY_INDEX_ITEMS = 2_000;
const MAX_MATCH_DETAIL_BYTES = 64 * 1024;

export type EvidencePageSize = 25 | 50;

export type EvidenceIndexItem = Readonly<{
  historical_occurrences: number;
  hypothesis_id: string;
  prospective_evidence_included: false;
  rank: number | null;
  rule_hash: string;
  summary_ref: string;
}>;

export type EvidenceIndex = Readonly<{
  evidence_availability: Readonly<{
    historical: true;
    prospective: false;
  }>;
  hypotheses: readonly EvidenceIndexItem[];
  match_index_ref: string;
  maximum_hypotheses: number;
  preview_scope: "RANKING_TOP_TEN_UNION";
  ranking_source: string;
  schema_version: "hypothesis-evidence-site-index-v1";
}>;

export type HypothesisEvidenceSummary = Readonly<{
  analysis_ref: string;
  conditions: readonly unknown[];
  evidence_availability: Readonly<{
    historical: Readonly<Record<string, unknown>>;
    prospective: Readonly<Record<string, unknown>>;
  }>;
  historical_summary: Readonly<Record<string, unknown>>;
  hypothesis_id: string;
  membership_pages: Readonly<Record<`${EvidencePageSize}`, unknown>>;
  provenance: Readonly<Record<string, unknown>>;
  query_index_ref: string;
  rank: number | null;
  rule_hash: string;
  schema_version: "hypothesis-evidence-site-summary-v1";
}>;

export type HypothesisEvidenceAnalysisMatchReference = Readonly<{
  canonical_match_id: string;
  match_date: string;
  match_detail_ref: string;
  match_label: string;
}>;

export type HypothesisEvidenceAnalysisBankrollPoint =
  HypothesisEvidenceAnalysisMatchReference &
    Readonly<{
      cumulative_profit_units: number;
      occurrence_index: number;
    }>;

export type HypothesisEvidenceAnalysis = Readonly<{
  bankroll_points: readonly HypothesisEvidenceAnalysisBankrollPoint[];
  evidence_kind: "HISTORICAL";
  folds: readonly Readonly<Record<string, unknown>>[];
  hypothesis_id: string;
  odds_bands: readonly Readonly<Record<string, unknown>>[];
  prospective_evidence_included: false;
  provenance: Readonly<Record<string, unknown>>;
  rule_hash: string;
  schema_version: "hypothesis-evidence-analysis-v1";
  seasons: readonly Readonly<Record<string, unknown>>[];
  streaks: Readonly<Record<string, unknown>>;
  team_concentration: Readonly<Record<string, unknown>>;
}>;

export type HypothesisEvidenceQueryIndexItem = Readonly<{
  away_team: Readonly<{ id: string; name: string }>;
  canonical_match_id: string;
  chronological_fold: string;
  competition: string;
  competition_key: string;
  cumulative_profit_units: number;
  final_score: Readonly<{ away: number; home: number }>;
  final_status: string;
  home_team: Readonly<{ id: string; name: string }>;
  kickoff_at: string;
  market: string;
  market_margin: number;
  match_date: string;
  match_detail_ref: string;
  observed_odds: number;
  occurrence_index: number;
  outcome: "lost" | "void" | "won";
  profit_units: number;
  round: number | string | null;
  season: number | string;
  selection: string;
}>;

export type HypothesisEvidenceQueryIndex = Readonly<{
  evidence_kind: "HISTORICAL";
  hypothesis_id: string;
  intended_consumer: "SERVER_RENDERED_MATCH_LIST";
  items: readonly HypothesisEvidenceQueryIndexItem[];
  maximum_items: 2_000;
  ordering: readonly [
    "OCCURRENCE_INDEX_ASC",
    "CANONICAL_MATCH_ID_ASC",
  ];
  prospective_evidence_included: false;
  provenance: Readonly<Record<string, unknown>>;
  rule_hash: string;
  schema_version: "hypothesis-evidence-query-index-v1";
  summary_ref: string;
  supported_filters: readonly [
    "chronological_fold",
    "observed_odds",
    "outcome",
    "season",
    "selection",
    "team",
  ];
  supported_page_sizes: readonly [25, 50];
  supported_sorts: readonly [
    "kickoff_at",
    "observed_odds",
    "outcome",
    "profit_units",
  ];
  total_items: number;
  transport: "PUBLIC_SAME_ORIGIN_STATIC_ASSET";
}>;

export type HistoricalMembershipItem = Readonly<{
  canonical_match_id: string;
  evidence_kind: "HISTORICAL";
  fixture: Readonly<Record<string, unknown>>;
  match_detail_ref: string;
  membership: Readonly<Record<string, unknown>>;
  reason: Readonly<Record<string, unknown>>;
}>;

export type HistoricalMembershipPage = Readonly<{
  condition_definitions: readonly unknown[];
  evidence_kind: "HISTORICAL";
  hypothesis_id: string;
  items: readonly HistoricalMembershipItem[];
  ordering: readonly string[];
  page: number;
  page_size: EvidencePageSize;
  prospective_evidence_included: false;
  rule_hash: string;
  schema_version: "hypothesis-evidence-membership-page-v1";
  summary_ref: string;
  total_items: number;
  total_pages: number;
}>;

export type HistoricalMatchDetail = Readonly<{
  canonical_match_id: string;
  evidence_kind: "HISTORICAL";
  fixture: Readonly<Record<string, unknown>>;
  prospective_evidence_included: false;
  schema_version: "hypothesis-evidence-historical-match-v1";
  source_reference: Readonly<Record<string, unknown>>;
  total_historical_rules: number;
  top_ten_hypotheses: readonly Readonly<Record<string, unknown>>[];
}>;

export type EvidenceAssetLoaderOptions = Readonly<{
  baseUrl?: string | URL;
  fetcher?: typeof fetch;
  signal?: AbortSignal;
}>;

export class EvidenceAssetError extends Error {
  readonly code: string;

  constructor(code: string, options?: ErrorOptions) {
    super(code, options);
    this.name = "EvidenceAssetError";
    this.code = code;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isGlobalRoiRank(value: unknown): value is number | null {
  return (
    value === null ||
    (Number.isInteger(value) && Number(value) >= 1 && Number(value) <= 10)
  );
}

function requireHypothesisId(hypothesisId: string): string {
  if (!HYPOTHESIS_ID_PATTERN.test(hypothesisId)) {
    throw new EvidenceAssetError("EVIDENCE_HYPOTHESIS_ID_INVALID");
  }
  return hypothesisId;
}

function requirePageSize(pageSize: number): EvidencePageSize {
  if (pageSize !== 25 && pageSize !== 50) {
    throw new EvidenceAssetError("EVIDENCE_PAGE_SIZE_INVALID");
  }
  return pageSize;
}

function requirePage(page: number): number {
  if (!Number.isInteger(page) || page < 1 || page > MAX_PAGE) {
    throw new EvidenceAssetError("EVIDENCE_PAGE_INVALID");
  }
  return page;
}

function requireMatchDetailRef(detailRef: string): string {
  if (!MATCH_DETAIL_REF_PATTERN.test(detailRef)) {
    throw new EvidenceAssetError("EVIDENCE_MATCH_DETAIL_REF_INVALID");
  }
  return detailRef;
}

export function hypothesisEvidenceIndexUrl(): string {
  return `${ASSET_BASE}/index.json`;
}

export function hypothesisEvidenceSummaryUrl(hypothesisId: string): string {
  return `${ASSET_BASE}/hypotheses/${requireHypothesisId(hypothesisId)}/summary.json`;
}

export function hypothesisEvidenceAnalysisUrl(hypothesisId: string): string {
  return `${ASSET_BASE}/hypotheses/${requireHypothesisId(hypothesisId)}/analysis.json`;
}

export function hypothesisEvidenceQueryIndexUrl(
  hypothesisId: string,
): string {
  return `${ASSET_BASE}/hypotheses/${requireHypothesisId(hypothesisId)}/query-index.json`;
}

export function hypothesisEvidenceMembershipPageUrl(
  hypothesisId: string,
  pageSize: number,
  page: number,
): string {
  return (
    `${ASSET_BASE}/hypotheses/${requireHypothesisId(hypothesisId)}` +
    `/memberships/${requirePageSize(pageSize)}` +
    `/page-${String(requirePage(page)).padStart(4, "0")}.json`
  );
}

export function hypothesisEvidenceMatchDetailUrl(detailRef: string): string {
  return `${ASSET_BASE}/${requireMatchDetailRef(detailRef)}`;
}

async function fetchJsonAsset(
  url: string,
  maximumBytes: number,
  options: EvidenceAssetLoaderOptions,
): Promise<unknown> {
  const fetcher = options.fetcher ?? globalThis.fetch;
  if (typeof fetcher !== "function") {
    throw new EvidenceAssetError("EVIDENCE_FETCH_UNAVAILABLE");
  }

  let response: Response;
  const requestUrl =
    options.baseUrl === undefined
      ? url
      : new URL(url, options.baseUrl).toString();
  try {
    response = await fetcher(requestUrl, {
      cache: "force-cache",
      headers: { Accept: "application/json" },
      signal: options.signal,
    });
  } catch (error) {
    throw new EvidenceAssetError("EVIDENCE_ASSET_REQUEST_FAILED", {
      cause: error,
    });
  }
  if (!response.ok) {
    throw new EvidenceAssetError(
      response.status === 404
        ? "EVIDENCE_ASSET_NOT_FOUND"
        : "EVIDENCE_ASSET_HTTP_ERROR",
    );
  }

  const declaredLength = response.headers.get("content-length");
  if (
    declaredLength !== null &&
    Number.isFinite(Number(declaredLength)) &&
    Number(declaredLength) > maximumBytes
  ) {
    throw new EvidenceAssetError("EVIDENCE_ASSET_TOO_LARGE");
  }
  const text = await response.text();
  if (new TextEncoder().encode(text).byteLength > maximumBytes) {
    throw new EvidenceAssetError("EVIDENCE_ASSET_TOO_LARGE");
  }
  try {
    return JSON.parse(text) as unknown;
  } catch (error) {
    throw new EvidenceAssetError("EVIDENCE_ASSET_JSON_INVALID", {
      cause: error,
    });
  }
}

function assertIndex(value: unknown): asserts value is EvidenceIndex {
  if (
    !isRecord(value) ||
    value.schema_version !== "hypothesis-evidence-site-index-v1" ||
    value.preview_scope !== "RANKING_TOP_TEN_UNION" ||
    !Number.isInteger(value.maximum_hypotheses) ||
    Number(value.maximum_hypotheses) < 0 ||
    Number(value.maximum_hypotheses) > MAX_PUBLISHED_HYPOTHESES ||
    !Array.isArray(value.hypotheses) ||
    value.hypotheses.length !== value.maximum_hypotheses ||
    !isRecord(value.evidence_availability) ||
    value.evidence_availability.historical !== true ||
    value.evidence_availability.prospective !== false
  ) {
    throw new EvidenceAssetError("EVIDENCE_INDEX_CONTRACT_INVALID");
  }
  const seen = new Set<string>();
  for (const item of value.hypotheses) {
    if (
      !isRecord(item) ||
      typeof item.hypothesis_id !== "string" ||
      !HYPOTHESIS_ID_PATTERN.test(item.hypothesis_id) ||
      typeof item.rule_hash !== "string" ||
      !/^[0-9a-f]{64}$/.test(item.rule_hash) ||
      !isGlobalRoiRank(item.rank) ||
      typeof item.historical_occurrences !== "number" ||
      item.historical_occurrences < 0 ||
      item.prospective_evidence_included !== false ||
      item.summary_ref !==
        `hypotheses/${item.hypothesis_id}/summary.json` ||
      seen.has(item.hypothesis_id)
    ) {
      throw new EvidenceAssetError("EVIDENCE_INDEX_ITEM_INVALID");
    }
    seen.add(item.hypothesis_id);
  }
}

function assertSummary(
  value: unknown,
  hypothesisId: string,
): asserts value is HypothesisEvidenceSummary {
  if (
    !isRecord(value) ||
    value.schema_version !== "hypothesis-evidence-site-summary-v1" ||
    value.hypothesis_id !== hypothesisId ||
    value.analysis_ref !== `hypotheses/${hypothesisId}/analysis.json` ||
    value.query_index_ref !==
      `hypotheses/${hypothesisId}/query-index.json` ||
    typeof value.rule_hash !== "string" ||
    !/^[0-9a-f]{64}$/.test(value.rule_hash) ||
    !isGlobalRoiRank(value.rank) ||
    !Array.isArray(value.conditions) ||
    !isRecord(value.historical_summary) ||
    !isRecord(value.membership_pages) ||
    !isRecord(value.provenance) ||
    !isRecord(value.evidence_availability) ||
    !isRecord(value.evidence_availability.historical) ||
    !isRecord(value.evidence_availability.prospective) ||
    value.evidence_availability.historical.available !== true ||
    value.evidence_availability.prospective.available !== false
  ) {
    throw new EvidenceAssetError("EVIDENCE_SUMMARY_CONTRACT_INVALID");
  }
}

function matchesExactArray(
  value: unknown,
  expected: readonly unknown[],
): boolean {
  return (
    Array.isArray(value) &&
    value.length === expected.length &&
    value.every((item, index) => item === expected[index])
  );
}

function assertQueryIndex(
  value: unknown,
  hypothesisId: string,
): asserts value is HypothesisEvidenceQueryIndex {
  if (
    !isRecord(value) ||
    value.schema_version !== "hypothesis-evidence-query-index-v1" ||
    value.evidence_kind !== "HISTORICAL" ||
    value.prospective_evidence_included !== false ||
    value.intended_consumer !== "SERVER_RENDERED_MATCH_LIST" ||
    value.transport !== "PUBLIC_SAME_ORIGIN_STATIC_ASSET" ||
    value.hypothesis_id !== hypothesisId ||
    typeof value.rule_hash !== "string" ||
    !/^[0-9a-f]{64}$/.test(value.rule_hash) ||
    value.summary_ref !== `hypotheses/${hypothesisId}/summary.json` ||
    value.maximum_items !== MAX_QUERY_INDEX_ITEMS ||
    !Number.isInteger(value.total_items) ||
    Number(value.total_items) < 0 ||
    !matchesExactArray(value.ordering, [
      "OCCURRENCE_INDEX_ASC",
      "CANONICAL_MATCH_ID_ASC",
    ]) ||
    !matchesExactArray(value.supported_page_sizes, [25, 50]) ||
    !matchesExactArray(value.supported_filters, [
      "chronological_fold",
      "observed_odds",
      "outcome",
      "season",
      "selection",
      "team",
    ]) ||
    !matchesExactArray(value.supported_sorts, [
      "kickoff_at",
      "observed_odds",
      "outcome",
      "profit_units",
    ]) ||
    !Array.isArray(value.items) ||
    value.items.length !== value.total_items ||
    value.items.length > MAX_QUERY_INDEX_ITEMS ||
    !isRecord(value.provenance) ||
    value.provenance.provider_payloads_copied !== false
  ) {
    throw new EvidenceAssetError("EVIDENCE_QUERY_INDEX_CONTRACT_INVALID");
  }

  const matchIds = new Set<string>();
  value.items.forEach((item, index) => {
    if (
      !isRecord(item) ||
      typeof item.canonical_match_id !== "string" ||
      item.canonical_match_id.length < 1 ||
      item.canonical_match_id.length > 512 ||
      matchIds.has(item.canonical_match_id) ||
      typeof item.match_detail_ref !== "string" ||
      !MATCH_DETAIL_REF_PATTERN.test(item.match_detail_ref) ||
      item.occurrence_index !== index + 1 ||
      typeof item.kickoff_at !== "string" ||
      typeof item.match_date !== "string" ||
      !/^\d{4}-\d{2}-\d{2}$/.test(item.match_date) ||
      typeof item.competition !== "string" ||
      typeof item.competition_key !== "string" ||
      typeof item.cumulative_profit_units !== "number" ||
      !Number.isFinite(item.cumulative_profit_units) ||
      !(
        typeof item.season === "string" ||
        (typeof item.season === "number" &&
          Number.isFinite(item.season))
      ) ||
      !(
        item.round === null ||
        typeof item.round === "string" ||
        (typeof item.round === "number" && Number.isFinite(item.round))
      ) ||
      !isRecord(item.home_team) ||
      typeof item.home_team.id !== "string" ||
      typeof item.home_team.name !== "string" ||
      !isRecord(item.away_team) ||
      typeof item.away_team.id !== "string" ||
      typeof item.away_team.name !== "string" ||
      !isRecord(item.final_score) ||
      typeof item.final_score.home !== "number" ||
      !Number.isFinite(item.final_score.home) ||
      typeof item.final_score.away !== "number" ||
      !Number.isFinite(item.final_score.away) ||
      typeof item.final_status !== "string" ||
      typeof item.chronological_fold !== "string" ||
      typeof item.market !== "string" ||
      typeof item.market_margin !== "number" ||
      !Number.isFinite(item.market_margin) ||
      item.market_margin < 0 ||
      item.market_margin > 1 ||
      typeof item.selection !== "string" ||
      typeof item.observed_odds !== "number" ||
      !Number.isFinite(item.observed_odds) ||
      item.observed_odds <= 1 ||
      !["lost", "void", "won"].includes(String(item.outcome)) ||
      typeof item.profit_units !== "number" ||
      !Number.isFinite(item.profit_units)
    ) {
      throw new EvidenceAssetError("EVIDENCE_QUERY_INDEX_ITEM_INVALID");
    }
    matchIds.add(item.canonical_match_id);
  });
}

function assertAnalysis(
  value: unknown,
  hypothesisId: string,
): asserts value is HypothesisEvidenceAnalysis {
  if (
    !isRecord(value) ||
    value.schema_version !== "hypothesis-evidence-analysis-v1" ||
    value.evidence_kind !== "HISTORICAL" ||
    value.prospective_evidence_included !== false ||
    value.hypothesis_id !== hypothesisId ||
    typeof value.rule_hash !== "string" ||
    !/^[0-9a-f]{64}$/.test(value.rule_hash) ||
    !Array.isArray(value.bankroll_points) ||
    value.bankroll_points.length > MAX_PAGE ||
    !Array.isArray(value.seasons) ||
    !Array.isArray(value.odds_bands) ||
    !Array.isArray(value.folds) ||
    !isRecord(value.team_concentration) ||
    !Array.isArray(value.team_concentration.items) ||
    value.team_concentration.items.length > 10 ||
    !isRecord(value.streaks) ||
    !Array.isArray(value.streaks.runs) ||
    !isRecord(value.provenance)
  ) {
    throw new EvidenceAssetError("EVIDENCE_ANALYSIS_CONTRACT_INVALID");
  }
  const matchIds = new Set<string>();
  for (const point of value.bankroll_points) {
    if (
      !isRecord(point) ||
      typeof point.canonical_match_id !== "string" ||
      point.canonical_match_id.length < 1 ||
      point.canonical_match_id.length > 512 ||
      matchIds.has(point.canonical_match_id) ||
      typeof point.match_date !== "string" ||
      !/^\d{4}-\d{2}-\d{2}$/.test(point.match_date) ||
      typeof point.match_label !== "string" ||
      point.match_label.length < 1 ||
      point.match_label.length > 512 ||
      !Number.isInteger(point.occurrence_index) ||
      Number(point.occurrence_index) < 1 ||
      typeof point.cumulative_profit_units !== "number" ||
      !Number.isFinite(point.cumulative_profit_units) ||
      typeof point.match_detail_ref !== "string" ||
      !MATCH_DETAIL_REF_PATTERN.test(point.match_detail_ref)
    ) {
      throw new EvidenceAssetError("EVIDENCE_ANALYSIS_BANKROLL_INVALID");
    }
    matchIds.add(point.canonical_match_id);
  }
  value.team_concentration.items.forEach((item, index) => {
    if (
      !isRecord(item) ||
      item.rank !== index + 1 ||
      typeof item.team_id !== "string" ||
      item.team_id.length === 0 ||
      typeof item.team_name !== "string" ||
      item.team_name.length === 0 ||
      !Number.isInteger(item.occurrences) ||
      Number(item.occurrences) < 1 ||
      !Number.isInteger(item.home_occurrences) ||
      Number(item.home_occurrences) < 0 ||
      !Number.isInteger(item.away_occurrences) ||
      Number(item.away_occurrences) < 0 ||
      Number(item.home_occurrences) + Number(item.away_occurrences) !==
        Number(item.occurrences) ||
      !Number.isInteger(item.wins) ||
      Number(item.wins) < 0 ||
      !Number.isInteger(item.losses) ||
      Number(item.losses) < 0 ||
      !Number.isInteger(item.voids) ||
      Number(item.voids) < 0 ||
      Number(item.wins) + Number(item.losses) + Number(item.voids) !==
        Number(item.occurrences) ||
      typeof item.profit_units !== "number" ||
      !Number.isFinite(item.profit_units) ||
      typeof item.share_of_team_appearances !== "number" ||
      !Number.isFinite(item.share_of_team_appearances) ||
      item.share_of_team_appearances < 0 ||
      item.share_of_team_appearances > 1 ||
      !isRecord(item.reference_match) ||
      typeof item.reference_match.match_label !== "string" ||
      item.reference_match.match_label.length < 1 ||
      item.reference_match.match_label.length > 512
    ) {
      throw new EvidenceAssetError(
        "EVIDENCE_ANALYSIS_TEAM_CONCENTRATION_INVALID",
      );
    }
  });
}

function assertMembershipPage(
  value: unknown,
  hypothesisId: string,
  pageSize: EvidencePageSize,
  page: number,
): asserts value is HistoricalMembershipPage {
  if (
    !isRecord(value) ||
    value.schema_version !== "hypothesis-evidence-membership-page-v1" ||
    value.evidence_kind !== "HISTORICAL" ||
    value.prospective_evidence_included !== false ||
    value.hypothesis_id !== hypothesisId ||
    value.page_size !== pageSize ||
    value.page !== page ||
    typeof value.total_pages !== "number" ||
    !Number.isInteger(value.total_pages) ||
    value.total_pages < 1 ||
    typeof value.total_items !== "number" ||
    !Number.isInteger(value.total_items) ||
    value.total_items < 0 ||
    !Array.isArray(value.items) ||
    value.items.length > pageSize ||
    !Array.isArray(value.condition_definitions) ||
    !Array.isArray(value.ordering)
  ) {
    throw new EvidenceAssetError("EVIDENCE_MEMBERSHIP_PAGE_CONTRACT_INVALID");
  }
  for (const item of value.items) {
    if (
      !isRecord(item) ||
      item.evidence_kind !== "HISTORICAL" ||
      typeof item.canonical_match_id !== "string" ||
      typeof item.match_detail_ref !== "string" ||
      !MATCH_DETAIL_REF_PATTERN.test(item.match_detail_ref) ||
      !isRecord(item.fixture) ||
      !isRecord(item.membership) ||
      !isRecord(item.reason)
    ) {
      throw new EvidenceAssetError("EVIDENCE_MEMBERSHIP_ITEM_INVALID");
    }
  }
}

function assertMatchDetail(value: unknown): asserts value is HistoricalMatchDetail {
  if (
    !isRecord(value) ||
    value.schema_version !== "hypothesis-evidence-historical-match-v1" ||
    value.evidence_kind !== "HISTORICAL" ||
    value.prospective_evidence_included !== false ||
    typeof value.canonical_match_id !== "string" ||
    !isRecord(value.fixture) ||
    !isRecord(value.source_reference) ||
    !Number.isInteger(value.total_historical_rules) ||
    Number(value.total_historical_rules) < 1 ||
    !Array.isArray(value.top_ten_hypotheses) ||
    value.top_ten_hypotheses.length > MAX_PUBLISHED_HYPOTHESES ||
    value.top_ten_hypotheses.length >
      Number(value.total_historical_rules) ||
    value.top_ten_hypotheses.some((item) => !isRecord(item))
  ) {
    throw new EvidenceAssetError("EVIDENCE_MATCH_DETAIL_CONTRACT_INVALID");
  }
}

export async function loadHypothesisEvidenceIndex(
  options: EvidenceAssetLoaderOptions = {},
): Promise<EvidenceIndex> {
  const value = await fetchJsonAsset(
    hypothesisEvidenceIndexUrl(),
    32 * 1024,
    options,
  );
  assertIndex(value);
  return value;
}

export async function loadHypothesisEvidenceSummary(
  hypothesisId: string,
  options: EvidenceAssetLoaderOptions = {},
): Promise<HypothesisEvidenceSummary> {
  const validId = requireHypothesisId(hypothesisId);
  const value = await fetchJsonAsset(
    hypothesisEvidenceSummaryUrl(validId),
    32 * 1024,
    options,
  );
  assertSummary(value, validId);
  return value;
}

export async function loadHypothesisEvidenceAnalysis(
  hypothesisId: string,
  options: EvidenceAssetLoaderOptions = {},
): Promise<HypothesisEvidenceAnalysis> {
  const validId = requireHypothesisId(hypothesisId);
  const value = await fetchJsonAsset(
    hypothesisEvidenceAnalysisUrl(validId),
    768 * 1024,
    options,
  );
  assertAnalysis(value, validId);
  return value;
}

/**
 * Charge l'index compact destiné au filtrage/tri SSR. Ne transmettez jamais
 * l'objet complet à un composant client : ne rendez que la tranche 25/50.
 */
export async function loadHypothesisEvidenceQueryIndex(
  hypothesisId: string,
  options: EvidenceAssetLoaderOptions = {},
): Promise<HypothesisEvidenceQueryIndex> {
  const validId = requireHypothesisId(hypothesisId);
  const value = await fetchJsonAsset(
    hypothesisEvidenceQueryIndexUrl(validId),
    2 * 1024 * 1024,
    options,
  );
  assertQueryIndex(value, validId);
  return value;
}

export async function loadHypothesisEvidenceMembershipPage(
  hypothesisId: string,
  pageSize: number,
  page: number,
  options: EvidenceAssetLoaderOptions = {},
): Promise<HistoricalMembershipPage> {
  const validId = requireHypothesisId(hypothesisId);
  const validPageSize = requirePageSize(pageSize);
  const validPage = requirePage(page);
  const value = await fetchJsonAsset(
    hypothesisEvidenceMembershipPageUrl(
      validId,
      validPageSize,
      validPage,
    ),
    160 * 1024,
    options,
  );
  assertMembershipPage(value, validId, validPageSize, validPage);
  return value;
}

export async function loadHypothesisEvidenceMatchDetail(
  detailRef: string,
  options: EvidenceAssetLoaderOptions = {},
): Promise<HistoricalMatchDetail> {
  const validRef = requireMatchDetailRef(detailRef);
  const value = await fetchJsonAsset(
    hypothesisEvidenceMatchDetailUrl(validRef),
    MAX_MATCH_DETAIL_BYTES,
    options,
  );
  assertMatchDetail(value);
  return value;
}
