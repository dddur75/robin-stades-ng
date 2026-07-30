import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import {
  historicalEvidenceOriginFromHeaders,
  loadHistoricalMatchDetailPage,
  loadHistoricalMatchListPage,
} from "../app/lib/historical-match-evidence.server";
import {
  filterAndSortHistoricalMemberships,
  historicalFoldLabel,
  historicalMatchDetailPath,
  historicalMatchListNeedsFullScan,
  historicalMatchListPath,
  historicalMembershipToListRow,
  normalizeHistoricalMembershipPage,
  parseHistoricalMatchContext,
  parseHistoricalMatchListQuery,
  safeHistoricalReturnPath,
  serializeHistoricalMatchListQuery,
} from "../app/lib/historical-match-evidence";

const hypothesisId = "J10-M002";
const otherHypothesisId = "J10-M099";
const ruleHash = "1".repeat(64);
const otherRuleHash = "2".repeat(64);
const datasetHash = "3".repeat(64);

function detailRef(canonicalMatchId: string): string {
  return `matches/${createHash("sha256").update(canonicalMatchId).digest("hex")}.json`;
}

function fixture(index: number) {
  const matchDate = `2024-01-${String(index).padStart(2, "0")}`;
  return {
    away_team: { id: `A${index}`, name: `Extérieur ${index}` },
    competition: "Serie A",
    competition_key: "api-football:135",
    final_score: { away: index % 2, home: (index + 1) % 3 },
    final_status: "RESULT_RECORDED",
    home_team: { id: `H${index}`, name: `Domicile ${index}` },
    kickoff_at: `${matchDate}T19:45:00+00:00`,
    match_date: matchDate,
    round: null,
    season: 2024,
  };
}

function membershipItem(
  index: number,
  {
    outcome = index % 2 === 0 ? "won" : "lost",
    targetHypothesisId = hypothesisId,
  }: {
    outcome?: "lost" | "void" | "won";
    targetHypothesisId?: string;
  } = {},
) {
  const canonicalMatchId = `api-football:${100 + index}`;
  const won = outcome === "won";
  const lost = outcome === "lost";
  const voided = outcome === "void";
  const profit = won ? 2.1 : lost ? -1 : 0;
  return {
    canonical_match_id: canonicalMatchId,
    evidence_kind: "HISTORICAL",
    fixture: fixture(index),
    match_detail_ref: detailRef(canonicalMatchId),
    membership: {
      chronological_fold: "SEASON:2024",
      cumulative_profit_units: index === 1 ? -1 : index - 2,
      gross_return_units: won ? 3.1 : voided ? 1 : 0,
      lost,
      market: "1X2_DRAW",
      market_margin: 0.05,
      membership_hash: createHash("sha256")
        .update(`${targetHypothesisId}:${canonicalMatchId}`)
        .digest("hex"),
      observed_odds: 2.8 + index / 10,
      observed_time_status: "SOURCE_PRICE_CLASS_ONLY",
      occurrence_index: index,
      price_class: "HISTORICAL_CLOSING_MARKET",
      profit_units: profit,
      selection: "DRAW",
      stake_units: 1,
      statistical_group: `2024-01-${String(index).padStart(2, "0")}`,
      void: voided,
      won,
    },
    reason: {
      condition_definitions_ref:
        `hypotheses/${targetHypothesisId}/summary.json`,
      eligibility_codes: [
        "ALL_CONDITIONS_MATCH",
        "OBSERVED_ODDS_ELIGIBLE",
        "OUTCOME_SETTLED",
      ],
      eligibility_reason:
        "ALL_CONDITIONS_MATCH;OBSERVED_ODDS_ELIGIBLE;OUTCOME_SETTLED",
      per_condition_evaluation_in_source: false,
      source_columns: [
        "hypothesis_fixture_membership.eligibility_reason",
        "hypothesis_historical_evidence_summary.conditions_json",
      ],
    },
  } as const;
}

const conditions = [
  {
    available_at: "FIXTURE_PUBLICATION",
    feature: "competition",
    operator: "EQ",
    source: "API_FOOTBALL_FIXTURE",
    value: "Serie A",
  },
  {
    available_at: "HISTORICAL_PRICE_CATEGORY",
    feature: "odds_draw",
    operator: "BETWEEN",
    source: "FOOTBALL_DATA",
    value: [2.5, 3.25],
  },
];

