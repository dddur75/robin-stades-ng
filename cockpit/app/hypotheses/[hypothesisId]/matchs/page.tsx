import type { Metadata } from "next";
import { headers } from "next/headers";
import { notFound } from "next/navigation";

import { HistoricalEvidenceUnavailable } from "../../../components/common/historical-evidence-unavailable";
import { HypothesisHistoricalMatchesPage } from "../../../components/hypotheses/hypothesis-historical-matches-page";
import { ExperienceShell } from "../../../components/navigation/experience-shell";
import {
  historicalEvidenceErrorCode,
  historicalEvidenceOriginFromHeaders,
  isHistoricalEvidenceNotFound,
  loadHistoricalMatchListPage,
} from "../../../lib/historical-match-evidence.server";
import { parseHistoricalMatchListQuery } from "../../../lib/historical-match-evidence";
import type { SearchParamRecord } from "../../../lib/query-params";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  description:
    "Liste paginée des matchs historiques reconstruits pour une hypothèse, séparée de toute observation prospective.",
  title: "Matchs historiques de l’hypothèse",
};

function decodePathSegment(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    notFound();
  }
}

export default async function HypothesisHistoricalMatchesRoute({
  params,
  searchParams,
}: {
  params: Promise<{ hypothesisId: string }>;
  searchParams: Promise<SearchParamRecord>;
}) {
  const [{ hypothesisId: rawHypothesisId }, rawSearchParams] =
    await Promise.all([params, searchParams]);
  const hypothesisId = decodePathSegment(rawHypothesisId);
  const query = parseHistoricalMatchListQuery(rawSearchParams);
  const retryHref =
    `/hypotheses/${encodeURIComponent(hypothesisId)}/matchs`;
  let data: Awaited<ReturnType<typeof loadHistoricalMatchListPage>> | null =
    null;
  let failureCode = "HISTORICAL_EVIDENCE_UNAVAILABLE";

  try {
    const requestHeaders = await headers();
    data = await loadHistoricalMatchListPage(
      hypothesisId,
      query,
      {
        baseUrl: historicalEvidenceOriginFromHeaders(requestHeaders),
      },
    );
  } catch (error) {
    if (isHistoricalEvidenceNotFound(error)) notFound();
    failureCode = historicalEvidenceErrorCode(error);
  }
  if (data === null) {
    return (
      <ExperienceShell active="hypotheses">
        <HistoricalEvidenceUnavailable
          code={failureCode}
          retryHref={retryHref}
        />
      </ExperienceShell>
    );
  }
  return (
    <ExperienceShell active="hypotheses">
      <HypothesisHistoricalMatchesPage data={data} query={query} />
    </ExperienceShell>
  );
}
