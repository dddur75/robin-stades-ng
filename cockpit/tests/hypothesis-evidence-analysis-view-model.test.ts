import assert from "node:assert/strict";
import test from "node:test";

import {
  HypothesisEvidenceAnalysisViewModelError,
  mapHypothesisEvidenceAnalysisToViewModels,
} from "../app/lib/hypothesis-evidence-analysis-view-model";
import type { HypothesisEvidenceAnalysis } from "../app/lib/hypothesis-evidence-assets";

const hypothesisId = "J10-M001";
const ruleHash = "1".repeat(64);
const returnTo =
  "/hypotheses/J10-M001/matchs?tri=profit-desc";

function reference(id: number, date: string, hash: string) {
  return {
    canonical_match_id: `api-football:${id}`,
    match_date: date,
    match_detail_ref: `matches/${hash.repeat(64)}.json`,
    match_label: `Home ${id} – Away ${id}`,
  };
}

const matchOne = reference(1, "2024-01-01", "a");
const matchTwo = reference(2, "2024-01-02", "b");
const matchThree = reference(3, "2024-01-03", "c");

const validAnalysis = {
  bankroll_points: [
    {
      ...matchOne,
      cumulative_profit_units: 1,
      occurrence_index: 1,
    },
    {
      ...matchTwo,
      cumulative_profit_units: 2,
      occurrence_index: 2,
    },
    {
      ...matchThree,
      cumulative_profit_units: 1,
      occurrence_index: 3,
    },
  ],
  evidence_kind: "HISTORICAL",
  folds: [
    {
      fold: "SEASON:2023",
      fold_index: 1,
      losses: 0,
      occurrences: 2,
      positive: true,
      profit_units: 2,
      reference_match: matchOne,
      roi: 1,
      total_staked_units: 2,
      voids: 0,
      wins: 2,
    },
    {
      fold: "SEASON:2024",
      fold_index: 2,
      losses: 1,
      occurrences: 1,
      positive: false,
      profit_units: -1,
      reference_match: matchThree,
      roi: -1,
      total_staked_units: 1,
      voids: 0,
      wins: 0,
    },
  ],
  hypothesis_id: hypothesisId,
  odds_bands: [
    {
      band_id: "FROM_1_50_TO_1_99",
      label: "1,50–1,99",
      losses: 0,
      maximum_odds_exclusive: 2,
      minimum_odds: 1.5,
      occurrences: 2,
      profit_units: 2,
      reference_match: matchOne,
      roi: 1,
      total_staked_units: 2,
      voids: 0,
      wins: 2,
    },
    {
      band_id: "GE_5_00",
      label: "5,00 ou plus",
      losses: 1,
      maximum_odds_exclusive: null,
      minimum_odds: 5,
      occurrences: 1,
      profit_units: -1,
      reference_match: matchThree,
      roi: -1,
      total_staked_units: 1,
      voids: 0,
      wins: 0,
    },
  ],
  prospective_evidence_included: false,
  provenance: {
    provider_payloads_copied: false,
  },
  rule_hash: ruleHash,
  schema_version: "hypothesis-evidence-analysis-v1",
  seasons: [
    {
      losses: 1,
      occurrences: 3,
      profit_units: 1,
      reference_match: matchOne,
      roi: 1 / 3,
      season: 2024,
      total_staked_units: 3,
      voids: 0,
      wins: 2,
    },
  ],
  streaks: {
    losing: {
      current_length: 1,
      current_run: {
        end_match: matchThree,
        end_occurrence_index: 3,
        length: 1,
        start_match: matchThree,
        start_occurrence_index: 3,
      },
      longest_length: 1,
      longest_run: {
        end_match: matchThree,
        end_occurrence_index: 3,
        length: 1,
        start_match: matchThree,
        start_occurrence_index: 3,
      },
      run_count: 1,
    },
    runs: [
      {
        end_occurrence_index: 2,
        length: 2,
        outcome: "WIN",
        start_occurrence_index: 1,
      },
      {
        end_occurrence_index: 3,
        length: 1,
        outcome: "LOSS",
        start_occurrence_index: 3,
      },
    ],
    winning: {
      current_length: 0,
      current_run: null,
      longest_length: 2,
      longest_run: {
        end_match: matchTwo,
        end_occurrence_index: 2,
        length: 2,
        start_match: matchOne,
        start_occurrence_index: 1,
      },
      run_count: 1,
    },
  },
  team_concentration: {
    denominator_team_appearances: 6,
    items: [
      {
        away_occurrences: 1,
        home_occurrences: 1,
        losses: 0,
        occurrences: 2,
        profit_units: 2,
        rank: 1,
        reference_match: matchOne,
        share_of_team_appearances: 1 / 3,
        team_id: "T1",
        team_name: "Équipe A",
        voids: 0,
        wins: 2,
      },
      {
        away_occurrences: 1,
        home_occurrences: 0,
        losses: 1,
        occurrences: 1,
        profit_units: -1,
        rank: 2,
        reference_match: matchThree,
        share_of_team_appearances: 1 / 6,
        team_id: "T2",
        team_name: "Équipe B",
        voids: 0,
        wins: 0,
      },
    ],
    maximum_items: 10,
  },
} satisfies HypothesisEvidenceAnalysis;

