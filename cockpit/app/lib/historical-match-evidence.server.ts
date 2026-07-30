import type { PaginationContract } from "./contracts/experience-v12";
import {
  EvidenceAssetError,
  loadHypothesisEvidenceMatchDetail,
  loadHypothesisEvidenceMembershipPage,
  loadHypothesisEvidenceQueryIndex,
  loadHypothesisEvidenceSummary,
  type EvidenceAssetLoaderOptions,
  type HistoricalMembershipPage,
  type HypothesisEvidenceSummary,
  type HypothesisEvidenceQueryIndex,
  type HypothesisEvidenceQueryIndexItem,
} from "./hypothesis-evidence-assets";
import {
  canonicalMatchIdValue,
  filterAndSortHistoricalMemberships,
  historicalMembershipToListRow,
  historicalMatchListNeedsFullScan,
  historicalMatchListPath,
  normalizeHistoricalMatchDetail,
  normalizeHistoricalFixture,
  normalizeHistoricalMembershipPage,
  normalizeRuleConditions,
  safeHistoricalReturnPath,
  HistoricalEvidenceContractError,
  type HistoricalHypothesisRelation,
  type HistoricalMatchListQuery,
  type HistoricalMatchListRow,
  type HistoricalMembershipRow,
  type HistoricalRuleCondition,
  type NormalizedHistoricalMatchDetail,
} from "./historical-match-evidence";
import { createPaginationContract } from "./query-params";

export const MAX_QUERY_INDEX_ITEMS = 2_000;

export type HistoricalMatchListPageData = Readonly<{
  conditions: readonly HistoricalRuleCondition[];
  hypothesis: Readonly<{
    hypothesisId: string;
    rank: number | null;
    ruleHash: string;
  }>;
  pagination: PaginationContract;
  rows: readonly HistoricalMatchListRow[];
  scan: Readonly<{
    assetsLoaded: number;
    fullyScanned: boolean;
    maximumAssets: number;
    maximumItems: typeof MAX_QUERY_INDEX_ITEMS;
    mode: "chronological-shard" | "query-index";
  }>;
  sourceTotalItems: number;
}>;

export type HistoricalAdjacentMatch = Readonly<{
  canonicalMatchId: string;
  kickoffAt: string;
  label: string;
}>;

export type HistoricalAdjacentHypothesis = Readonly<{
  hypothesisId: string;
}>;

export type HistoricalMatchDetailPageData = Readonly<{
  activeRelation: HistoricalHypothesisRelation;
  conditions: readonly HistoricalRuleCondition[];
  contextRequestedButUnavailable: boolean;
  detail: NormalizedHistoricalMatchDetail;
  navigation: Readonly<{
    next: HistoricalAdjacentMatch | null;
    nextHypothesis: HistoricalAdjacentHypothesis | null;
    previous: HistoricalAdjacentMatch | null;
    previousHypothesis: HistoricalAdjacentHypothesis | null;
  }>;
  otherRelations: readonly HistoricalHypothesisRelation[];
  returnTo: string;
}>;

export class HistoricalEvidencePageError extends Error {
  readonly code: string;

  constructor(code: string, options?: ErrorOptions) {
    super(code, options);
    this.name = "HistoricalEvidencePageError";
    this.code = code;
  }
}

function pageError(code: string): never {
  throw new HistoricalEvidencePageError(code);
}

function validateSummary(
  summary: HypothesisEvidenceSummary,
): {
  conditions: HistoricalRuleCondition[];
  occurrences: number;
} {
  if (
    summary.rank !== null &&
    (!Number.isInteger(summary.rank) || summary.rank < 1)
  ) {
    pageError("HISTORICAL_EVIDENCE_SUMMARY_RANK_INVALID");
  }
  const occurrences = summary.historical_summary.occurrences;
  if (
    typeof occurrences !== "number" ||
    !Number.isInteger(occurrences) ||
    occurrences < 1
  ) {
    pageError("HISTORICAL_EVIDENCE_SUMMARY_OCCURRENCES_INVALID");
  }
  return {
    conditions: normalizeRuleConditions(
      summary.conditions,
      "summary.conditions",
    ),
    occurrences,
  };
}

