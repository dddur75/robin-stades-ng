import assert from "node:assert/strict";
import test from "node:test";

import {
  EvidenceAssetError,
  hypothesisEvidenceAnalysisUrl,
  hypothesisEvidenceMatchDetailUrl,
  hypothesisEvidenceMembershipPageUrl,
  hypothesisEvidenceQueryIndexUrl,
  hypothesisEvidenceSummaryUrl,
  loadHypothesisEvidenceAnalysis,
  loadHypothesisEvidenceIndex,
  loadHypothesisEvidenceMatchDetail,
  loadHypothesisEvidenceMembershipPage,
  loadHypothesisEvidenceQueryIndex,
  loadHypothesisEvidenceSummary,
} from "../app/lib/hypothesis-evidence-assets";

const hypothesisId = "J10-M001";
const ruleHash = "1".repeat(64);
const matchRef = `matches/${"2".repeat(64)}.json`;

const indexPayload = {
  evidence_availability: { historical: true, prospective: false },
  hypotheses: [
    {
      historical_occurrences: 2,
      hypothesis_id: hypothesisId,
      prospective_evidence_included: false,
      rank: 1,
      rule_hash: ruleHash,
      summary_ref: `hypotheses/${hypothesisId}/summary.json`,
    },
  ],
  match_index_ref: "matches/index.json",
  maximum_hypotheses: 1,
  preview_scope: "RANKING_TOP_TEN_UNION",
  ranking_source: "global.by_roi.items",
  schema_version: "hypothesis-evidence-site-index-v1",
};

const summaryPayload = {
  analysis_ref: `hypotheses/${hypothesisId}/analysis.json`,
  conditions: [],
  evidence_availability: {
    historical: { available: true },
    prospective: { available: false },
  },
  historical_summary: { occurrences: 2 },
  hypothesis_id: hypothesisId,
  membership_pages: { "25": {}, "50": {} },
  provenance: { dataset_hash: "3".repeat(64) },
  query_index_ref: `hypotheses/${hypothesisId}/query-index.json`,
  rank: 1,
  rule_hash: ruleHash,
  schema_version: "hypothesis-evidence-site-summary-v1",
};

const analysisPayload = {
  bankroll_points: [
    {
      canonical_match_id: "api-football:123",
      cumulative_profit_units: 1,
      match_date: "2024-01-01",
      match_detail_ref: matchRef,
      match_label: "Home – Away",
      occurrence_index: 1,
    },
  ],
  evidence_kind: "HISTORICAL",
  folds: [],
  hypothesis_id: hypothesisId,
  odds_bands: [],
  prospective_evidence_included: false,
  provenance: {},
  rule_hash: ruleHash,
  schema_version: "hypothesis-evidence-analysis-v1",
  seasons: [],
  streaks: { runs: [] },
  team_concentration: { items: [] },
};

const queryIndexPayload = {
  evidence_kind: "HISTORICAL",
  hypothesis_id: hypothesisId,
  items: [
    {
      away_team: { id: "A1", name: "Away" },
      canonical_match_id: "api-football:123",
      chronological_fold: "SEASON:2024",
      competition: "Test League",
      competition_key: "TEST_LEAGUE",
      cumulative_profit_units: 1,
      final_score: { away: 1, home: 2 },
      final_status: "FT",
      home_team: { id: "H1", name: "Home" },
      kickoff_at: "2024-01-01T15:00:00+00:00",
      market: "MATCH_RESULT",
      market_margin: 0.05,
      match_date: "2024-01-01",
      match_detail_ref: matchRef,
      observed_odds: 2,
      occurrence_index: 1,
      outcome: "won",
      profit_units: 1,
      round: "Round 1",
      season: 2024,
      selection: "HOME",
    },
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
  total_items: 1,
};

const pagePayload = {
  condition_definitions: [],
  evidence_kind: "HISTORICAL",
  hypothesis_id: hypothesisId,
  items: [
    {
      canonical_match_id: "api-football:123",
      evidence_kind: "HISTORICAL",
      fixture: {},
      match_detail_ref: matchRef,
      membership: {},
      reason: {},
    },
  ],
  ordering: ["OCCURRENCE_INDEX_ASC"],
  page: 1,
  page_size: 25,
  prospective_evidence_included: false,
  rule_hash: ruleHash,
  schema_version: "hypothesis-evidence-membership-page-v1",
  summary_ref: `hypotheses/${hypothesisId}/summary.json`,
  total_items: 1,
  total_pages: 1,
};

const matchPayload = {
  canonical_match_id: "api-football:123",
  evidence_kind: "HISTORICAL",
  fixture: {},
  prospective_evidence_included: false,
  schema_version: "hypothesis-evidence-historical-match-v1",
  source_reference: {},
  total_historical_rules: 70,
  top_ten_hypotheses: [],
};

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    headers: { "content-type": "application/json" },
    status: 200,
  });
}