function cloneAnalysis(): HypothesisEvidenceAnalysis {
  return structuredClone(validAnalysis);
}

function href(matchId: number): string {
  return (
    `/matchs/historique/api-football%3A${matchId}` +
    "?hypothese=J10-M001" +
    "&retour=%2Fhypotheses%2FJ10-M001%2Fmatchs%3Ftri%3Dprofit-desc"
  );
}

test("le mapper produit exactement les six view-models et les liens contextuels", () => {
  const analysis = cloneAnalysis();
  const before = structuredClone(analysis);

  const result = mapHypothesisEvidenceAnalysisToViewModels(analysis, {
    hypothesisId,
    returnTo,
  });

  assert.deepEqual(result, {
    bankroll: [
      {
        cumulativeProfitUnits: 1,
        matchDate: "2024-01-01",
        matchHref: href(1),
        matchId: "api-football:1",
        matchLabel: "Home 1 – Away 1",
        playedAt: "2024-01-01",
      },
      {
        cumulativeProfitUnits: 2,
        matchDate: "2024-01-02",
        matchHref: href(2),
        matchId: "api-football:2",
        matchLabel: "Home 2 – Away 2",
        playedAt: "2024-01-02",
      },
      {
        cumulativeProfitUnits: 1,
        matchDate: "2024-01-03",
        matchHref: href(3),
        matchId: "api-football:3",
        matchLabel: "Home 3 – Away 3",
        playedAt: "2024-01-03",
      },
    ],
    folds: [
      {
        fold: 1,
        label: "Saison 2023",
        matchDate: "2024-01-01",
        matchHref: href(1),
        matchId: "api-football:1",
        matchLabel: "Home 1 – Away 1",
        matches: 2,
        positive: true,
        profitUnits: 2,
        roi: 1,
      },
      {
        fold: 2,
        label: "Saison 2024",
        matchDate: "2024-01-03",
        matchHref: href(3),
        matchId: "api-football:3",
        matchLabel: "Home 3 – Away 3",
        matches: 1,
        positive: false,
        profitUnits: -1,
        roi: -1,
      },
    ],
    odds: [
      {
        label: "1,50–1,99",
        matchDate: "2024-01-01",
        matchHref: href(1),
        matchId: "api-football:1",
        matchLabel: "Home 1 – Away 1",
        matches: 2,
        maximumOdds: 2,
        minimumOdds: 1.5,
        profitUnits: 2,
        wins: 2,
      },
      {
        label: "5,00 ou plus",
        matchDate: "2024-01-03",
        matchHref: href(3),
        matchId: "api-football:3",
        matchLabel: "Home 3 – Away 3",
        matches: 1,
        maximumOdds: 5,
        minimumOdds: 5,
        profitUnits: -1,
        wins: 0,
      },
    ],
    seasons: [
      {
        losses: 1,
        matchDate: "2024-01-01",
        matchHref: href(1),
        matchId: "api-football:1",
        matchLabel: "Home 1 – Away 1",
        matches: 3,
        profitUnits: 1,
        roi: 1 / 3,
        season: "2024",
        wins: 2,
      },
    ],
    streaks: {
      losing: {
        currentLength: 1,
        longestLength: 1,
        runCount: 1,
      },
      runs: [
        {
          endOccurrenceIndex: 2,
          length: 2,
          outcome: "won",
          startOccurrenceIndex: 1,
        },
        {
          endOccurrenceIndex: 3,
          length: 1,
          outcome: "lost",
          startOccurrenceIndex: 3,
        },
      ],
      winning: {
        currentLength: 0,
        longestLength: 2,
        runCount: 1,
      },
    },
    teams: [
      {
        losses: 0,
        matchDate: "2024-01-01",
        matchHref: href(1),
        matchId: "api-football:1",
        matchLabel: "Home 1 – Away 1",
        matches: 2,
        profitUnits: 2,
        share: 1 / 3,
        team: "Équipe A",
        voids: 0,
        wins: 2,
      },
      {
        losses: 1,
        matchDate: "2024-01-03",
        matchHref: href(3),
        matchId: "api-football:3",
        matchLabel: "Home 3 – Away 3",
        matches: 1,
        profitUnits: -1,
        share: 1 / 6,
        team: "Équipe B",
        voids: 0,
        wins: 0,
      },
    ],
    teamTotalMatches: 6,
  });
  assert.deepEqual(analysis, before);
});

