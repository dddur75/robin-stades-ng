import type {
  HypothesisBankrollPoint,
} from "../components/hypotheses/hypothesis-bankroll-chart";
import type {
  HypothesisFoldEvidence,
} from "../components/hypotheses/hypothesis-fold-validation";
import type {
  HypothesisOddsBin,
} from "../components/hypotheses/hypothesis-odds-distribution";
import type {
  HypothesisSeasonEvidence,
} from "../components/hypotheses/hypothesis-season-breakdown";
import type {
  HypothesisStreakRun,
  HypothesisStreakSummary,
} from "../components/hypotheses/hypothesis-streak-breakdown";
import type {
  HypothesisTeamConcentrationItem,
} from "../components/hypotheses/hypothesis-team-concentration";
import type { HistoricalMatchReference } from "../components/hypotheses/historical-evidence-chart-utils";
import {
  historicalMatchDetailPath,
  historicalMatchListPath,
  safeHistoricalReturnPath,
} from "./historical-match-evidence";
import type { HypothesisEvidenceAnalysis } from "./hypothesis-evidence-assets";

const HASH_64 = /^[0-9a-f]{64}$/u;
const HYPOTHESIS_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u;
const MATCH_DATE = /^\d{4}-\d{2}-\d{2}$/u;
const MATCH_DETAIL_REF = /^matches\/[0-9a-f]{64}\.json$/u;

export type HypothesisEvidenceAnalysisViewModelContext = Readonly<{
  hypothesisId: string;
  returnTo?: string | null;
}>;

export type HypothesisEvidenceAnalysisViewModels = Readonly<{
  bankroll: readonly HypothesisBankrollPoint[];
  folds: readonly HypothesisFoldEvidence[];
  odds: readonly HypothesisOddsBin[];
  seasons: readonly HypothesisSeasonEvidence[];
  streaks: Readonly<{
    losing: HypothesisStreakSummary;
    runs: readonly HypothesisStreakRun[];
    winning: HypothesisStreakSummary;
  }>;
  teams: readonly HypothesisTeamConcentrationItem[];
  teamTotalMatches: number;
}>;

export class HypothesisEvidenceAnalysisViewModelError extends Error {
  readonly code: string;
  readonly path: string;

  constructor(code: string, path: string) {
    super(`${code}:${path}`);
    this.name = "HypothesisEvidenceAnalysisViewModelError";
    this.code = code;
    this.path = path;
  }
}

function invalid(code: string, path: string): never {
  throw new HypothesisEvidenceAnalysisViewModelError(code, path);
}

function record(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    invalid("ANALYSIS_VIEW_MODEL_RECORD_INVALID", path);
  }
  return value as Record<string, unknown>;
}

function array(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) {
    invalid("ANALYSIS_VIEW_MODEL_ARRAY_INVALID", path);
  }
  return value;
}

function stringValue(value: unknown, path: string): string {
  if (typeof value !== "string" || value.length === 0) {
    invalid("ANALYSIS_VIEW_MODEL_STRING_INVALID", path);
  }
  return value;
}

function finiteNumber(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    invalid("ANALYSIS_VIEW_MODEL_NUMBER_INVALID", path);
  }
  return value;
}

function integer(value: unknown, path: string, minimum = 0): number {
  const candidate = finiteNumber(value, path);
  if (!Number.isInteger(candidate) || candidate < minimum) {
    invalid("ANALYSIS_VIEW_MODEL_INTEGER_INVALID", path);
  }
  return candidate;
}

function booleanValue(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") {
    invalid("ANALYSIS_VIEW_MODEL_BOOLEAN_INVALID", path);
  }
  return value;
}

function displayValue(value: unknown, path: string): string {
  if (typeof value === "string" && value.length > 0) return value;
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  return invalid("ANALYSIS_VIEW_MODEL_DISPLAY_INVALID", path);
}