function summary(
  targetHypothesisId = hypothesisId,
  targetRuleHash = ruleHash,
  rank: number | null = 2,
) {
  return {
    analysis_ref: `hypotheses/${targetHypothesisId}/analysis.json`,
    conditions,
    evidence_availability: {
      historical: { available: true },
      prospective: { available: false },
    },
    historical_summary: { occurrences: 3 },
    hypothesis_id: targetHypothesisId,
    membership_pages: { "25": {}, "50": {} },
    provenance: { dataset_hash: datasetHash },
    query_index_ref:
      `hypotheses/${targetHypothesisId}/query-index.json`,
    rank,
    rule_hash: targetRuleHash,
    schema_version: "hypothesis-evidence-site-summary-v1",
  } as const;
}

function membershipPage() {
  return {
    condition_definitions: conditions,
    evidence_kind: "HISTORICAL",
    hypothesis_id: hypothesisId,
    items: [
      membershipItem(1),
      membershipItem(2),
      membershipItem(3, { outcome: "won" }),
    ],
    ordering: ["OCCURRENCE_INDEX_ASC", "CANONICAL_MATCH_ID_ASC"],
    page: 1,
    page_size: 25,
    prospective_evidence_included: false,
    rule_hash: ruleHash,
    schema_version: "hypothesis-evidence-membership-page-v1",
    summary_ref: `hypotheses/${hypothesisId}/summary.json`,
    total_items: 3,
    total_pages: 1,
  } as const;
}

function queryIndexItem(index: number, outcome: "lost" | "void" | "won") {
  const item = membershipItem(index, { outcome });
  return {
    ...item.fixture,
    canonical_match_id: item.canonical_match_id,
    chronological_fold: item.membership.chronological_fold,
    cumulative_profit_units: item.membership.cumulative_profit_units,
    market: item.membership.market,
    market_margin: item.membership.market_margin,
    match_detail_ref: item.match_detail_ref,
    observed_odds: item.membership.observed_odds,
    occurrence_index: index,
    outcome,
    profit_units: item.membership.profit_units,
    selection: item.membership.selection,
  };
}

function queryIndex() {
  return {
    evidence_kind: "HISTORICAL",
    hypothesis_id: hypothesisId,
    items: [
      queryIndexItem(1, "lost"),
      queryIndexItem(2, "won"),
      queryIndexItem(3, "won"),
    ],
    maximum_items: 2_000,
    ordering: ["OCCURRENCE_INDEX_ASC", "CANONICAL_MATCH_ID_ASC"],
    prospective_evidence_included: false,
    provenance: { provider_payloads_copied: false },
    rule_hash: ruleHash,
    schema_version: "hypothesis-evidence-query-index-v1",
    intended_consumer: "SERVER_RENDERED_MATCH_LIST",
    transport: "PUBLIC_SAME_ORIGIN_STATIC_ASSET",
    summary_ref: `hypotheses/${hypothesisId}/summary.json`,
    supported_filters: [
      "chronological_fold",
      "observed_odds",
      "outcome",
      "season",
      "selection",
      "team",
    ],
    supported_page_sizes: [25, 50],
    supported_sorts: [
      "kickoff_at",
      "observed_odds",
      "outcome",
      "profit_units",
    ],
    total_items: 3,
  } as const;
}

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    headers: { "content-type": "application/json" },
    status: 200,
  });
}

function mappedFetcher(
  payloads: ReadonlyMap<string, unknown>,
  calls: string[],
): typeof fetch {
  return async (input) => {
    const url = String(input);
    calls.push(url);
    const payload = payloads.get(url);
    return payload === undefined
      ? new Response("missing", { status: 404 })
      : jsonResponse(payload);
  };
}

test("les paramètres historiques sont bornés, canoniques et déclenchent l’index global", () => {
  const query = parseHistoricalMatchListQuery(
    new URLSearchParams(
      "taille=50&page=99999&saison=2024&equipe=  Inter   Milan  &resultat=won&selection=DRAW&cotes=2.50-3.25&periodE=ignored&periode=SEASON%3A2024&tri=profit-desc",
    ),
  );
  assert.deepEqual(query, {
    fold: "SEASON:2024",
    oddsBand: "2.50-3.25",
    outcome: "won",
    page: 10_000,
    pageSize: 50,
    season: "2024",
    selection: "DRAW",
    sort: "profit-desc",
    team: "Inter Milan",
  });
  assert.equal(historicalMatchListNeedsFullScan(query), true);
  assert.equal(
    serializeHistoricalMatchListQuery(query).toString(),
    "cotes=2.50-3.25&equipe=Inter+Milan&page=10000&periode=SEASON%3A2024&resultat=won&saison=2024&selection=DRAW&taille=50&tri=profit-desc",
  );
  assert.equal(
    historicalMatchListNeedsFullScan(
      parseHistoricalMatchListQuery(new URLSearchParams()),
    ),
    false,
  );
});