test("le contexte d'hypothèse doit correspondre à l'asset", () => {
  assert.throws(
    () =>
      mapHypothesisEvidenceAnalysisToViewModels(cloneAnalysis(), {
        hypothesisId: "J10-M999",
      }),
    (error: unknown) =>
      error instanceof HypothesisEvidenceAnalysisViewModelError &&
      error.code ===
        "ANALYSIS_VIEW_MODEL_HYPOTHESIS_RELATION_INVALID",
  );
});

test("les relations, nombres et séries incohérents échouent fermés", () => {
  const cases: Array<
    [
      (analysis: Record<string, unknown>) => void,
      string,
    ]
  > = [
    [
      (analysis) => {
        const points = analysis.bankroll_points as Array<
          Record<string, unknown>
        >;
        points[1]!.canonical_match_id =
          points[0]!.canonical_match_id;
      },
      "ANALYSIS_VIEW_MODEL_BANKROLL_ORDER_INVALID",
    ],
    [
      (analysis) => {
        const seasons = analysis.seasons as Array<Record<string, unknown>>;
        seasons[0]!.profit_units = Number.NaN;
      },
      "ANALYSIS_VIEW_MODEL_NUMBER_INVALID",
    ],
    [
      (analysis) => {
        const points = analysis.bankroll_points as Array<
          Record<string, unknown>
        >;
        points[0]!.match_label = points[0]!.canonical_match_id;
      },
      "ANALYSIS_VIEW_MODEL_REFERENCE_INVALID",
    ],
    [
      (analysis) => {
        const streaks = analysis.streaks as Record<string, unknown>;
        const runs = streaks.runs as Array<Record<string, unknown>>;
        runs[0]!.length = 1;
      },
      "ANALYSIS_VIEW_MODEL_STREAK_RUN_INVALID",
    ],
  ];

  for (const [mutate, expectedCode] of cases) {
    const analysis = cloneAnalysis() as unknown as Record<string, unknown>;
    mutate(analysis);
    assert.throws(
      () =>
        mapHypothesisEvidenceAnalysisToViewModels(
          analysis as unknown as HypothesisEvidenceAnalysis,
          { hypothesisId },
        ),
      (error: unknown) =>
        error instanceof HypothesisEvidenceAnalysisViewModelError &&
        error.code === expectedCode,
    );
  }
});