test("les URLs de transport sont strictement bornées", () => {
  assert.equal(
    hypothesisEvidenceAnalysisUrl(hypothesisId),
    `/data/hypothesis-evidence/hypotheses/${hypothesisId}/analysis.json`,
  );
  assert.equal(
    hypothesisEvidenceQueryIndexUrl(hypothesisId),
    `/data/hypothesis-evidence/hypotheses/${hypothesisId}/query-index.json`,
  );
  assert.equal(
    hypothesisEvidenceSummaryUrl(hypothesisId),
    `/data/hypothesis-evidence/hypotheses/${hypothesisId}/summary.json`,
  );
  assert.equal(
    hypothesisEvidenceMembershipPageUrl(hypothesisId, 25, 3),
    `/data/hypothesis-evidence/hypotheses/${hypothesisId}/memberships/25/page-0003.json`,
  );
  assert.equal(
    hypothesisEvidenceMatchDetailUrl(matchRef),
    `/data/hypothesis-evidence/${matchRef}`,
  );
  assert.throws(
    () => hypothesisEvidenceMembershipPageUrl("../secret", 25, 1),
    (error: unknown) =>
      error instanceof EvidenceAssetError &&
      error.code === "EVIDENCE_HYPOTHESIS_ID_INVALID",
  );
  assert.throws(
    () => hypothesisEvidenceMembershipPageUrl(hypothesisId, 100, 1),
    (error: unknown) =>
      error instanceof EvidenceAssetError &&
      error.code === "EVIDENCE_PAGE_SIZE_INVALID",
  );
  assert.throws(
    () => hypothesisEvidenceMatchDetailUrl("../manifest.json"),
    (error: unknown) =>
      error instanceof EvidenceAssetError &&
      error.code === "EVIDENCE_MATCH_DETAIL_REF_INVALID",
  );
});

test("chaque loader ne lit que l'asset demandé, jamais le manifeste global", async () => {
  const calls: string[] = [];
  const payloads = new Map<string, unknown>([
    ["/data/hypothesis-evidence/index.json", indexPayload],
    [
      `/data/hypothesis-evidence/hypotheses/${hypothesisId}/summary.json`,
      summaryPayload,
    ],
    [
      `/data/hypothesis-evidence/hypotheses/${hypothesisId}/analysis.json`,
      analysisPayload,
    ],
    [
      `/data/hypothesis-evidence/hypotheses/${hypothesisId}/query-index.json`,
      queryIndexPayload,
    ],
    [
      `/data/hypothesis-evidence/hypotheses/${hypothesisId}/memberships/25/page-0001.json`,
      pagePayload,
    ],
    [`/data/hypothesis-evidence/${matchRef}`, matchPayload],
  ]);
  const fetcher: typeof fetch = async (input) => {
    const url = String(input);
    calls.push(url);
    const payload = payloads.get(url);
    return payload === undefined
      ? new Response("missing", { status: 404 })
      : jsonResponse(payload);
  };

  const index = await loadHypothesisEvidenceIndex({ fetcher });
  const summary = await loadHypothesisEvidenceSummary(hypothesisId, {
    fetcher,
  });
  const analysis = await loadHypothesisEvidenceAnalysis(hypothesisId, {
    fetcher,
  });
  const queryIndex = await loadHypothesisEvidenceQueryIndex(hypothesisId, {
    fetcher,
  });
  const page = await loadHypothesisEvidenceMembershipPage(
    hypothesisId,
    25,
    1,
    { fetcher },
  );
  const match = await loadHypothesisEvidenceMatchDetail(matchRef, {
    fetcher,
  });

  assert.equal(index.hypotheses.length, 1);
  assert.equal(summary.hypothesis_id, hypothesisId);
  assert.equal(analysis.bankroll_points.length, 1);
  assert.equal(queryIndex.items.length, 1);
  assert.equal(queryIndex.intended_consumer, "SERVER_RENDERED_MATCH_LIST");
  assert.equal(queryIndex.transport, "PUBLIC_SAME_ORIGIN_STATIC_ASSET");
  assert.equal(page.items.length, 1);
  assert.equal(match.canonical_match_id, "api-football:123");
  assert.equal(match.total_historical_rules, 70);
  assert.deepEqual(calls, [...payloads.keys()]);
  assert.ok(calls.every((url) => !url.endsWith("/manifest.json")));
  assert.ok(calls.every((url) => !url.endsWith("/matches/index.json")));
});