test("les liens de détail et de retour refusent les sorties de périmètre", () => {
  const context = parseHistoricalMatchContext({
    hypothese: hypothesisId,
    retour: `/hypotheses/${hypothesisId}/matchs?resultat=won`,
  });
  assert.equal(context.hypothesisId, hypothesisId);
  assert.equal(
    historicalMatchDetailPath("api-football:101", {
      hypothesisId,
      returnTo: context.returnTo,
    }),
    `/matchs/historique/api-football%3A101?hypothese=${hypothesisId}&retour=%2Fhypotheses%2F${hypothesisId}%2Fmatchs%3Fresultat%3Dwon`,
  );
  assert.equal(
    safeHistoricalReturnPath("https://evil.example/", hypothesisId),
    historicalMatchListPath(hypothesisId),
  );
  assert.equal(
    safeHistoricalReturnPath(
      `/hypotheses/${hypothesisId}/matchs?resultat=won`,
      hypothesisId,
    ),
    `/hypotheses/${hypothesisId}/matchs?resultat=won`,
  );
});

test("la normalisation conserve les colonnes et applique filtres et tris globalement", () => {
  const normalized = normalizeHistoricalMembershipPage(membershipPage());
  const rows = normalized.rows.map(historicalMembershipToListRow);
  const query = parseHistoricalMatchListQuery(
    new URLSearchParams(
      "resultat=won&selection=DRAW&cotes=2.50-3.25&tri=profit-desc",
    ),
  );
  const filtered = filterAndSortHistoricalMemberships(rows, query);
  assert.deepEqual(
    filtered.map((row) => row.canonicalMatchId),
    ["api-football:102", "api-football:103"],
  );
  assert.equal(filtered[0]?.marketMargin, 0.05);
  assert.equal(filtered[0]?.cumulativeProfitUnits, 0);
  assert.equal(historicalFoldLabel("SEASON:2020"), "Saison 2020");
  const localizedFold = filterAndSortHistoricalMemberships(
    rows,
    parseHistoricalMatchListQuery(
      new URLSearchParams("periode=Saison+2024"),
    ),
  );
  assert.equal(localizedFold.length, 3);
});

test("la lecture chronologique ne charge que le shard demandé", async () => {
  const calls: string[] = [];
  const payloads = new Map<string, unknown>([
    [
      `/data/hypothesis-evidence/hypotheses/${hypothesisId}/summary.json`,
      summary(hypothesisId, ruleHash, null),
    ],
    [
      `/data/hypothesis-evidence/hypotheses/${hypothesisId}/memberships/25/page-0001.json`,
      membershipPage(),
    ],
  ]);
  const data = await loadHistoricalMatchListPage(
    hypothesisId,
    parseHistoricalMatchListQuery(new URLSearchParams()),
    { fetcher: mappedFetcher(payloads, calls) },
  );
  assert.equal(data.rows.length, 3);
  assert.equal(data.scan.mode, "chronological-shard");
  assert.equal(data.scan.assetsLoaded, 1);
  assert.equal(data.hypothesis.rank, null);
  assert.ok(calls.every((url) => !url.endsWith("/query-index.json")));
});

test("un filtre global charge uniquement le query-index serveur puis rend la tranche", async () => {
  const calls: string[] = [];
  const payloads = new Map<string, unknown>([
    [
      `/data/hypothesis-evidence/hypotheses/${hypothesisId}/summary.json`,
      summary(),
    ],
    [
      `/data/hypothesis-evidence/hypotheses/${hypothesisId}/query-index.json`,
      queryIndex(),
    ],
  ]);
  const data = await loadHistoricalMatchListPage(
    hypothesisId,
    parseHistoricalMatchListQuery(
      new URLSearchParams("resultat=won&tri=profit-desc"),
    ),
    { fetcher: mappedFetcher(payloads, calls) },
  );
  assert.equal(data.scan.mode, "query-index");
  assert.equal(data.scan.assetsLoaded, 1);
  assert.deepEqual(
    data.rows.map((row) => row.canonicalMatchId),
    ["api-football:102", "api-football:103"],
  );
  assert.equal(data.pagination.totalItems, 2);
  assert.ok(calls.every((url) => !url.includes("/memberships/")));
});

