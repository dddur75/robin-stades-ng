/**
 * Frontend presentation contracts for Robin Experience V1.2.
 *
 * These types deliberately describe bounded, source-backed view models. They
 * are not scientific source contracts and must never be used to infer missing
 * historical or prospective evidence.
 */

export const EXPERIENCE_PAGE_SIZES = [25, 50] as const;
export const DEFAULT_EXPERIENCE_PAGE_SIZE = 25;

export type ExperiencePageSize = (typeof EXPERIENCE_PAGE_SIZES)[number];
export type ExperiencePhase = "historical" | "prospective";
export type IsoDateTime = string;

export function isExperiencePageSize(
  value: unknown,
): value is ExperiencePageSize {
  return (
    typeof value === "number" &&
    EXPERIENCE_PAGE_SIZES.includes(value as ExperiencePageSize)
  );
}

export type PaginationContract = {
  /** One-based current page. */
  page: number;
  pageSize: ExperiencePageSize;
  totalItems: number;
  /** At least one, including for an empty collection. */
  totalPages: number;
  /** One-based inclusive item index, or zero for an empty collection. */
  from: number;
  /** One-based inclusive item index, or zero for an empty collection. */
  to: number;
  hasPrevious: boolean;
  hasNext: boolean;
};

export type PresentationProvenance = {
  generatedAt: IsoDateTime;
  sourceRevision: string;
  sourceHashes: readonly string[];
  sourceContracts: readonly string[];
};

export type MatchTeamContract = {
  id: string;
  name: string;
  identityStatus: "verified" | "unresolved";
};

export type MatchScoreContract = {
  away: number;
  home: number;
  period: "full_time" | "after_extra_time" | "after_penalties";
  penaltiesAway: number | null;
  penaltiesHome: number | null;
};

export type MatchHypothesisRelation = {
  hypothesisId: string;
  relation:
    | "eligible"
    | "observed"
    | "rejected"
    | "settled"
    | "potential";
  evidenceId: string | null;
};

type MatchSummaryBase = {
  id: string;
  competition: string;
  kickoffAt: IsoDateTime;
  home: MatchTeamContract;
  away: MatchTeamContract;
  hypothesisRelations: readonly MatchHypothesisRelation[];
};

export type HistoricalMatchSummaryContract = MatchSummaryBase & {
  phase: "historical";
  status: "finished";
  score: MatchScoreContract;
  settledAt: IsoDateTime | null;
};

export type ProspectiveMatchSummaryContract = MatchSummaryBase & {
  phase: "prospective";
  status: "scheduled" | "postponed" | "cancelled";
  coverage: number;
  dataStatus: string;
  nextCaptureAt: IsoDateTime | null;
  nextCaptureFamilies: readonly string[];
};

export type MatchSummaryContract =
  | HistoricalMatchSummaryContract
  | ProspectiveMatchSummaryContract;

export type HistoricalMatchDetailContract = {
  schemaVersion: "match-detail-v1.2";
  phase: "historical";
  summary: HistoricalMatchSummaryContract;
  historical: {
    score: MatchScoreContract;
    settledAt: IsoDateTime | null;
    statistics: Readonly<Record<string, number | null>>;
    eventIds: readonly string[];
  };
  prospective?: never;
  provenance: PresentationProvenance;
};

export type ProspectiveCaptureWindowContract = {
  id: string;
  family: string;
  opensAt: IsoDateTime;
  dueAt: IsoDateTime;
  cutoffAt: IsoDateTime;
  status: string;
};

export type ProspectiveMatchDetailContract = {
  schemaVersion: "match-detail-v1.2";
  phase: "prospective";
  summary: ProspectiveMatchSummaryContract;
  historical?: never;
  prospective: {
    captureWindows: readonly ProspectiveCaptureWindowContract[];
    capturedFamilies: readonly string[];
    expectedFamilies: readonly string[];
    oddsSnapshotIds: readonly string[];
  };
  provenance: PresentationProvenance;
};

export type MatchDetailContract =
  | HistoricalMatchDetailContract
  | ProspectiveMatchDetailContract;

export type MatchListContract = {
  schemaVersion: "match-list-v1.2";
  items: readonly MatchSummaryContract[];
  pagination: PaginationContract;
  provenance: PresentationProvenance;
};

export function isHistoricalMatchSummary(
  match: MatchSummaryContract,
): match is HistoricalMatchSummaryContract {
  return match.phase === "historical";
}

export function isProspectiveMatchSummary(
  match: MatchSummaryContract,
): match is ProspectiveMatchSummaryContract {
  return match.phase === "prospective";
}

export function isHistoricalMatchDetail(
  match: MatchDetailContract,
): match is HistoricalMatchDetailContract {
  return match.phase === "historical";
}

export function isProspectiveMatchDetail(
  match: MatchDetailContract,
): match is ProspectiveMatchDetailContract {
  return match.phase === "prospective";
}

export type RankingCategory =
  | "historical_raw"
  | "exploratory_priority"
  | "prospective_observation"
  | "validated"
  | "long_tail";

export type RankingScope =
  | { kind: "global" }
  | { kind: "competition"; competition: string }
  | { kind: "family"; family: string }
  | { kind: "market"; market: string }
  | { kind: "origin"; origin: string }
  | { kind: "cutoff"; cutoff: string };

export type HistoricalRankingEvidence = {
  phase: "historical";
  support: number;
  roi: number | null;
  profitUnits: number | null;
  confidenceInterval: readonly [number, number] | null;
  maximumDrawdown: number | null;
  stability: number | null;
  correctedFalsePositiveRisk: number | null;
};

export type ProspectiveRankingEvidence = {
  phase: "prospective";
  frozenAt: IsoDateTime;
  fixturesExamined: number;
  eligibleMatches: number;
  settledObservations: number;
  profitUnits: number | null;
};

export type RankingEvidence =
  | HistoricalRankingEvidence
  | ProspectiveRankingEvidence;

export type RankingEntryContract = {
  hypothesisId: string;
  labelFr: string;
  category: RankingCategory;
  rank: number;
  /** Stable source-backed tie breaker, never a random frontend value. */
  tieBreakKey: string;
  scientificStatus: string;
  family: string;
  competition: string | null;
  market: string | null;
  origin: string | null;
  cutoff: string | null;
  evidence: RankingEvidence;
};

export type RankingPageContract = {
  schemaVersion: "ranking-page-v1.2";
  scope: RankingScope;
  category: RankingCategory;
  requestedTop: number;
  availableCount: number;
  /** False when, for example, a requested top 10 contains only 3 source rows. */
  complete: boolean;
  items: readonly RankingEntryContract[];
  pagination: PaginationContract;
  provenance: PresentationProvenance;
};