function close(left: number, right: number): boolean {
  return (
    Math.abs(left - right) <=
    1e-9 * Math.max(1, Math.abs(left), Math.abs(right))
  );
}

type MappingContext = Readonly<{
  hypothesisId: string;
  returnTo: string;
}>;

function matchReference(
  value: unknown,
  path: string,
  context: MappingContext,
): HistoricalMatchReference {
  const source = record(value, path);
  const matchId = stringValue(
    source.canonical_match_id,
    `${path}.canonical_match_id`,
  );
  const matchDate = stringValue(source.match_date, `${path}.match_date`);
  const matchLabel = stringValue(source.match_label, `${path}.match_label`);
  const detailRef = stringValue(
    source.match_detail_ref,
    `${path}.match_detail_ref`,
  );
  if (
    !MATCH_DATE.test(matchDate) ||
    !MATCH_DETAIL_REF.test(detailRef) ||
    matchLabel === matchId ||
    /api-football:/iu.test(matchLabel)
  ) {
    invalid("ANALYSIS_VIEW_MODEL_REFERENCE_INVALID", path);
  }
  return {
    matchDate,
    matchHref: historicalMatchDetailPath(matchId, {
      hypothesisId: context.hypothesisId,
      returnTo: context.returnTo,
    }),
    matchId,
    matchLabel,
  };
}

type Aggregate = Readonly<{
  losses: number;
  occurrences: number;
  profitUnits: number;
  reference: HistoricalMatchReference | null;
  roi: number | null;
  totalStakedUnits: number;
  voids: number;
  wins: number;
}>;

function aggregate(
  value: Record<string, unknown>,
  path: string,
  context: MappingContext,
  allowEmpty: boolean,
): Aggregate {
  const occurrences = integer(value.occurrences, `${path}.occurrences`);
  const wins = integer(value.wins, `${path}.wins`);
  const losses = integer(value.losses, `${path}.losses`);
  const voids = integer(value.voids, `${path}.voids`);
  const totalStakedUnits = finiteNumber(
    value.total_staked_units,
    `${path}.total_staked_units`,
  );
  const profitUnits = finiteNumber(
    value.profit_units,
    `${path}.profit_units`,
  );
  if (
    (!allowEmpty && occurrences === 0) ||
    wins + losses + voids !== occurrences ||
    totalStakedUnits < 0
  ) {
    invalid("ANALYSIS_VIEW_MODEL_AGGREGATE_INVALID", path);
  }
  const roi =
    value.roi === null
      ? null
      : finiteNumber(value.roi, `${path}.roi`);
  if (
    (totalStakedUnits === 0 && roi !== null) ||
    (totalStakedUnits > 0 &&
      (roi === null || !close(roi, profitUnits / totalStakedUnits)))
  ) {
    invalid("ANALYSIS_VIEW_MODEL_ROI_INVALID", path);
  }
  const reference =
    value.reference_match === null
      ? null
      : matchReference(
          value.reference_match,
          `${path}.reference_match`,
          context,
        );
  if (
    (occurrences === 0 && reference !== null) ||
    (occurrences > 0 && reference === null)
  ) {
    invalid("ANALYSIS_VIEW_MODEL_REFERENCE_RELATION_INVALID", path);
  }
  return {
    losses,
    occurrences,
    profitUnits,
    reference,
    roi,
    totalStakedUnits,
    voids,
    wins,
  };
}

function requiredReference(
  value: HistoricalMatchReference | null,
  path: string,
): HistoricalMatchReference {
  if (value === null) {
    invalid("ANALYSIS_VIEW_MODEL_REFERENCE_REQUIRED", path);
  }
  return value;
}

function streakSummary(
  value: unknown,
  path: string,
): HypothesisStreakSummary {
  const source = record(value, path);
  return {
    currentLength: integer(
      source.current_length,
      `${path}.current_length`,
    ),
    longestLength: integer(
      source.longest_length,
      `${path}.longest_length`,
    ),
    runCount: integer(source.run_count, `${path}.run_count`),
  };
}