test("la fiche historique vérifie le contexte et fournit précédent/suivant", async () => {
  const page = membershipPage();
  const current = page.items[1];
  const otherMembership = membershipItem(2, {
    outcome: "won",
    targetHypothesisId: otherHypothesisId,
  });
  const matchDetail = {
    canonical_match_id: current.canonical_match_id,
    evidence_kind: "HISTORICAL",
    fixture: current.fixture,
    prospective_evidence_included: false,
    schema_version: "hypothesis-evidence-historical-match-v1",
    source_reference: {
      dataset_hash: datasetHash,
      observed_time_status: "SOURCE_PRICE_CLASS_ONLY",
      source: "FOOTBALL_DATA",
      source_row_hash: "4".repeat(64),
    },
    total_historical_rules: 70,
    top_ten_hypotheses: [
      {
        hypothesis_id: hypothesisId,
        membership: {
          lost: current.membership.lost,
          market: current.membership.market,
          market_margin: current.membership.market_margin,
          membership_hash: current.membership.membership_hash,
          observed_odds: current.membership.observed_odds,
          profit_units: current.membership.profit_units,
          selection: current.membership.selection,
          void: current.membership.void,
          won: current.membership.won,
        },
        membership_page_refs: [
          {
            item_index: 1,
            page: 1,
            page_size: 25,
            path:
              `hypotheses/${hypothesisId}/memberships/25/page-0001.json`,
          },
          {
            item_index: 1,
            page: 1,
            page_size: 50,
            path:
              `hypotheses/${hypothesisId}/memberships/50/page-0001.json`,
          },
        ],
        reason: current.reason,
        rule_hash: ruleHash,
        summary_ref: `hypotheses/${hypothesisId}/summary.json`,
      },
      {
        hypothesis_id: otherHypothesisId,
        membership: {
          lost: otherMembership.membership.lost,
          market: otherMembership.membership.market,
          market_margin: otherMembership.membership.market_margin,
          membership_hash: otherMembership.membership.membership_hash,
          observed_odds: otherMembership.membership.observed_odds,
          profit_units: otherMembership.membership.profit_units,
          selection: otherMembership.membership.selection,
          void: otherMembership.membership.void,
          won: otherMembership.membership.won,
        },
        membership_page_refs: [
          {
            item_index: 1,
            page: 1,
            page_size: 25,
            path:
              `hypotheses/${otherHypothesisId}/memberships/25/page-0001.json`,
          },
          {
            item_index: 1,
            page: 1,
            page_size: 50,
            path:
              `hypotheses/${otherHypothesisId}/memberships/50/page-0001.json`,
          },
        ],
        reason: {
          ...otherMembership.reason,
          condition_definitions_ref:
            `hypotheses/${otherHypothesisId}/summary.json`,
        },
        rule_hash: otherRuleHash,
        summary_ref:
          `hypotheses/${otherHypothesisId}/summary.json`,
      },
    ],
  } as const;
  const calls: string[] = [];
  const payloads = new Map<string, unknown>([
    [
      `/data/hypothesis-evidence/${detailRef(current.canonical_match_id)}`,
      matchDetail,
    ],
    [
      `/data/hypothesis-evidence/hypotheses/${hypothesisId}/summary.json`,
      summary(),
    ],
    [
      `/data/hypothesis-evidence/hypotheses/${hypothesisId}/memberships/25/page-0001.json`,
      page,
    ],
  ]);
  const returnTo =
    `/hypotheses/${hypothesisId}/matchs?resultat=won`;
  const data = await loadHistoricalMatchDetailPage(
    current.canonical_match_id,
    { hypothesisId, returnTo },
    { fetcher: mappedFetcher(payloads, calls) },
  );
  assert.equal(data.activeRelation.hypothesisId, hypothesisId);
  assert.equal(data.detail.totalHistoricalRules, 70);
  assert.equal(data.navigation.previous?.canonicalMatchId, "api-football:101");
  assert.equal(data.navigation.next?.canonicalMatchId, "api-football:103");
  assert.equal(data.navigation.previousHypothesis, null);
  assert.equal(
    data.navigation.nextHypothesis?.hypothesisId,
    otherHypothesisId,
  );
  assert.equal(data.otherRelations[0]?.hypothesisId, otherHypothesisId);
  assert.equal(data.returnTo, returnTo);
  assert.equal(data.conditions.length, 2);
  assert.equal(calls.length, 3);
});

test("l’origine SSR refuse les hôtes ambigus", () => {
  assert.equal(
    historicalEvidenceOriginFromHeaders(
      new Headers({ host: "localhost:3000" }),
    ),
    "http://localhost:3000",
  );
  assert.throws(
    () =>
      historicalEvidenceOriginFromHeaders(
        new Headers({ host: "preview.example/path" }),
      ),
    /HISTORICAL_EVIDENCE_REQUEST_HOST_INVALID/u,
  );
});