function validatePageEnvelope(
  page: HistoricalMembershipPage,
  summary: HypothesisEvidenceSummary,
  expectedPage: number,
): void {
  if (
    page.hypothesis_id !== summary.hypothesis_id ||
    page.rule_hash !== summary.rule_hash ||
    page.page !== expectedPage
  ) {
    pageError("HISTORICAL_EVIDENCE_PAGE_SUMMARY_RELATION_INVALID");
  }
  const expectedPages = Math.max(
    1,
    Math.ceil(page.total_items / page.page_size),
  );
  if (page.total_pages !== expectedPages) {
    pageError("HISTORICAL_EVIDENCE_TOTAL_PAGES_INVALID");
  }
  const expectedItems =
    page.page === page.total_pages
      ? page.total_items - (page.page - 1) * page.page_size
      : page.page_size;
  if (
    expectedItems < 0 ||
    page.items.length !== expectedItems ||
    page.page > page.total_pages
  ) {
    pageError("HISTORICAL_EVIDENCE_PAGE_CARDINALITY_INVALID");
  }
}

function validateSameCollection(
  page: HistoricalMembershipPage,
  first: HistoricalMembershipPage,
): void {
  if (
    page.hypothesis_id !== first.hypothesis_id ||
    page.rule_hash !== first.rule_hash ||
    page.page_size !== first.page_size ||
    page.total_items !== first.total_items ||
    page.total_pages !== first.total_pages ||
    JSON.stringify(page.condition_definitions) !==
      JSON.stringify(first.condition_definitions) ||
    JSON.stringify(page.ordering) !== JSON.stringify(first.ordering)
  ) {
    pageError("HISTORICAL_EVIDENCE_PAGE_COLLECTION_INVALID");
  }
}

async function detailRefForCanonicalMatchId(
  canonicalMatchId: string,
): Promise<string> {
  const validId = canonicalMatchIdValue(canonicalMatchId);
  if (
    typeof globalThis.crypto !== "object" ||
    typeof globalThis.crypto.subtle !== "object"
  ) {
    pageError("HISTORICAL_EVIDENCE_DIGEST_UNAVAILABLE");
  }
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(validId),
  );
  const hash = [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  return `matches/${hash}.json`;
}

async function validateDisplayedDetailRefs(
  rows: readonly HistoricalMatchListRow[],
): Promise<void> {
  const expected = await Promise.all(
    rows.map((row) => detailRefForCanonicalMatchId(row.canonicalMatchId)),
  );
  expected.forEach((detailRef, index) => {
    if (detailRef !== rows[index]?.matchDetailRef) {
      pageError("HISTORICAL_EVIDENCE_DETAIL_LINK_INVALID");
    }
  });
}

export async function loadHistoricalMatchListPage(
  hypothesisId: string,
  query: HistoricalMatchListQuery,
  options: EvidenceAssetLoaderOptions,
): Promise<HistoricalMatchListPageData> {
  if (historicalMatchListNeedsFullScan(query)) {
    return loadHistoricalMatchListFromQueryIndex(
      hypothesisId,
      query,
      options,
    );
  }

  const [summary, firstPage] = await Promise.all([
    loadHypothesisEvidenceSummary(hypothesisId, options),
    loadHypothesisEvidenceMembershipPage(
      hypothesisId,
      query.pageSize,
      1,
      options,
    ),
  ]);
  const normalizedSummary = validateSummary(summary);
  validatePageEnvelope(firstPage, summary, 1);
  if (
    firstPage.total_items !== normalizedSummary.occurrences ||
    firstPage.total_items > MAX_QUERY_INDEX_ITEMS
  ) {
    pageError("HISTORICAL_EVIDENCE_SUMMARY_TOTAL_INVALID");
  }

  const pagination = createPaginationContract(
    query.page,
    query.pageSize,
    firstPage.total_items,
  );
  const selectedPage =
    pagination.page === 1
      ? firstPage
      : await loadHypothesisEvidenceMembershipPage(
          hypothesisId,
          query.pageSize,
          pagination.page,
          options,
        );
  if (selectedPage !== firstPage) {
    validatePageEnvelope(selectedPage, summary, pagination.page);
    validateSameCollection(selectedPage, firstPage);
  }
  const normalized = normalizeHistoricalMembershipPage(selectedPage);
  const rows = normalized.rows.map(historicalMembershipToListRow);
  await validateDisplayedDetailRefs(rows);
  return {
    conditions: normalizedSummary.conditions,
    hypothesis: {
      hypothesisId: summary.hypothesis_id,
      rank: summary.rank,
      ruleHash: summary.rule_hash,
    },
    pagination,
    rows,
    scan: {
      assetsLoaded: pagination.page === 1 ? 1 : 2,
      fullyScanned: false,
      maximumAssets: 2,
      maximumItems: MAX_QUERY_INDEX_ITEMS,
      mode: "chronological-shard",
    },
    sourceTotalItems: firstPage.total_items,
  };
}