function validateStreakDetail(
  value: unknown,
  expected: HypothesisStreakRun | null,
  path: string,
  context: MappingContext,
): void {
  if (expected === null) {
    if (value !== null) {
      invalid("ANALYSIS_VIEW_MODEL_STREAK_DETAIL_INVALID", path);
    }
    return;
  }
  const source = record(value, path);
  if (
    integer(source.length, `${path}.length`, 1) !== expected.length ||
    integer(
      source.start_occurrence_index,
      `${path}.start_occurrence_index`,
      1,
    ) !== expected.startOccurrenceIndex ||
    integer(
      source.end_occurrence_index,
      `${path}.end_occurrence_index`,
      1,
    ) !== expected.endOccurrenceIndex
  ) {
    invalid("ANALYSIS_VIEW_MODEL_STREAK_DETAIL_INVALID", path);
  }
  matchReference(source.start_match, `${path}.start_match`, context);
  matchReference(source.end_match, `${path}.end_match`, context);
}

function mapStreaks(
  value: unknown,
  bankrollLength: number,
  totalVoids: number,
  context: MappingContext,
): HypothesisEvidenceAnalysisViewModels["streaks"] {
  const source = record(value, "analysis.streaks");
  const rawRuns = array(source.runs, "analysis.streaks.runs");
  let previousEnd = 0;
  const runs = rawRuns.map((value, index): HypothesisStreakRun => {
    const path = `analysis.streaks.runs[${index}]`;
    const run = record(value, path);
    const rawOutcome = stringValue(run.outcome, `${path}.outcome`);
    if (rawOutcome !== "WIN" && rawOutcome !== "LOSS") {
      invalid("ANALYSIS_VIEW_MODEL_STREAK_OUTCOME_INVALID", path);
    }
    const startOccurrenceIndex = integer(
      run.start_occurrence_index,
      `${path}.start_occurrence_index`,
      1,
    );
    const endOccurrenceIndex = integer(
      run.end_occurrence_index,
      `${path}.end_occurrence_index`,
      1,
    );
    const length = integer(run.length, `${path}.length`, 1);
    if (
      startOccurrenceIndex <= previousEnd ||
      endOccurrenceIndex > bankrollLength ||
      endOccurrenceIndex - startOccurrenceIndex + 1 !== length
    ) {
      invalid("ANALYSIS_VIEW_MODEL_STREAK_RUN_INVALID", path);
    }
    previousEnd = endOccurrenceIndex;
    return {
      endOccurrenceIndex,
      length,
      outcome: rawOutcome === "WIN" ? "won" : "lost",
      startOccurrenceIndex,
    };
  });
  if (
    runs.reduce((sum, run) => sum + run.length, 0) !==
    bankrollLength - totalVoids
  ) {
    invalid(
      "ANALYSIS_VIEW_MODEL_STREAK_COVERAGE_INVALID",
      "analysis.streaks.runs",
    );
  }

  const winning = streakSummary(source.winning, "analysis.streaks.winning");
  const losing = streakSummary(source.losing, "analysis.streaks.losing");
  const validateSummary = (
    outcome: HypothesisStreakRun["outcome"],
    summary: HypothesisStreakSummary,
    rawSummary: Record<string, unknown>,
    path: string,
  ) => {
    const matching = runs.filter((run) => run.outcome === outcome);
    const longest = matching.reduce<HypothesisStreakRun | null>(
      (current, run) =>
        current === null || run.length > current.length ? run : current,
      null,
    );
    const terminal =
      runs.at(-1)?.outcome === outcome ? (runs.at(-1) ?? null) : null;
    if (
      summary.runCount !== matching.length ||
      summary.longestLength !== (longest?.length ?? 0) ||
      summary.currentLength !== (terminal?.length ?? 0)
    ) {
      invalid("ANALYSIS_VIEW_MODEL_STREAK_SUMMARY_INVALID", path);
    }
    validateStreakDetail(
      rawSummary.longest_run,
      longest,
      `${path}.longest_run`,
      context,
    );
    validateStreakDetail(
      rawSummary.current_run,
      terminal,
      `${path}.current_run`,
      context,
    );
  };
  validateSummary(
    "won",
    winning,
    record(source.winning, "analysis.streaks.winning"),
    "analysis.streaks.winning",
  );
  validateSummary(
    "lost",
    losing,
    record(source.losing, "analysis.streaks.losing"),
    "analysis.streaks.losing",
  );
  return { losing, runs, winning };
}

