import {
  DEFAULT_EXPERIENCE_PAGE_SIZE,
  isExperiencePageSize,
  type ExperiencePageSize,
  type ExperiencePhase,
  type PaginationContract,
} from "./contracts/experience-v12";

export type SearchParamRecord = Readonly<
  Record<string, string | readonly string[] | undefined>
>;
export type SearchParamInput = URLSearchParams | SearchParamRecord;

export const MAX_QUERY_PAGE = 10_000;
export const MAX_FILTER_LENGTH = 120;

export type MatchListSort =
  | "kickoff-asc"
  | "kickoff-desc"
  | "team-asc";

export type MatchListQuery = {
  page: number;
  pageSize: ExperiencePageSize;
  phase: ExperiencePhase | "all";
  competition: string | null;
  date: string | null;
  status: string | null;
  query: string;
  sort: MatchListSort;
};

export const HISTORICAL_RANKING_CATEGORY = "historical_raw" as const;
export const HISTORICAL_RANKING_SORTS = [
  "roi-desc",
  "profit-desc",
  "support-desc",
  "hit-rate-desc",
  "drawdown-asc",
] as const;

export type RankingSort = (typeof HISTORICAL_RANKING_SORTS)[number];

export type RankingListQuery = {
  page: number;
  pageSize: ExperiencePageSize;
  category: typeof HISTORICAL_RANKING_CATEGORY;
  competition: string | null;
  family: string | null;
  market: string | null;
  origin: string | null;
  cutoff: string | null;
  sort: RankingSort;
};

function firstValue(input: SearchParamInput, key: string): string | undefined {
  if (input instanceof URLSearchParams) {
    return input.get(key) ?? undefined;
  }
  const value = input[key];
  return typeof value === "string" ? value : value?.[0];
}

function cleanText(value: string | undefined, uppercase = false) {
  if (!value) return null;
  const cleaned = value.replace(/\s+/gu, " ").trim().slice(0, MAX_FILTER_LENGTH);
  if (!cleaned) return null;
  return uppercase ? cleaned.toLocaleUpperCase("fr-FR") : cleaned;
}

function parsePage(value: string | undefined) {
  if (!value || !/^\d+$/u.test(value)) return 1;
  const page = Number(value);
  if (!Number.isSafeInteger(page) || page < 1) return 1;
  return Math.min(page, MAX_QUERY_PAGE);
}

function parsePageSize(value: string | undefined): ExperiencePageSize {
  const parsed = Number(value);
  return isExperiencePageSize(parsed)
    ? parsed
    : DEFAULT_EXPERIENCE_PAGE_SIZE;
}

function enumValue<const Value extends string>(
  value: string | undefined,
  allowed: readonly Value[],
  fallback: Value,
): Value {
  return allowed.includes(value as Value) ? (value as Value) : fallback;
}

function isoDate(value: string | undefined) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/u.test(value)) return null;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ||
    date.toISOString().slice(0, 10) !== value
    ? null
    : value;
}

export function parseMatchListQuery(
  input: SearchParamInput,
): MatchListQuery {
  const query =
    cleanText(
      firstValue(input, "recherche") ?? firstValue(input, "q"),
    ) ?? "";
  return {
    page: parsePage(firstValue(input, "page")),
    pageSize: parsePageSize(
      firstValue(input, "taille") ?? firstValue(input, "pageSize"),
    ),
    phase: enumValue(
      firstValue(input, "phase"),
      ["all", "historical", "prospective"] as const,
      "all",
    ),
    competition: cleanText(firstValue(input, "competition")),
    date: isoDate(firstValue(input, "date")),
    status: cleanText(firstValue(input, "statut"), true),
    query,
    sort: enumValue(
      firstValue(input, "tri"),
      ["kickoff-asc", "kickoff-desc", "team-asc"] as const,
      "kickoff-asc",
    ),
  };
}

export function serializeMatchListQuery(query: MatchListQuery) {
  const params = new URLSearchParams();
  if (query.phase !== "all") params.set("phase", query.phase);
  if (query.competition) params.set("competition", query.competition);
  if (query.date) params.set("date", query.date);
  if (query.status) params.set("statut", query.status);
  if (query.query) params.set("recherche", query.query);
  if (query.sort !== "kickoff-asc") params.set("tri", query.sort);
  if (query.page > 1) params.set("page", String(query.page));
  if (query.pageSize !== DEFAULT_EXPERIENCE_PAGE_SIZE) {
    params.set("taille", String(query.pageSize));
  }
  return canonicalizeSearchParams(params);
}

export function parseRankingListQuery(
  input: SearchParamInput,
): RankingListQuery {
  return {
    page: parsePage(firstValue(input, "page")),
    pageSize: parsePageSize(
      firstValue(input, "taille") ?? firstValue(input, "pageSize"),
    ),
    category: enumValue(
      firstValue(input, "categorie"),
      [HISTORICAL_RANKING_CATEGORY] as const,
      HISTORICAL_RANKING_CATEGORY,
    ),
    competition: cleanText(firstValue(input, "competition")),
    family: cleanText(firstValue(input, "famille"), true),
    market: cleanText(firstValue(input, "marche"), true),
    origin: cleanText(firstValue(input, "origine"), true),
    cutoff: cleanText(firstValue(input, "heure-limite"), true),
    sort: enumValue(
      firstValue(input, "tri"),
      HISTORICAL_RANKING_SORTS,
      "roi-desc",
    ),
  };
}

export function serializeRankingListQuery(query: RankingListQuery) {
  const params = new URLSearchParams();
  if (query.competition) params.set("competition", query.competition);
  if (query.family) params.set("famille", query.family);
  if (query.market) params.set("marche", query.market);
  if (query.origin) params.set("origine", query.origin);
  if (query.cutoff) params.set("heure-limite", query.cutoff);
  if (query.sort !== "roi-desc") params.set("tri", query.sort);
  if (query.page > 1) params.set("page", String(query.page));
  if (query.pageSize !== DEFAULT_EXPERIENCE_PAGE_SIZE) {
    params.set("taille", String(query.pageSize));
  }
  return canonicalizeSearchParams(params);
}

export function canonicalizeSearchParams(input: URLSearchParams) {
  const canonical = new URLSearchParams();
  const entries = [...input.entries()].sort(([leftKey, leftValue], [rightKey, rightValue]) => {
    const keyOrder = leftKey.localeCompare(rightKey, "fr");
    return keyOrder || leftValue.localeCompare(rightValue, "fr");
  });
  for (const [key, value] of entries) canonical.append(key, value);
  return canonical;
}

export function mergeSearchParams(
  input: URLSearchParams,
  updates: Readonly<Record<string, string | number | null | undefined>>,
) {
  const next = new URLSearchParams(input);
  for (const [key, value] of Object.entries(updates)) {
    if (value == null || value === "") next.delete(key);
    else next.set(key, String(value));
  }
  return canonicalizeSearchParams(next);
}

export function createPaginationContract(
  requestedPage: number,
  pageSize: ExperiencePageSize,
  totalItems: number,
): PaginationContract {
  const safeTotal = Math.max(0, Math.trunc(totalItems));
  const totalPages = Math.max(1, Math.ceil(safeTotal / pageSize));
  const page = Math.min(
    Math.max(1, Math.trunc(requestedPage) || 1),
    totalPages,
  );
  const from = safeTotal === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = safeTotal === 0 ? 0 : Math.min(page * pageSize, safeTotal);
  return {
    page,
    pageSize,
    totalItems: safeTotal,
    totalPages,
    from,
    to,
    hasPrevious: page > 1,
    hasNext: page < totalPages,
  };
}