function queryIndexItemToListRow(
  item: HypothesisEvidenceQueryIndexItem,
): HistoricalMatchListRow {
  return {
    canonicalMatchId: canonicalMatchIdValue(item.canonical_match_id),
    chronologicalFold: item.chronological_fold,
    cumulativeProfitUnits: item.cumulative_profit_units,
    fixture: normalizeHistoricalFixture(
      {
        away_team: item.away_team,
        competition: item.competition,
        competition_key: item.competition_key,
        final_score: item.final_score,
        final_status: item.final_status,
        home_team: item.home_team,
        kickoff_at: item.kickoff_at,
        match_date: item.match_date,
        round: item.round,
        season: item.season,
      },
      `query_index.items[${item.occurrence_index - 1}].fixture`,
    ),
    marketMargin: item.market_margin,
    matchDetailRef: item.match_detail_ref,
    observedOdds: item.observed_odds,
    occurrenceIndex: item.occurrence_index,
    outcome: item.outcome,
    profitUnits: item.profit_units,
    selection: item.selection,
  };
}

function validateQueryIndexRelation(
  queryIndex: HypothesisEvidenceQueryIndex,
  summary: HypothesisEvidenceSummary,
  occurrences: number,
): void {
  if (
    queryIndex.hypothesis_id !== summary.hypothesis_id ||
    queryIndex.rule_hash !== summary.rule_hash ||
    queryIndex.summary_ref !==
      `hypotheses/${summary.hypothesis_id}/summary.json` ||
    summary.query_index_ref !==
      `hypotheses/${summary.hypothesis_id}/query-index.json` ||
    queryIndex.total_items !== occurrences ||
    queryIndex.items.length !== occurrences ||
    queryIndex.maximum_items !== MAX_QUERY_INDEX_ITEMS
  ) {
    pageError("HISTORICAL_EVIDENCE_QUERY_INDEX_RELATION_INVALID");
  }
}

async function loadHistoricalMatchListFromQueryIndex(
  hypothesisId: string,
  query: HistoricalMatchListQuery,
  options: EvidenceAssetLoaderOptions,
): Promise<HistoricalMatchListPageData> {
  const [summary, queryIndex] = await Promise.all([
    loadHypothesisEvidenceSummary(hypothesisId, options),
    loadHypothesisEvidenceQueryIndex(hypothesisId, options),
  ]);
  const normalizedSummary = validateSummary(summary);
  validateQueryIndexRelation(
    queryIndex,
    summary,
    normalizedSummary.occurrences,
  );
  const allRows = queryIndex.items.map(queryIndexItemToListRow);
  const filteredRows = filterAndSortHistoricalMemberships(allRows, query);
  const pagination = createPaginationContract(
    query.page,
    query.pageSize,
    filteredRows.length,
  );
  const start = (pagination.page - 1) * pagination.pageSize;
  const rows = filteredRows.slice(start, start + pagination.pageSize);
  await validateDisplayedDetailRefs(rows);
  return {
    conditions: normalizedSummary.conditions,
    hypothesis: {
      hypothesisId: summary.hypothesis_id,
      rank: summary.rank,
      ruleHash: summary.rule_hash,
    },
    pagination,
    rows,
    scan: {
      assetsLoaded: 1,
      fullyScanned: true,
      maximumAssets: 1,
      maximumItems: MAX_QUERY_INDEX_ITEMS,
      mode: "query-index",
    },
    sourceTotalItems: queryIndex.total_items,
  };
}

function fixtureLabel(row: HistoricalMembershipRow): string {
  return `${row.fixture.homeTeam.name} – ${row.fixture.awayTeam.name}`;
}

function adjacentMatch(
  row: HistoricalMembershipRow | undefined,
): HistoricalAdjacentMatch | null {
  return row
    ? {
        canonicalMatchId: row.canonicalMatchId,
        kickoffAt: row.fixture.kickoffAt,
        label: fixtureLabel(row),
      }
    : null;
}

function validateRelationAgainstRow(
  relation: HistoricalHypothesisRelation,
  row: HistoricalMembershipRow,
): void {
  if (
    relation.membership.membershipHash !== row.membershipHash ||
    relation.membership.market !== row.market ||
    relation.membership.selection !== row.selection ||
    relation.membership.outcome !== row.outcome ||
    relation.membership.observedOdds !== row.observedOdds ||
    relation.membership.marketMargin !== row.marketMargin ||
    relation.membership.profitUnits !== row.profitUnits
  ) {
    pageError("HISTORICAL_EVIDENCE_MATCH_RELATION_INVALID");
  }
}