export function mapHypothesisEvidenceAnalysisToViewModels(
  analysis: HypothesisEvidenceAnalysis,
  context: HypothesisEvidenceAnalysisViewModelContext,
): HypothesisEvidenceAnalysisViewModels {
  const source = record(analysis, "analysis");
  if (
    source.schema_version !== "hypothesis-evidence-analysis-v1" ||
    source.evidence_kind !== "HISTORICAL" ||
    source.prospective_evidence_included !== false
  ) {
    invalid("ANALYSIS_VIEW_MODEL_ENVELOPE_INVALID", "analysis");
  }
  const hypothesisId = stringValue(
    source.hypothesis_id,
    "analysis.hypothesis_id",
  );
  if (
    !HYPOTHESIS_ID.test(hypothesisId) ||
    context.hypothesisId !== hypothesisId
  ) {
    invalid(
      "ANALYSIS_VIEW_MODEL_HYPOTHESIS_RELATION_INVALID",
      "analysis.hypothesis_id",
    );
  }
  const ruleHash = stringValue(source.rule_hash, "analysis.rule_hash");
  if (!HASH_64.test(ruleHash)) {
    invalid("ANALYSIS_VIEW_MODEL_RULE_HASH_INVALID", "analysis.rule_hash");
  }
  const provenance = record(source.provenance, "analysis.provenance");
  if (provenance.provider_payloads_copied !== false) {
    invalid(
      "ANALYSIS_VIEW_MODEL_PROVENANCE_INVALID",
      "analysis.provenance",
    );
  }
  const mappingContext: MappingContext = {
    hypothesisId,
    returnTo: safeHistoricalReturnPath(
      context.returnTo ?? historicalMatchListPath(hypothesisId),
      hypothesisId,
    ),
  };

  const seenMatches = new Set<string>();
  const bankroll = array(
    source.bankroll_points,
    "analysis.bankroll_points",
  ).map((value, index): HypothesisBankrollPoint => {
    const path = `analysis.bankroll_points[${index}]`;
    const point = record(value, path);
    const reference = matchReference(point, path, mappingContext);
    if (
      integer(point.occurrence_index, `${path}.occurrence_index`, 1) !==
        index + 1 ||
      reference.matchId === undefined ||
      seenMatches.has(reference.matchId)
    ) {
      invalid("ANALYSIS_VIEW_MODEL_BANKROLL_ORDER_INVALID", path);
    }
    seenMatches.add(reference.matchId);
    return {
      ...reference,
      cumulativeProfitUnits: finiteNumber(
        point.cumulative_profit_units,
        `${path}.cumulative_profit_units`,
      ),
      playedAt: stringValue(point.match_date, `${path}.match_date`),
    };
  });
  if (bankroll.length === 0) {
    invalid(
      "ANALYSIS_VIEW_MODEL_BANKROLL_EMPTY",
      "analysis.bankroll_points",
    );
  }

  let seasonOccurrences = 0;
  let seasonVoids = 0;
  let seasonProfit = 0;
  const seenSeasons = new Set<string>();
  const seasons = array(source.seasons, "analysis.seasons").map(
    (value, index): HypothesisSeasonEvidence => {
      const path = `analysis.seasons[${index}]`;
      const row = record(value, path);
      const season = displayValue(row.season, `${path}.season`);
      if (seenSeasons.has(season)) {
        invalid("ANALYSIS_VIEW_MODEL_SEASON_DUPLICATE", path);
      }
      seenSeasons.add(season);
      const metrics = aggregate(row, path, mappingContext, false);
      if (metrics.roi === null) {
        invalid("ANALYSIS_VIEW_MODEL_ROI_REQUIRED", `${path}.roi`);
      }
      seasonOccurrences += metrics.occurrences;
      seasonVoids += metrics.voids;
      seasonProfit += metrics.profitUnits;
      return {
        ...requiredReference(metrics.reference, `${path}.reference_match`),
        losses: metrics.losses,
        matches: metrics.occurrences,
        profitUnits: metrics.profitUnits,
        roi: metrics.roi,
        season,
        wins: metrics.wins,
      };
    },
  );

  let oddsOccurrences = 0;
  let oddsProfit = 0;
  const seenBands = new Set<string>();
  const odds = array(source.odds_bands, "analysis.odds_bands").map(
    (value, index): HypothesisOddsBin => {
      const path = `analysis.odds_bands[${index}]`;
      const row = record(value, path);
      const bandId = stringValue(row.band_id, `${path}.band_id`);
      if (seenBands.has(bandId)) {
        invalid("ANALYSIS_VIEW_MODEL_ODDS_BAND_DUPLICATE", path);
      }
      seenBands.add(bandId);
      const minimumOdds = finiteNumber(
        row.minimum_odds,
        `${path}.minimum_odds`,
      );
      const maximumOdds =
        row.maximum_odds_exclusive === null
          ? minimumOdds
          : finiteNumber(
              row.maximum_odds_exclusive,
              `${path}.maximum_odds_exclusive`,
            );
      if (
        minimumOdds < 0 ||
        (row.maximum_odds_exclusive !== null &&
          maximumOdds <= minimumOdds)
      ) {
        invalid("ANALYSIS_VIEW_MODEL_ODDS_RANGE_INVALID", path);
      }
      const metrics = aggregate(row, path, mappingContext, true);
      oddsOccurrences += metrics.occurrences;
      oddsProfit += metrics.profitUnits;
      return {
        ...(metrics.reference ?? {}),
        label: stringValue(row.label, `${path}.label`),
        matches: metrics.occurrences,
        maximumOdds,
        minimumOdds,
        profitUnits: metrics.profitUnits,
        wins: metrics.wins,
      };
    },
  );

  let foldOccurrences = 0;
  let foldProfit = 0;
  const folds = array(source.folds, "analysis.folds").map(
    (value, index): HypothesisFoldEvidence => {
      const path = `analysis.folds[${index}]`;
      const row = record(value, path);
      const fold = integer(row.fold_index, `${path}.fold_index`, 1);
      if (fold !== index + 1) {
        invalid("ANALYSIS_VIEW_MODEL_FOLD_ORDER_INVALID", path);
      }
      const metrics = aggregate(row, path, mappingContext, false);
      if (metrics.roi === null) {
        invalid("ANALYSIS_VIEW_MODEL_ROI_REQUIRED", `${path}.roi`);
      }
      const positive = booleanValue(row.positive, `${path}.positive`);
      if (positive !== (metrics.profitUnits > 0)) {
        invalid("ANALYSIS_VIEW_MODEL_FOLD_SIGN_INVALID", path);
      }
      const sourceLabel = stringValue(row.fold, `${path}.fold`);
      const label = sourceLabel.startsWith("SEASON:")
        ? `Saison ${sourceLabel.slice("SEASON:".length)}`
        : `Période ${fold}`;
      foldOccurrences += metrics.occurrences;
      foldProfit += metrics.profitUnits;
      return {
        ...requiredReference(metrics.reference, `${path}.reference_match`),
        fold,
        label,
        matches: metrics.occurrences,
        positive,
        profitUnits: metrics.profitUnits,
        roi: metrics.roi,
      };
    },
  );

  const teamConcentration = record(
    source.team_concentration,
    "analysis.team_concentration",
  );
  if (
    integer(
      teamConcentration.maximum_items,
      "analysis.team_concentration.maximum_items",
      1,
    ) !== 10
  ) {
    invalid(
      "ANALYSIS_VIEW_MODEL_TEAM_LIMIT_INVALID",
      "analysis.team_concentration.maximum_items",
    );
  }
  const teamTotalMatches = integer(
    teamConcentration.denominator_team_appearances,
    "analysis.team_concentration.denominator_team_appearances",
    1,
  );
  const seenTeams = new Set<string>();
  const rawTeams = array(
    teamConcentration.items,
    "analysis.team_concentration.items",
  );
  if (rawTeams.length > 10) {
    invalid(
      "ANALYSIS_VIEW_MODEL_TEAM_LIMIT_INVALID",
      "analysis.team_concentration.items",
    );
  }
  const teams = rawTeams.map(
    (value, index): HypothesisTeamConcentrationItem => {
      const path = `analysis.team_concentration.items[${index}]`;
      const row = record(value, path);
      if (integer(row.rank, `${path}.rank`, 1) !== index + 1) {
        invalid("ANALYSIS_VIEW_MODEL_TEAM_ORDER_INVALID", path);
      }
      const teamId = stringValue(row.team_id, `${path}.team_id`);
      if (seenTeams.has(teamId)) {
        invalid("ANALYSIS_VIEW_MODEL_TEAM_DUPLICATE", path);
      }
      seenTeams.add(teamId);
      const matches = integer(row.occurrences, `${path}.occurrences`, 1);
      const wins = integer(row.wins, `${path}.wins`);
      const losses = integer(row.losses, `${path}.losses`);
      const voids = integer(row.voids, `${path}.voids`);
      const profitUnits = finiteNumber(
        row.profit_units,
        `${path}.profit_units`,
      );
      const home = integer(
        row.home_occurrences,
        `${path}.home_occurrences`,
      );
      const away = integer(
        row.away_occurrences,
        `${path}.away_occurrences`,
      );
      const share = finiteNumber(
        row.share_of_team_appearances,
        `${path}.share_of_team_appearances`,
      );
      if (
        home + away !== matches ||
        wins + losses + voids !== matches ||
        share < 0 ||
        share > 1 ||
        !close(share, matches / teamTotalMatches)
      ) {
        invalid("ANALYSIS_VIEW_MODEL_TEAM_AGGREGATE_INVALID", path);
      }
      return {
        ...matchReference(
          row.reference_match,
          `${path}.reference_match`,
          mappingContext,
        ),
        losses,
        matches,
        profitUnits,
        share,
        team: stringValue(row.team_name, `${path}.team_name`),
        voids,
        wins,
      };
    },
  );

  if (
    seasonOccurrences !== bankroll.length ||
    oddsOccurrences !== bankroll.length ||
    foldOccurrences !== bankroll.length ||
    teamTotalMatches !== bankroll.length * 2 ||
    !close(seasonProfit, oddsProfit) ||
    !close(seasonProfit, foldProfit) ||
    !close(
      seasonProfit,
      bankroll.at(-1)?.cumulativeProfitUnits ?? Number.NaN,
    )
  ) {
    invalid("ANALYSIS_VIEW_MODEL_TOTALS_INVALID", "analysis");
  }
  const streaks = mapStreaks(
    source.streaks,
    bankroll.length,
    seasonVoids,
    mappingContext,
  );

  return {
    bankroll,
    folds,
    odds,
    seasons,
    streaks,
    teams,
    teamTotalMatches,
  };
}