test("le loader SSR résout l'asset contre une origine explicite", async () => {
  const calls: string[] = [];
  const fetcher: typeof fetch = async (input) => {
    calls.push(String(input));
    return jsonResponse(pagePayload);
  };

  await loadHypothesisEvidenceMembershipPage(hypothesisId, 25, 1, {
    baseUrl: "https://preview.example.test/hypotheses/J10-M001",
    fetcher,
  });

  assert.deepEqual(calls, [
    `https://preview.example.test/data/hypothesis-evidence/hypotheses/${hypothesisId}/memberships/25/page-0001.json`,
  ]);
});

test("le transport SSR n'impose pas de mode cache incompatible avec Workers", async () => {
  let observedInit: RequestInit | undefined;
  const fetcher: typeof fetch = async (_input, init) => {
    observedInit = init;
    return jsonResponse(summaryPayload);
  };

  await loadHypothesisEvidenceSummary(hypothesisId, { fetcher });

  assert.equal(observedInit?.cache, undefined);
  assert.equal(new Headers(observedInit?.headers).get("accept"), "application/json");
});

test("un payload trop gros ou incohérent est rejeté avant usage", async () => {
  const oversized: typeof fetch = async () =>
    new Response("{}", {
      headers: { "content-length": String(200 * 1024) },
      status: 200,
    });
  await assert.rejects(
    loadHypothesisEvidenceMembershipPage(hypothesisId, 25, 1, {
      fetcher: oversized,
    }),
    (error: unknown) =>
      error instanceof EvidenceAssetError &&
      error.code === "EVIDENCE_ASSET_TOO_LARGE",
  );

  const wrongPage: typeof fetch = async () =>
    jsonResponse({ ...pagePayload, page: 2 });
  await assert.rejects(
    loadHypothesisEvidenceMembershipPage(hypothesisId, 25, 1, {
      fetcher: wrongPage,
    }),
    (error: unknown) =>
      error instanceof EvidenceAssetError &&
      error.code === "EVIDENCE_MEMBERSHIP_PAGE_CONTRACT_INVALID",
  );

  const oversizedQueryIndex: typeof fetch = async () =>
    new Response("{}", {
      headers: { "content-length": String(2 * 1024 * 1024 + 1) },
      status: 200,
    });
  await assert.rejects(
    loadHypothesisEvidenceQueryIndex(hypothesisId, {
      fetcher: oversizedQueryIndex,
    }),
    (error: unknown) =>
      error instanceof EvidenceAssetError &&
      error.code === "EVIDENCE_ASSET_TOO_LARGE",
  );

  const duplicateQueryIndex: typeof fetch = async () =>
    jsonResponse({
      ...queryIndexPayload,
      items: [
        queryIndexPayload.items[0],
        { ...queryIndexPayload.items[0], occurrence_index: 2 },
      ],
      total_items: 2,
    });
  await assert.rejects(
    loadHypothesisEvidenceQueryIndex(hypothesisId, {
      fetcher: duplicateQueryIndex,
    }),
    (error: unknown) =>
      error instanceof EvidenceAssetError &&
      error.code === "EVIDENCE_QUERY_INDEX_ITEM_INVALID",
  );

  const analysisWithoutHumanLabel: typeof fetch = async () =>
    jsonResponse({
      ...analysisPayload,
      bankroll_points: analysisPayload.bankroll_points.map((point) =>
        Object.fromEntries(
          Object.entries(point).filter(([key]) => key !== "match_label"),
        ),
      ),
    });
  await assert.rejects(
    loadHypothesisEvidenceAnalysis(hypothesisId, {
      fetcher: analysisWithoutHumanLabel,
    }),
    (error: unknown) =>
      error instanceof EvidenceAssetError &&
      error.code === "EVIDENCE_ANALYSIS_BANKROLL_INVALID",
  );

  const inconsistentMatchCount: typeof fetch = async () =>
    jsonResponse({
      ...matchPayload,
      top_ten_hypotheses: [{ hypothesis_id: hypothesisId }],
      total_historical_rules: 0,
    });
  await assert.rejects(
    loadHypothesisEvidenceMatchDetail(matchRef, {
      fetcher: inconsistentMatchCount,
    }),
    (error: unknown) =>
      error instanceof EvidenceAssetError &&
      error.code === "EVIDENCE_MATCH_DETAIL_CONTRACT_INVALID",
  );
});