function validateFixtureRelation(
  detail: NormalizedHistoricalMatchDetail,
  row: HistoricalMembershipRow,
): void {
  const fixture = detail.fixture;
  const rowFixture = row.fixture;
  if (
    fixture.kickoffAt !== rowFixture.kickoffAt ||
    fixture.competitionKey !== rowFixture.competitionKey ||
    fixture.homeTeam.id !== rowFixture.homeTeam.id ||
    fixture.awayTeam.id !== rowFixture.awayTeam.id ||
    fixture.finalScore.home !== rowFixture.finalScore.home ||
    fixture.finalScore.away !== rowFixture.finalScore.away
  ) {
    pageError("HISTORICAL_EVIDENCE_MATCH_FIXTURE_INVALID");
  }
}

async function loadAdjacentMatches(
  detail: NormalizedHistoricalMatchDetail,
  relation: HistoricalHypothesisRelation,
  summary: HypothesisEvidenceSummary,
  options: EvidenceAssetLoaderOptions,
): Promise<{
  next: HistoricalAdjacentMatch | null;
  previous: HistoricalAdjacentMatch | null;
}> {
  const pageRef = relation.membershipPageRefs.find(
    (item) => item.pageSize === 25,
  );
  if (!pageRef) pageError("HISTORICAL_EVIDENCE_NAVIGATION_REF_MISSING");

  const currentPage = await loadHypothesisEvidenceMembershipPage(
    relation.hypothesisId,
    pageRef.pageSize,
    pageRef.page,
    options,
  );
  validatePageEnvelope(currentPage, summary, pageRef.page);
  const currentRows = normalizeHistoricalMembershipPage(currentPage).rows;
  const currentRow = currentRows[pageRef.itemIndex];
  if (!currentRow || currentRow.canonicalMatchId !== detail.canonicalMatchId) {
    pageError("HISTORICAL_EVIDENCE_NAVIGATION_ANCHOR_INVALID");
  }
  validateRelationAgainstRow(relation, currentRow);
  validateFixtureRelation(detail, currentRow);

  let previous = adjacentMatch(currentRows[pageRef.itemIndex - 1]);
  let next = adjacentMatch(currentRows[pageRef.itemIndex + 1]);
  const requests: Promise<HistoricalMembershipPage>[] = [];
  const requestedKinds: ("previous" | "next")[] = [];
  if (previous === null && pageRef.page > 1) {
    requestedKinds.push("previous");
    requests.push(
      loadHypothesisEvidenceMembershipPage(
        relation.hypothesisId,
        pageRef.pageSize,
        pageRef.page - 1,
        options,
      ),
    );
  }
  if (next === null && pageRef.page < currentPage.total_pages) {
    requestedKinds.push("next");
    requests.push(
      loadHypothesisEvidenceMembershipPage(
        relation.hypothesisId,
        pageRef.pageSize,
        pageRef.page + 1,
        options,
      ),
    );
  }
  const boundaryPages = await Promise.all(requests);
  boundaryPages.forEach((page, index) => {
    validatePageEnvelope(page, summary, page.page);
    validateSameCollection(page, currentPage);
    const rows = normalizeHistoricalMembershipPage(page).rows;
    if (requestedKinds[index] === "previous") {
      previous = adjacentMatch(rows.at(-1));
    } else {
      next = adjacentMatch(rows[0]);
    }
  });
  return { next, previous };
}

export async function loadHistoricalMatchDetailPage(
  canonicalMatchId: string,
  context: Readonly<{
    hypothesisId: string | null;
    returnTo: string | null;
  }>,
  options: EvidenceAssetLoaderOptions,
): Promise<HistoricalMatchDetailPageData> {
  const validMatchId = canonicalMatchIdValue(canonicalMatchId);
  const detailRef = await detailRefForCanonicalMatchId(validMatchId);
  const rawDetail = await loadHypothesisEvidenceMatchDetail(
    detailRef,
    options,
  );
  const detail = normalizeHistoricalMatchDetail(rawDetail);
  if (detail.canonicalMatchId !== validMatchId) {
    pageError("HISTORICAL_EVIDENCE_MATCH_ID_RELATION_INVALID");
  }
  const requestedRelation = context.hypothesisId
    ? detail.relations.find(
        (relation) => relation.hypothesisId === context.hypothesisId,
      )
    : undefined;
  const activeRelation = requestedRelation ?? detail.relations[0];
  if (!activeRelation) {
    pageError("HISTORICAL_EVIDENCE_ACTIVE_RELATION_MISSING");
  }
  const summary = await loadHypothesisEvidenceSummary(
    activeRelation.hypothesisId,
    options,
  );
  const normalizedSummary = validateSummary(summary);
  if (
    summary.rule_hash !== activeRelation.ruleHash ||
    activeRelation.reason.conditionDefinitionsRef !==
      activeRelation.summaryRef
  ) {
    pageError("HISTORICAL_EVIDENCE_MATCH_SUMMARY_RELATION_INVALID");
  }
  const matchNavigation = await loadAdjacentMatches(
    detail,
    activeRelation,
    summary,
    options,
  );
  const activeRelationIndex = detail.relations.findIndex(
    (relation) => relation.hypothesisId === activeRelation.hypothesisId,
  );
  if (activeRelationIndex < 0) {
    pageError("HISTORICAL_EVIDENCE_ACTIVE_RELATION_INDEX_INVALID");
  }
  const previousHypothesis = detail.relations[activeRelationIndex - 1];
  const nextHypothesis = detail.relations[activeRelationIndex + 1];
  return {
    activeRelation,
    conditions: normalizedSummary.conditions,
    contextRequestedButUnavailable:
      context.hypothesisId !== null && requestedRelation === undefined,
    detail,
    navigation: {
      ...matchNavigation,
      nextHypothesis: nextHypothesis
        ? { hypothesisId: nextHypothesis.hypothesisId }
        : null,
      previousHypothesis: previousHypothesis
        ? { hypothesisId: previousHypothesis.hypothesisId }
        : null,
    },
    otherRelations: detail.relations.filter(
      (relation) => relation.hypothesisId !== activeRelation.hypothesisId,
    ),
    returnTo: safeHistoricalReturnPath(
      context.returnTo,
      activeRelation.hypothesisId,
    ),
  };
}

export function historicalEvidenceOriginFromHeaders(
  input: Pick<Headers, "get">,
): string {
  const host = (
    input.get("host") ??
    input.get("x-forwarded-host") ??
    ""
  )
    .split(",")[0]
    ?.trim();
  if (
    !host ||
    host.length > 255 ||
    /[\s/@\\]/u.test(host)
  ) {
    pageError("HISTORICAL_EVIDENCE_REQUEST_HOST_INVALID");
  }
  const forwardedProtocol = input
    .get("x-forwarded-proto")
    ?.split(",")[0]
    ?.trim()
    .toLocaleLowerCase("en");
  const localHost =
    host.startsWith("localhost") ||
    host.startsWith("127.0.0.1") ||
    host.startsWith("[::1]");
  const protocol = forwardedProtocol ?? (localHost ? "http" : "https");
  if (protocol !== "http" && protocol !== "https") {
    pageError("HISTORICAL_EVIDENCE_REQUEST_PROTOCOL_INVALID");
  }
  try {
    const origin = new URL(`${protocol}://${host}`);
    if (
      origin.username ||
      origin.password ||
      origin.pathname !== "/" ||
      origin.search ||
      origin.hash
    ) {
      pageError("HISTORICAL_EVIDENCE_REQUEST_ORIGIN_INVALID");
    }
    return origin.origin;
  } catch (error) {
    if (
      error instanceof HistoricalEvidencePageError ||
      error instanceof HistoricalEvidenceContractError ||
      error instanceof EvidenceAssetError
    ) {
      throw error;
    }
    throw new HistoricalEvidencePageError(
      "HISTORICAL_EVIDENCE_REQUEST_ORIGIN_INVALID",
      { cause: error },
    );
  }
}

export function isHistoricalEvidenceNotFound(error: unknown): boolean {
  return (
    error instanceof EvidenceAssetError &&
    (error.code === "EVIDENCE_ASSET_NOT_FOUND" ||
      error.code === "EVIDENCE_HYPOTHESIS_ID_INVALID" ||
      error.code === "EVIDENCE_MATCH_DETAIL_REF_INVALID")
  ) || (
    error instanceof HistoricalEvidenceContractError &&
    error.code.startsWith("HISTORICAL_EVIDENCE_MATCH_ID_INVALID")
  );
}

export function historicalEvidenceErrorCode(error: unknown): string {
  if (
    error instanceof EvidenceAssetError ||
    error instanceof HistoricalEvidencePageError ||
    error instanceof HistoricalEvidenceContractError
  ) {
    return error.code.split(":")[0] ?? "HISTORICAL_EVIDENCE_UNAVAILABLE";
  }
  return "HISTORICAL_EVIDENCE_UNAVAILABLE";
}

export function defaultHistoricalReturnPath(
  hypothesisId: string,
): string {
  return historicalMatchListPath(hypothesisId);
}
